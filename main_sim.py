import asyncio
import random
import subprocess
import sys
import os
import time
from datetime import datetime

from src.config import *
from src.agents.Resources import AgenteDoente, AgenteTriagem, AgenteMedico, AgenteSala, AgenteEnfermeiro
from src.agents.Coordinators import (
    CoordenadorConsultas, CoordenadorUrgencias,
    CoordenadorExames, CoordenadorCirurgias,
    CoordenadorTriagem, CoordenadorInternamento,
)
from src.agents.supervisor import Supervisor
from src.agents.agente_triagem_geral import AgenteTriagemGeral


# ─────────────────────────────────────────────────────────────
#  Tee — escreve simultaneamente para o terminal E para ficheiro
# ─────────────────────────────────────────────────────────────
class _Tee:
    """Duplica stdout/stderr para o terminal e para um ficheiro."""
    def __init__(self, file_obj, original):
        self._file = file_obj
        self._original = original

    def write(self, data):
        self._original.write(data)
        self._original.flush()
        # Remove ANSI color codes before writing to file
        import re
        clean = re.sub(r'\033\[[0-9;]*m', '', data)
        self._file.write(clean)
        self._file.flush()

    def flush(self):
        self._original.flush()
        self._file.flush()

    def isatty(self):
        return self._original.isatty()


def setup_output_file():
    """Cria a pasta outputs/ e abre o ficheiro de log desta execução."""
    outputs_dir = "outputs"
    os.makedirs(outputs_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(outputs_dir, f"simulacao_{ts}.txt")
    f = open(path, "w", encoding="utf-8")
    sys.stdout = _Tee(f, sys.__stdout__)
    sys.stderr = _Tee(f, sys.__stderr__)
    return f, path


def teardown_output_file(f, path):
    """Restaura stdout/stderr e fecha o ficheiro."""
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    f.close()
    print(f"\n[OUTPUT] Log desta execução guardado em: {path}")

PATIENT_NAMES = [
    "Alice", "Bernardo", "Carla", "Duarte", "Elena", "Filipe", "Guilherme", "Helena",
    "Inês", "João", "Katia", "Luís", "Marta", "Nuno", "Olívia", "Pedro", "Quitéria",
    "Ricardo", "Sofia", "Tiago", "Ulisses", "Vera", "Walter", "Xavier", "Yara", "Zulmira"
]


async def spawn_patient(type_entry, hospital_config):
    """Spawn a patient for a specific hospital.
    
    If a random roll falls below PROB_CENTRAL_TRIAGE, the patient is redirected
    to the central triage agent regardless of their original type_entry.
    """
    name = random.choice(PATIENT_NAMES) + f"_{random.randint(100, 999)}"
    jid_str = jid(name.lower().replace(" ", "_"))

    # Decide whether to route through central triage
    use_central_triage = random.random() < PROB_CENTRAL_TRIAGE

    if use_central_triage:
        # Central triage patients keep their original type (Normal or Urgencia)
        # but are sent to the unified triage agent which decides the hospital
        actual_type = type_entry
        patient = AgenteDoente(
            jid_str, PASSWORD,
            nome_doente=name,
            tipo_entrada="Central",
            especialidade=None,  # Central triage agent will diagnose
            hospital_config=None,  # Not bound to a hospital yet
        )
        log("SIMULATOR",
            f"[SPAWN] {name} → Triagem Geral Central (tipo original={actual_type})", "MAGENTA")
    else:
        if type_entry == "Normal":
            specialty = random.choice(ROUTINE_SPECIALTIES)
        else:
            specialty = None
        patient = AgenteDoente(
            jid_str, PASSWORD,
            nome_doente=name,
            tipo_entrada=type_entry,
            especialidade=specialty,
            hospital_config=hospital_config,
        )
        hospital_id = hospital_config.get("supervisor", "").split("@")[0]
        log("SIMULATOR",
            f"[SPAWN] {name} → {hospital_id} (tipo={type_entry})", "GREEN" if type_entry == "Normal" else "RED")

    await patient.start(auto_register=True)
    return patient


async def arrival_generator(type_entry, rate, hospital_config, agents_list):
    """Generate patients at a Poisson rate for a given hospital."""
    mean_inter_arrival = 1.0 / rate
    hospital_id = hospital_config.get("supervisor", "?").split("@")[0]
    log("SIMULATOR",
        f"Starting {type_entry} arrival generator for [{hospital_id}] "
        f"(avg every {mean_inter_arrival:.1f}s)", "BOLD")

    gen_start_time = time.time()

    while True:
        wait_time = random.expovariate(rate)
        await asyncio.sleep(wait_time)
        
        elapsed = time.time() - gen_start_time
        dia_simulado_s = elapsed % SIM_DAY_SECONDS
        
        # O turno da noite ("night") corresponde à última parte do dia (ex: 16h - 24h)
        is_night = (dia_simulado_s >= 2 * SHIFT_DURATION_SECONDS)
        
        if type_entry == "Normal" and is_night:
            # Em pausa durante a noite, tentar novamente daqui a um pouco
            await asyncio.sleep(1)
            continue
            
        # Backpressure: se existirem mais de 150 pacientes a correr, aguardamos para não rebentar o OS (Errno 24)
        active_patients = [p for p in agents_list if p.is_alive()]
        if len(active_patients) > 150:
            log("SIMULATOR", f"[ALERTA] Sobrecarga do sistema ({len(active_patients)} pacientes ativos). A pausar gerador temporariamente...", "RED")
            await asyncio.sleep(5)
            continue

        try:
            p = await spawn_patient(type_entry, hospital_config)
            agents_list.append(p)
        except Exception as e:
            log("SIMULATOR", f"[ERROR] Failed to spawn {type_entry} patient: {e}", "RED")
            await asyncio.sleep(5)  # Wait before trying again


async def start_hospital(hospital_config, agents, hospital_id=1):
    """Start all infrastructure and resource agents for one hospital."""
    sup_name = hospital_config["supervisor"].split("@")[0]
    log("SIMULATOR", f"Starting hospital {hospital_id}: {sup_name}", "BOLD")

    # Coordinators
    coord_cons = CoordenadorConsultas(hospital_config["coord_cons"], PASSWORD, hospital_config=hospital_config)
    coord_urg = CoordenadorUrgencias(hospital_config["coord_urg"], PASSWORD, hospital_config=hospital_config)
    coord_exam = CoordenadorExames(hospital_config["coord_exam"], PASSWORD, hospital_config=hospital_config)
    coord_cir = CoordenadorCirurgias(hospital_config["coord_cir"], PASSWORD, hospital_config=hospital_config)
    coord_tri = CoordenadorTriagem(hospital_config["coord_tri"], PASSWORD, hospital_config=hospital_config)
    coord_int = CoordenadorInternamento(hospital_config["coord_int"], PASSWORD, hospital_config=hospital_config)
    supervisor = Supervisor(hospital_config["supervisor"], PASSWORD, hospital_config=hospital_config, hospital_id=hospital_id)

    infrastructure = [coord_cons, coord_urg, coord_exam, coord_cir, coord_tri, coord_int, supervisor]
    for a in infrastructure:
        await a.start(auto_register=True)
        agents.append(a)

    # Medics and rooms — match JIDs from hospital_config against AGENT_REGISTRY
    all_resource_jids = (
        hospital_config["medicos"]
        + hospital_config["medicos_triagem"]
        + hospital_config["salas"]
        + hospital_config["equipamentos"]
        + hospital_config["blocos"]
        + hospital_config["salas_triagem"]
        + hospital_config["internamento"]
    )

    for agent_jid_str in all_resource_jids:
        info = AGENT_REGISTRY.get(agent_jid_str, {})
        role = info.get("role")
        if role == "medic":
            a = AgenteMedico(agent_jid_str, PASSWORD,
                             nome_medico=info["name"],
                             hospital_config=hospital_config)
        elif role == "triage_medic":
            a = AgenteTriagem(agent_jid_str, PASSWORD,
                              nome_medico=info["name"],
                              hospital_config=hospital_config)
        elif role == "room":
            a = AgenteSala(agent_jid_str, PASSWORD,
                           nome_sala=info["name"],
                           hospital_config=hospital_config)
        else:
            continue
        await a.start(auto_register=True)
        agents.append(a)

    # Nurses
    for nurse_jid_str in hospital_config.get("enfermeiros", []):
        info = AGENT_REGISTRY.get(nurse_jid_str, {})
        a = AgenteEnfermeiro(nurse_jid_str, PASSWORD,
                             nome_enfermeiro=info.get("name", "Enfermeiro/a"),
                             hospital_config=hospital_config)
        await a.start(auto_register=True)
        agents.append(a)


def cleanup_state():
    """Delete stale data files to ensure a fresh start."""
    data_dir = "data"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        
    files_to_remove = ["dashboard.json", "log_supervisor.txt"]
    for f in files_to_remove:
        p = os.path.join(data_dir, f)
        if os.path.exists(p):
            try:
                os.remove(p)
                log("SIMULATOR", f"Cleaned up stale file: {f}", "CYAN")
            except:
                pass


async def main():
    log_file, log_path = setup_output_file()
    cleanup_state()
    
    print("\n" + "=" * 70)
    print("  SISTEMA MULTIAGENTE — SIMULAÇÃO HOSPITALAR MULTI-HOSPITAL")
    print("  Hospitais: H1 + H2 | Triagem Central Unificada")
    print(f"  Duração: {SIMULATION_DURATION}s | P(Triagem Central)={PROB_CENTRAL_TRIAGE:.0%}")
    print("=" * 70 + "\n")

    # 1. Dashboard
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.py")
    dashboard_proc = subprocess.Popen([sys.executable, dashboard_path])

    agents = []
    tasks = []

    try:
        # 2. Start Hospital 1
        await start_hospital(H1_CONFIG, agents, hospital_id=1)

        # 3. Start Hospital 2
        await start_hospital(H2_CONFIG, agents, hospital_id=2)

        # 4. Start Central Triage Agent
        triagem_geral = AgenteTriagemGeral(
            jid(UNIFIED_TRIAGE), PASSWORD,
            hospital_configs=[H1_CONFIG, H2_CONFIG]
        )
        await triagem_geral.start(auto_register=True)
        agents.append(triagem_geral)

        await asyncio.sleep(SIM_INFRA_READY_WAIT_SECONDS)
        log("SIMULATOR", "Infrastructure ready (H1 + H2 + Central Triage). Opening doors to patients...", "CYAN")

        # 5. Patient generators — one pair (Normal + Urgent) per hospital
        for cfg in [H1_CONFIG, H2_CONFIG]:
            tasks.append(asyncio.create_task(arrival_generator("Normal", ARRIVAL_RATE_NORMAL, cfg, agents)))
            tasks.append(asyncio.create_task(arrival_generator("Urgencia", ARRIVAL_RATE_URGENT, cfg, agents)))

        # 6. Run simulation
        start_time = time.time()
        while time.time() - start_time < SIMULATION_DURATION:
            await asyncio.sleep(SIM_PROGRESS_TICK_SECONDS)
            elapsed = int(time.time() - start_time)
            print(f"--- SIMULATION PROGRESS: {elapsed}/{SIMULATION_DURATION}s ---")

    except KeyboardInterrupt:
        log("SIMULATOR", "Simulation interrupted by user.", "YELLOW")
    except Exception as e:
        log("SIMULATOR", f"Unexpected error: {str(e)}", "RED")
        import traceback
        traceback.print_exc()
    finally:
        # 7. Shutdown
        for t in tasks:
            t.cancel()

        log("SIMULATOR", f"Closing hospitals. Discharging {len(agents)} active agents...", "BOLD")
        
        # Stop patients first (they are often the ones sending msgs)
        active_agents = list(agents) # Copy to avoid mutation issues
        for a in reversed(active_agents):
            try:
                await a.stop()
            except:
                pass

        if dashboard_proc:
            dashboard_proc.terminate()
            
        print("=" * 70)
        print("  SIMULAÇÃO CONCLUÍDA")
    print("=" * 70 + "\n")

    teardown_output_file(log_file, log_path)


if __name__ == "__main__":
    try:
        import spade
        if hasattr(spade, "run"):
            spade.run(main())
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SIMULAÇÃO] Interrompida pelo utilizador.")
