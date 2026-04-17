import asyncio
import subprocess

from src.config import *
from src.agents.Resources import AgenteDoente, AgenteTriagem, AgenteMedico, AgenteSala
from src.agents.Coordinators import (
    CoordenadorConsultas, CoordenadorUrgencias,
    CoordenadorExames, CoordenadorCirurgias,
)
from src.agents.supervisor import Supervisor


PATIENT_N1_ID = "doente_n1"
PATIENT_N2_ID = "doente_n2"
PATIENT_U1_ID = "doente_u1"


async def main():
    """
    Função principal assíncrona.
    Instancia e inicia todos os agentes, depois executa o cenário de teste
    com delays cronológicos para produzir um log claro e legível.
    """

    print("\n" + "=" * 70)
    print("  SISTEMA MULTIAGENTE — GESTÃO HOSPITALAR (PEDIATRIA)")
    print("  Framework: SPADE | Protocolo: FIPA-Contract-Net")
    print("  Servidor XMPP: " + XMPP_SERVER)
    print("=" * 70 + "\n")

    # ==========================================================
    # ARRANQUE DO DASHBOARD & AGENTES DE INFRAESTRUTURA
    # ==========================================================
    log("SISTEMA", "MaaS Architecture Boot: A inicializar Dashboard Web em http://localhost:8000 ...", "CYAN")
    dashboard_proc = subprocess.Popen(["python3", "dashboard.py"])

    # Médico
    medico1 = AgenteMedico(
        jid(MEDICO1), PASSWORD,
        nome_medico=AGENT_REGISTRY[jid(MEDICO1)]["name"]
    )
    await medico1.start(auto_register=True)

    # Sala
    sala1 = AgenteSala(
        jid(SALA1), PASSWORD,
        nome_sala=AGENT_REGISTRY[jid(SALA1)]["name"]
    )
    await sala1.start(auto_register=True)

    # Sala de Raio-X
    sala_raiox = AgenteSala(
        jid(SALA_RAIOX), PASSWORD,
        nome_sala=AGENT_REGISTRY[jid(SALA_RAIOX)]["name"]
    )
    await sala_raiox.start(auto_register=True)

    # Bloco Operatório
    bloco_op = AgenteSala(
        jid(BLOCO_OPERATORIO1), PASSWORD,
        nome_sala=AGENT_REGISTRY[jid(BLOCO_OPERATORIO1)]["name"]
    )
    await bloco_op.start(auto_register=True)

    # ==========================================================
    # ARRANQUE DOS AGENTES DE COORDENAÇÃO
    # ==========================================================

    coord_cons = CoordenadorConsultas(jid(COORD_CONS), PASSWORD)
    await coord_cons.start(auto_register=True)

    coord_urg = CoordenadorUrgencias(jid(COORD_URG), PASSWORD)
    await coord_urg.start(auto_register=True)

    coord_exam = CoordenadorExames(jid(COORD_EXAM), PASSWORD)
    await coord_exam.start(auto_register=True)

    coord_cir = CoordenadorCirurgias(jid(COORD_CIR), PASSWORD)
    await coord_cir.start(auto_register=True)

    # Triagem
    triagem = AgenteTriagem(jid(TRIAGEM), PASSWORD)
    await triagem.start(auto_register=True)

    # ==========================================================
    # ARRANQUE DA SUPERVISÃO
    # ==========================================================

    supervisor = Supervisor(jid(SUPERVISOR), PASSWORD)
    await supervisor.start(auto_register=True)

    # Aguardar estabilização de todos os agentes
    await asyncio.sleep(MAIN_STARTUP_STABILIZATION_SECONDS)

    # ==========================================================
    # FASE 1: Doente Normal 1 — Consulta de rotina
    # ==========================================================
    print("\n" + "-" * 70)
    print("  FASE 1: Doente Normal 1 — Pedido de consulta de rotina")
    print("-" * 70 + "\n")

    doente_n1 = AgenteDoente(
        jid(PATIENT_N1_ID), PASSWORD,
        nome_doente="Joao Nunes",
        tipo_entrada="Normal",
        sintomas="Febre ligeira, tosse",
        prioridade=2,
    )
    await doente_n1.start(auto_register=True)

    # Aguardar apenas 2 segundos para que a Fase 2 arranque ENQUANTO o João da Fase 1 ainda está em consulta (que demora 4s)
    await asyncio.sleep(MAIN_PHASE_GAP_SECONDS)

    # ==========================================================
    # FASE 2: Doente Normal 2 — Recursos já ocupados
    # ==========================================================
    print("\n" + "-" * 70)
    print("  FASE 2: Doente Normal 2 — Pedido (recursos já ocupados)")
    print("-" * 70 + "\n")

    doente_n2 = AgenteDoente(
        jid(PATIENT_N2_ID), PASSWORD,
        nome_doente="Maria Costa",
        tipo_entrada="Normal",
        sintomas="Dor de ouvido",
        prioridade=1,
    )
    await doente_n2.start(auto_register=True)

    # Aguardar processamento
    await asyncio.sleep(MAIN_POST_PHASE2_WAIT_SECONDS)

    # ==========================================================
    # FASE 3: URGÊNCIA — Preemption / Reescalonamento Dinâmico
    # ==========================================================
    print("\n" + "-" * 70)
    print("  FASE 3: URGÊNCIA — Preemption / Reescalonamento Dinâmico")
    print("-" * 70 + "\n")

    doente_u1 = AgenteDoente(
        jid(PATIENT_U1_ID), PASSWORD,
        nome_doente="Pedro Alves",
        tipo_entrada="Urgencia",
        sintomas="Dificuldade respiratória aguda, cianose",
        prioridade=0,  # Prioridade será atualizada pela Triagem
    )
    await doente_u1.start(auto_register=True)

    # Aguardar todo o fluxo: Triagem → Supervisor → Preemption → Contract-Net
    await asyncio.sleep(MAIN_URGENT_FLOW_WAIT_SECONDS)

    # ==========================================================
    # FASE 4: Cascata de Cuidados — Exame → Cirurgia (Totalmente Autónoma)
    # ==========================================================
    print("\n" + "-" * 70)
    print("  FASE 4: Cascata de Cuidados Autónoma (Exame → Cirurgia)")
    print("-" * 70 + "\n")

    # Aguardar que o AgenteMedico (Dr. Silva) diagnostique autonomamente o Pedro,
    # solicite o Exame, aguarde, e acione a Cirurgia.
    await asyncio.sleep(MAIN_CASCADE_WAIT_SECONDS)

    # Parar todos os agentes de forma ordenada
    agents = [
        doente_n1, doente_n2, doente_u1,
        triagem, coord_cons, coord_urg, coord_exam, coord_cir,
        medico1, sala1, sala_raiox, bloco_op, supervisor,   
    ]
    for a in agents:
        await a.stop()

    dashboard_proc.terminate()
    log("SISTEMA", "Execução do sistema terminada com sucesso.", "BOLD")


# ============================================================================
# ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    try:
        import spade
        if hasattr(spade, "run"):
            spade.run(main())
        else:
            asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SISTEMA] Simulação interrompida pelo utilizador.")
