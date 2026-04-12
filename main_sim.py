import asyncio
import random
import subprocess
import time

from src.config import *
from src.agents.resources import AgenteDoente, AgenteTriagem, AgenteMedico, AgenteSala
from src.agents.coordinators import (
    CoordenadorConsultas, CoordenadorUrgencias,
    CoordenadorExames, CoordenadorCirurgias,
)
from src.agents.supervisor import Supervisor

# Mock data 
PATIENT_NAMES = [
    "Alice", "Bernardo", "Carla", "Duarte", "Elena", "Filipe", "Guilherme", "Helena",
    "Inês", "João", "Katia", "Luís", "Marta", "Nuno", "Olívia", "Pedro", "Quitéria",
    "Ricardo", "Sofia", "Tiago", "Ulisses", "Vera", "Walter", "Xavier", "Yara", "Zulmira"
]

SYMPTOMS_ROUTINE = ["Tosse ligeira", "Febre baixa", "Vómitos", "Dor de garganta", "Borbulhas na pele"]
SYMPTOMS_URGENT = ["Dificuldade respiratória", "Cianose", "Traumatismo craniano", "Hemorragia", "Convulsão"]

async def spawn_patient(type_entry):
    name = random.choice(PATIENT_NAMES) + f"_{random.randint(100, 999)}"
    jid_str = jid(name.lower().replace(" ", "_"))
    
    if type_entry == "Normal":
        symptoms = random.choice(SYMPTOMS_ROUTINE)
        priority = random.randint(1, 3)
        color = "GREEN"
    else:
        symptoms = random.choice(SYMPTOMS_URGENT)
        priority = 0 # Vai ser avaliado na triagem
        color = "RED"

    patient = AgenteDoente(
        jid_str, PASSWORD,
        nome_doente=name,
        tipo_entrada=type_entry,
        sintomas=symptoms,
        prioridade=priority
    )
    await patient.start(auto_register=True)
    return patient

# Gerador de pacientes
async def arrival_generator(type_entry, rate):
    all_patients = []
    mean_inter_arrival = 1.0 / rate
    
    log("SIMULATOR", f"Starting {type_entry} arrival generator (avg every {mean_inter_arrival:.1f}s)", "BOLD")
    
    while True:
        wait_time = random.expovariate(rate)
        await asyncio.sleep(wait_time)
        
        p = await spawn_patient(type_entry)
        all_patients.append(p)
        
async def main():
    print("\n" + "=" * 70)
    print("  SISTEMA MULTIAGENTE — SIMULAÇÃO HOSPITALAR REALISTA")
    print("  Duração: " + str(SIMULATION_DURATION) + "s | Escala: Médica/Surgical Full")
    print("=" * 70 + "\n")

    # 1. Dashboard
    dashboard_proc = subprocess.Popen(["python3", "dashboard.py"])
    
    # 2. Agentes
    agents = []
    
    # Coordenadores
    coord_cons = CoordenadorConsultas(jid(COORD_CONS), PASSWORD)
    coord_urg = CoordenadorUrgencias(jid(COORD_URG), PASSWORD)
    coord_exam = CoordenadorExames(jid(COORD_EXAM), PASSWORD)
    coord_cir = CoordenadorCirurgias(jid(COORD_CIR), PASSWORD)
    
    # Infraestrutura
    triagem = AgenteTriagem(jid(TRIAGEM), PASSWORD)
    supervisor = Supervisor(jid(SUPERVISOR), PASSWORD)
    
    infrastructure = [coord_cons, coord_urg, coord_exam, coord_cir, triagem, supervisor]
    for a in infrastructure:
        await a.start(auto_register=True)
        agents.append(a)

    # Recursos Físicos (Médicos, Salas)
    for agent_jid, info in AGENT_REGISTRY.items():
        if info["role"] == "medic":
            a = AgenteMedico(agent_jid, PASSWORD, nome_medico=info["name"])
        elif info["role"] == "room":
            a = AgenteSala(agent_jid, PASSWORD, nome_sala=info["name"])
        else:
            continue
            
        await a.start(auto_register=True)
        agents.append(a)

    await asyncio.sleep(2)
    log("SIMULATOR", "Infrastructure ready. Opening doors to patients...", "CYAN")

    # 3. Gerar Pacientes
    routine_task = asyncio.create_task(arrival_generator("Normal", ARRIVAL_RATE_NORMAL))
    urgent_task = asyncio.create_task(arrival_generator("Urgencia", ARRIVAL_RATE_URGENT))

    # 4. Duração da Simulação
    start_time = time.time()
    try:
        while time.time() - start_time < SIMULATION_DURATION:
            await asyncio.sleep(5)
            elapsed = int(time.time() - start_time)
            print(f"--- SIMULATION PROGRESS: {elapsed}/{SIMULATION_DURATION}s ---")
    except KeyboardInterrupt:
        pass

    # 5. Desligar
    routine_task.cancel()
    urgent_task.cancel()
    
    log("SIMULATOR", "Closing hospital. Discharging agents...", "BOLD")
    for a in agents:
        await a.stop()
    
    dashboard_proc.terminate()
    print("=" * 70)
    print("  SIMULAÇÃO CONCLUÍDA")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    try:
        import spade
        if hasattr(spade, "run"):
            spade.run(main())
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SIMULAÇÃO] Interrompida pelo utilizador.")
