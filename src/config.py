import os
from datetime import datetime
from dotenv import load_dotenv

# load_dotenv()

from src.patch import apply_xmpp_patch
apply_xmpp_patch()

# Configuração do Servidor XMPP
XMPP_SERVER = os.getenv("XMPP_SERVER", "127.0.0.1")
PASSWORD = os.getenv("XMPP_PASSWORD", "password")

def jid(name: str) -> str:
    return f"{name}@{XMPP_SERVER}"

# ────────────────────────────────────────────────────────────
#  Hospital 1 (H1) — original names kept for backward-compat
# ────────────────────────────────────────────────────────────
MEDICO1 = "medico1"
MEDICO2 = "medico2"
MEDICO3 = "medico3"
MEDICO4 = "medico4"
MEDICO5 = "medico5"
MEDICO6 = "medico6"
MEDICO7 = "medico7"
MEDICO8 = "medico8"
MEDICO9 = "medico9"
MEDICO10 = "medico10"
MEDICO11 = "medico11"
MEDICO12 = "medico12"
MEDICO13 = "medico13"
MEDICO14 = "medico14"
MEDICO15 = "medico15"

MEDICO_TRIAGEM1 = "medico_triagem1"
MEDICO_TRIAGEM2 = "medico_triagem2"

SALA1 = "sala1"
SALA2 = "sala2"
SALA3 = "sala3"
SALA4 = "sala4"
SALA5 = "sala5"
SALA6 = "sala6"
SALA7 = "sala7"
SALA8 = "sala8"
SALA9 = "sala9"
SALA10 = "sala10"

ENFERMEIRO1 = "enfermeiro1"
ENFERMEIRO2 = "enfermeiro2"
ENFERMEIRO3 = "enfermeiro3"

H2_ENFERMEIRO1 = "h2_enfermeiro1"
H2_ENFERMEIRO2 = "h2_enfermeiro2"
H2_ENFERMEIRO3 = "h2_enfermeiro3"

COORD_CONS = "coord_consultas"
COORD_URG = "coord_urgencias"
COORD_EXAM = "coord_exames"
COORD_CIR = "coord_cirurgias"
COORD_TRI = "coord_triagem"
COORD_INT = "coord_internamento"
SUPERVISOR = "supervisor"

SALA_TRIAGEM1 = "sala_triagem1"
SALA_TRIAGEM2 = "sala_triagem2"

INTERNAMENTO1 = "internamento1"
INTERNAMENTO2 = "internamento2"
INTERNAMENTO3 = "internamento3"
INTERNAMENTO4 = "internamento4"

SALA_RAIOX1 = "sala_raiox1"
SALA_RAIOX2 = "sala_raiox2"
SALA_TAC1 = "sala_tac1"
SALA_TAC2 = "sala_tac2"
SALA_ANALISES1 = "sala_analises1"
SALA_ANALISES2 = "sala_analises2"

BLOCO_OPERATORIO1 = "bloco_operatorio1"
BLOCO_OPERATORIO2 = "bloco_operatorio2"
BLOCO_OPERATORIO3 = "bloco_operatorio3"

# ────────────────────────────────────────────────────────────
#  Hospital 2 (H2) — h2_ prefix
# ────────────────────────────────────────────────────────────
H2_MEDICO1 = "h2_medico1"
H2_MEDICO2 = "h2_medico2"
H2_MEDICO3 = "h2_medico3"
H2_MEDICO4 = "h2_medico4"
H2_MEDICO5 = "h2_medico5"
H2_MEDICO6 = "h2_medico6"
H2_MEDICO7 = "h2_medico7"
H2_MEDICO8 = "h2_medico8"
H2_MEDICO9 = "h2_medico9"
H2_MEDICO10 = "h2_medico10"
H2_MEDICO11 = "h2_medico11"
H2_MEDICO12 = "h2_medico12"
H2_MEDICO13 = "h2_medico13"
H2_MEDICO14 = "h2_medico14"
H2_MEDICO15 = "h2_medico15"

H2_MEDICO_TRIAGEM1 = "h2_medico_triagem1"
H2_MEDICO_TRIAGEM2 = "h2_medico_triagem2"

H2_SALA1 = "h2_sala1"
H2_SALA2 = "h2_sala2"
H2_SALA3 = "h2_sala3"
H2_SALA4 = "h2_sala4"
H2_SALA5 = "h2_sala5"
H2_SALA6 = "h2_sala6"
H2_SALA7 = "h2_sala7"
H2_SALA8 = "h2_sala8"
H2_SALA9 = "h2_sala9"
H2_SALA10 = "h2_sala10"

H2_COORD_CONS = "h2_coord_consultas"
H2_COORD_URG = "h2_coord_urgencias"
H2_COORD_EXAM = "h2_coord_exames"
H2_COORD_CIR = "h2_coord_cirurgias"
H2_COORD_TRI = "h2_coord_triagem"
H2_COORD_INT = "h2_coord_internamento"
H2_SUPERVISOR = "h2_supervisor"

H2_SALA_TRIAGEM1 = "h2_sala_triagem1"
H2_SALA_TRIAGEM2 = "h2_sala_triagem2"

H2_INTERNAMENTO1 = "h2_internamento1"
H2_INTERNAMENTO2 = "h2_internamento2"
H2_INTERNAMENTO3 = "h2_internamento3"
H2_INTERNAMENTO4 = "h2_internamento4"

H2_SALA_RAIOX1 = "h2_sala_raiox1"
H2_SALA_RAIOX2 = "h2_sala_raiox2"
H2_SALA_TAC1 = "h2_sala_tac1"
H2_SALA_TAC2 = "h2_sala_tac2"
H2_SALA_ANALISES1 = "h2_sala_analises1"
H2_SALA_ANALISES2 = "h2_sala_analises2"

H2_BLOCO_OPERATORIO1 = "h2_bloco_operatorio1"
H2_BLOCO_OPERATORIO2 = "h2_bloco_operatorio2"
H2_BLOCO_OPERATORIO3 = "h2_bloco_operatorio3"

# ────────────────────────────────────────────────────────────
#  Central / Unified triage agent
# ────────────────────────────────────────────────────────────
UNIFIED_TRIAGE = "triagem_geral"

# ────────────────────────────────────────────────────────────
#  Escalas e carga horária simulada
# ────────────────────────────────────────────────────────────
WEEKLY_MAX_HOURS = 40
SIM_HOUR_SECONDS = 10          # 10 segundos reais = 1 hora simulada
SIM_DAY_SECONDS = 24 * SIM_HOUR_SECONDS
SIM_WEEK_SECONDS = 7 * SIM_DAY_SECONDS
ALLOW_EMERGENCY_CALL_OUTSIDE_SHIFT = True

SHIFT_DURATION_HOURS = 8
SHIFT_DURATION_SECONDS = SHIFT_DURATION_HOURS * SIM_HOUR_SECONDS

# Janela permitida para consultas de rotina
ROUTINE_START_H = 8
ROUTINE_END_H = 20

# Duração em horas simuladas por tipo de procedimento
# Valores fracionados para sincronizar com o tempo real (1 hora simulada = 10s)
PROCEDURE_HOURS = {
    "consultation": 0.3,
    "emergency":    0.2,
    "exam":         0.3,
    "surgery":      0.6,
    "triage":       0.1,
    "internment":   2.0,
}

# Valores da Simulação
SIMULATION_WEEKS = 1
# Duração real da demonstração. Por defeito fica em 3 minutos para a defesa;
# se for preciso correr uma semana simulada completa, definir SIMULATION_DURATION=1680 no ambiente.
SIMULATION_DURATION = int(os.getenv("SIMULATION_DURATION", "180"))
ARRIVAL_RATE_NORMAL = 0.3  # reduzido para a capacidade do hospital
ARRIVAL_RATE_URGENT = 0.05 # reduzido para a capacidade do hospital

# Probability that a newly spawned patient is redirected to the central triage agent
PROB_CENTRAL_TRIAGE = 0.3

# Temporização (segundos)
SUPERVISOR_DUMP_INTERVAL_SECONDS = 1
SUPERVISOR_RECEIVE_TIMEOUT_SECONDS = 5

COORDINATOR_RECEIVE_TIMEOUT_SECONDS = 1
COORDINATOR_PROPOSAL_TIMEOUT_SECONDS = 1.5
RESOURCE_RECEIVE_TIMEOUT_SECONDS = 10
DISPATCH_BATCH_LIMIT = 2

CONTRACT_NET_RESPONSE_WAIT_SECONDS = 0.75
TRIAGE_CONTRACT_NET_RESPONSE_WAIT_SECONDS = 1
TRIAGE_CONTRACT_NET_PROPOSAL_TIMEOUT_SECONDS = 2
INTERNMENT_CONTRACT_NET_RESPONSE_WAIT_SECONDS = 1
INTERNMENT_CONTRACT_NET_PROPOSAL_TIMEOUT_SECONDS = 2
INTERNMENT_RETRY_BASE_SECONDS = 5
INTERNMENT_RETRY_MAX_SECONDS = 30
INTERNMENT_MAX_RETRIES = 6

EXAM_RETRY_BASE_SECONDS = 3
EXAM_RETRY_MAX_SECONDS = 20
EXAM_MAX_RETRIES = 5

SURGERY_RETRY_BASE_SECONDS = 4
SURGERY_RETRY_MAX_SECONDS = 30
SURGERY_MAX_RETRIES = 5

PREEMPTION_CONFIRM_WAIT_SECONDS = 2

CONSULTATION_DURATION_NORMAL_SECONDS = 3
CONSULTATION_DURATION_URGENT_SECONDS = 2
EXAM_RESULTS_WAIT_SECONDS = 2  # mantido por compatibilidade; o fluxo agora espera por exam_result real
PROCEDURE_RESULT_TIMEOUT_SECONDS = 15  # mantido por compatibilidade
EXAM_RESULT_TIMEOUT_SECONDS = 60
SURGERY_RESULT_TIMEOUT_SECONDS = 90
SURGERY_DURATION_SECONDS = 6
EXAM_DURATION_SECONDS = 3
TRIAGE_CLASSIFICATION_SECONDS = 1

CENTRAL_TRIAGE_DIAGNOSIS_SECONDS = 2  # time for central triage agent to diagnose
LOAD_QUERY_RESPONSE_WAIT_SECONDS = 3  # timeout to collect load_query responses

SIM_INFRA_READY_WAIT_SECONDS = 2
SIM_PROGRESS_TICK_SECONDS = 5

# Probabilidades de Fluxo Clínico
PROB_EXAM_URGENT = 0.8  # 80% dos urgentes vão a exame
PROB_EXAM_NORMAL = 0.2  # 20% dos de rotina vão a exame
PROB_SURGERY_AFTER_EXAM = 0.5  # 50% dos que fazem exame vão para cirurgia
PROB_INTERNAMENTO_URGENT = 0.4

INTERNAMENTO_MIN_SECONDS = 15
INTERNAMENTO_MAX_SECONDS = 30

URGENT_PRIORITY_MIN = 0
URGENT_PRIORITY_MAX = 3

SPECIALTY_RX = "raio_x"
SPECIALTY_TAC = "tac"
SPECIALTY_ANALISES = "analises"
SPECIALTY_CIRURGIA = "cirurgia"
SPECIALTY_PEDIATRIA = "pediatria"
SPECIALTY_ORTOPEDIA = "ortopedia"
SPECIALTY_CARDIOLOGIA = "cardiologia"
SPECIALTY_TRIAGEM = "triagem"

ROUTINE_SPECIALTIES = [
    SPECIALTY_PEDIATRIA,
    SPECIALTY_ORTOPEDIA,
    SPECIALTY_CARDIOLOGIA,
]

URGENT_TRIAGE_SPECIALTIES = list(ROUTINE_SPECIALTIES)

# ────────────────────────────────────────────────────────────
#  Hospital configs — passed to each agent as hospital_config
# ────────────────────────────────────────────────────────────

def build_hospital_config(
    supervisor_name,
    coord_cons_name, coord_urg_name, coord_exam_name,
    coord_cir_name, coord_tri_name, coord_int_name,
    medicos_names, medicos_triagem_names,
    salas_names, equipamentos_map, blocos_names,
    salas_triagem_names, internamento_names,
    enfermeiros_names=None,
):
    """Build the full hospital_config dict used by all agents."""
    return {
        "supervisor": jid(supervisor_name),
        "coord_cons": jid(coord_cons_name),
        "coord_urg": jid(coord_urg_name),
        "coord_exam": jid(coord_exam_name),
        "coord_cir": jid(coord_cir_name),
        "coord_tri": jid(coord_tri_name),
        "coord_int": jid(coord_int_name),
        "medicos": [jid(m) for m in medicos_names],
        "medicos_triagem": [jid(m) for m in medicos_triagem_names],
        "salas": [jid(s) for s in salas_names],
        # equipamentos_map: list of (jid_name, specialty) tuples
        "equipamentos": [jid(s) for s, _ in equipamentos_map],
        "equipamentos_specialty": {jid(s): sp for s, sp in equipamentos_map},
        "blocos": [jid(b) for b in blocos_names],
        "salas_triagem": [jid(s) for s in salas_triagem_names],
        "internamento": [jid(s) for s in internamento_names],
        "enfermeiros": [jid(e) for e in (enfermeiros_names or [])],
    }


# ── Hospital 1 config ──
H1_CONFIG = build_hospital_config(
    supervisor_name=SUPERVISOR,
    coord_cons_name=COORD_CONS, coord_urg_name=COORD_URG,
    coord_exam_name=COORD_EXAM, coord_cir_name=COORD_CIR,
    coord_tri_name=COORD_TRI, coord_int_name=COORD_INT,
    medicos_names=[MEDICO1, MEDICO2, MEDICO3, MEDICO4, MEDICO5,
                   MEDICO6, MEDICO7, MEDICO8, MEDICO9, MEDICO10,
                   MEDICO11, MEDICO12, MEDICO13, MEDICO14, MEDICO15],
    medicos_triagem_names=[MEDICO_TRIAGEM1, MEDICO_TRIAGEM2],
    salas_names=[SALA1, SALA2, SALA3, SALA4, SALA5,
                 SALA6, SALA7, SALA8, SALA9, SALA10],
    equipamentos_map=[
        (SALA_RAIOX1, SPECIALTY_RX), (SALA_RAIOX2, SPECIALTY_RX),
        (SALA_TAC1, SPECIALTY_TAC), (SALA_TAC2, SPECIALTY_TAC),
        (SALA_ANALISES1, SPECIALTY_ANALISES), (SALA_ANALISES2, SPECIALTY_ANALISES),
    ],
    blocos_names=[BLOCO_OPERATORIO1, BLOCO_OPERATORIO2, BLOCO_OPERATORIO3],
    salas_triagem_names=[SALA_TRIAGEM1, SALA_TRIAGEM2],
    internamento_names=[INTERNAMENTO1, INTERNAMENTO2, INTERNAMENTO3, INTERNAMENTO4],
    enfermeiros_names=[ENFERMEIRO1, ENFERMEIRO2, ENFERMEIRO3],
)

# ── Hospital 2 config ──
H2_CONFIG = build_hospital_config(
    supervisor_name=H2_SUPERVISOR,
    coord_cons_name=H2_COORD_CONS, coord_urg_name=H2_COORD_URG,
    coord_exam_name=H2_COORD_EXAM, coord_cir_name=H2_COORD_CIR,
    coord_tri_name=H2_COORD_TRI, coord_int_name=H2_COORD_INT,
    medicos_names=[H2_MEDICO1, H2_MEDICO2, H2_MEDICO3, H2_MEDICO4, H2_MEDICO5,
                   H2_MEDICO6, H2_MEDICO7, H2_MEDICO8, H2_MEDICO9, H2_MEDICO10,
                   H2_MEDICO11, H2_MEDICO12, H2_MEDICO13, H2_MEDICO14, H2_MEDICO15],
    medicos_triagem_names=[H2_MEDICO_TRIAGEM1, H2_MEDICO_TRIAGEM2],
    salas_names=[H2_SALA1, H2_SALA2, H2_SALA3, H2_SALA4, H2_SALA5,
                 H2_SALA6, H2_SALA7, H2_SALA8, H2_SALA9, H2_SALA10],
    equipamentos_map=[
        (H2_SALA_RAIOX1, SPECIALTY_RX), (H2_SALA_RAIOX2, SPECIALTY_RX),
        (H2_SALA_TAC1, SPECIALTY_TAC), (H2_SALA_TAC2, SPECIALTY_TAC),
        (H2_SALA_ANALISES1, SPECIALTY_ANALISES), (H2_SALA_ANALISES2, SPECIALTY_ANALISES),
    ],
    blocos_names=[H2_BLOCO_OPERATORIO1, H2_BLOCO_OPERATORIO2, H2_BLOCO_OPERATORIO3],
    salas_triagem_names=[H2_SALA_TRIAGEM1, H2_SALA_TRIAGEM2],
    internamento_names=[H2_INTERNAMENTO1, H2_INTERNAMENTO2, H2_INTERNAMENTO3, H2_INTERNAMENTO4],
    enfermeiros_names=[H2_ENFERMEIRO1, H2_ENFERMEIRO2, H2_ENFERMEIRO3],
)

# ────────────────────────────────────────────────────────────
#  Agent Registry (used by Dashboard / Supervisor)
# ────────────────────────────────────────────────────────────
def _build_registry_for_hospital(prefix, hospital_id, doctor_names, names):
    """Build registry entries for one hospital. prefix='' for H1, 'h2_' for H2."""
    p = prefix
    return {
        jid(f"{p}medico1"): {"name": f"[H{hospital_id}] Dr. Jose Silva",      "type": "Especialista", "role": "medic", "zone": "normal",   "specialty": SPECIALTY_PEDIATRIA,  "hospital": hospital_id, "shift": "morning"},
        jid(f"{p}medico2"): {"name": f"[H{hospital_id}] Dra. Beatriz Santos", "type": "Especialista", "role": "medic", "zone": "normal",   "specialty": SPECIALTY_ORTOPEDIA,  "hospital": hospital_id, "shift": "morning"},
        jid(f"{p}medico3"): {"name": f"[H{hospital_id}] Dr. Henrique Costa",  "type": "Especialista", "role": "medic", "zone": "normal",   "specialty": SPECIALTY_CARDIOLOGIA,"hospital": hospital_id, "shift": "morning"},
        jid(f"{p}medico4"): {"name": f"[H{hospital_id}] Dr. Ricardo Lima",    "type": "Especialista", "role": "medic", "zone": "surgical", "specialty": SPECIALTY_CIRURGIA,   "hospital": hospital_id, "shift": "morning"},
        jid(f"{p}medico5"): {"name": f"[H{hospital_id}] Dra. Ana Leal",       "type": "Especialista", "role": "medic", "zone": "exam",     "specialty": SPECIALTY_RX,         "hospital": hospital_id, "shift": "morning"},
        jid(f"{p}medico6"): {"name": f"[H{hospital_id}] Dr. Hugo Ribeiro",    "type": "Especialista", "role": "medic", "zone": "exam",     "specialty": SPECIALTY_TAC,        "hospital": hospital_id, "shift": "morning"},
        jid(f"{p}medico7"): {"name": f"[H{hospital_id}] Dra. Marta Faria",    "type": "Especialista", "role": "medic", "zone": "exam",     "specialty": SPECIALTY_ANALISES,   "hospital": hospital_id, "shift": "morning"},
        jid(f"{p}medico8"): {"name": f"[H{hospital_id}] Dr. Paulo Rocha",     "type": "Especialista", "role": "medic", "zone": "normal",   "specialty": SPECIALTY_PEDIATRIA,  "hospital": hospital_id, "shift": "afternoon"},
        jid(f"{p}medico9"): {"name": f"[H{hospital_id}] Dra. Rita Goncalves", "type": "Especialista", "role": "medic", "zone": "normal",   "specialty": SPECIALTY_ORTOPEDIA,  "hospital": hospital_id, "shift": "afternoon"},
        jid(f"{p}medico10"):{"name": f"[H{hospital_id}] Dr. Bruno Martins",   "type": "Especialista", "role": "medic", "zone": "normal",   "specialty": SPECIALTY_CARDIOLOGIA,"hospital": hospital_id, "shift": "afternoon"},
        jid(f"{p}medico11"):{"name": f"[H{hospital_id}] Dra. Sara Pires",     "type": "Especialista", "role": "medic", "zone": "exam",     "specialty": SPECIALTY_RX,         "hospital": hospital_id, "shift": "afternoon"},
        jid(f"{p}medico12"):{"name": f"[H{hospital_id}] Dr. Andre Lopes",     "type": "Especialista", "role": "medic", "zone": "exam",     "specialty": SPECIALTY_TAC,        "hospital": hospital_id, "shift": "afternoon"},
        jid(f"{p}medico13"):{"name": f"[H{hospital_id}] Dra. Mariana Teixeira","type":"Especialista", "role": "medic", "zone": "exam",     "specialty": SPECIALTY_ANALISES,   "hospital": hospital_id, "shift": "afternoon"},
        jid(f"{p}medico14"):{"name": f"[H{hospital_id}] Dr. Carlos Nogueira", "type": "Urgencista",   "role": "medic", "zone": "normal",   "specialty": SPECIALTY_PEDIATRIA,  "hospital": hospital_id, "shift": "night"},
        jid(f"{p}medico15"):{"name": f"[H{hospital_id}] Dra. Ines Simoes",    "type": "Urgencista",   "role": "medic", "zone": "surgical", "specialty": SPECIALTY_CIRURGIA,   "hospital": hospital_id, "shift": "night"},
        jid(f"{p}medico_triagem1"): {"name": f"[H{hospital_id}] Dr. Tiago Pinto",   "type": "Triagem", "role": "triage_medic", "zone": "triage", "specialty": SPECIALTY_TRIAGEM, "hospital": hospital_id, "shift": "morning"},
        jid(f"{p}medico_triagem2"): {"name": f"[H{hospital_id}] Dra. Leonor Viana", "type": "Triagem", "role": "triage_medic", "zone": "triage", "specialty": SPECIALTY_TRIAGEM, "hospital": hospital_id, "shift": "afternoon"},

        jid(f"{p}sala1"):  {"name": f"[H{hospital_id}] Consultorio 1",  "wing": "primary",    "role": "room", "hospital": hospital_id},
        jid(f"{p}sala2"):  {"name": f"[H{hospital_id}] Consultorio 2",  "wing": "primary",    "role": "room", "hospital": hospital_id},
        jid(f"{p}sala3"):  {"name": f"[H{hospital_id}] Consultorio 3",  "wing": "primary",    "role": "room", "hospital": hospital_id},
        jid(f"{p}sala4"):  {"name": f"[H{hospital_id}] Consultorio 4",  "wing": "primary",    "role": "room", "hospital": hospital_id},
        jid(f"{p}sala5"):  {"name": f"[H{hospital_id}] Consultorio 5",  "wing": "primary",    "role": "room", "hospital": hospital_id},
        jid(f"{p}sala6"):  {"name": f"[H{hospital_id}] Consultorio 6",  "wing": "primary",    "role": "room", "hospital": hospital_id},
        jid(f"{p}sala7"):  {"name": f"[H{hospital_id}] Consultorio 7",  "wing": "primary",    "role": "room", "hospital": hospital_id},
        jid(f"{p}sala8"):  {"name": f"[H{hospital_id}] Consultorio 8",  "wing": "primary",    "role": "room", "hospital": hospital_id},
        jid(f"{p}sala9"):  {"name": f"[H{hospital_id}] Consultorio 9",  "wing": "primary",    "role": "room", "hospital": hospital_id},
        jid(f"{p}sala10"): {"name": f"[H{hospital_id}] Consultorio 10", "wing": "primary",    "role": "room", "hospital": hospital_id},

        jid(f"{p}sala_raiox1"):   {"name": f"[H{hospital_id}] Sala de Raio-X 1",  "wing": "specialized", "role": "room", "specialty": SPECIALTY_RX,       "hospital": hospital_id},
        jid(f"{p}sala_raiox2"):   {"name": f"[H{hospital_id}] Sala de Raio-X 2",  "wing": "specialized", "role": "room", "specialty": SPECIALTY_RX,       "hospital": hospital_id},
        jid(f"{p}sala_tac1"):     {"name": f"[H{hospital_id}] Sala de TAC 1",      "wing": "specialized", "role": "room", "specialty": SPECIALTY_TAC,      "hospital": hospital_id},
        jid(f"{p}sala_tac2"):     {"name": f"[H{hospital_id}] Sala de TAC 2",      "wing": "specialized", "role": "room", "specialty": SPECIALTY_TAC,      "hospital": hospital_id},
        jid(f"{p}sala_analises1"):{"name": f"[H{hospital_id}] Sala de Analises 1", "wing": "specialized", "role": "room", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id},
        jid(f"{p}sala_analises2"):{"name": f"[H{hospital_id}] Sala de Analises 2", "wing": "specialized", "role": "room", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id},

        jid(f"{p}bloco_operatorio1"): {"name": f"[H{hospital_id}] Bloco Operatório A", "wing": "surgical",   "role": "room", "hospital": hospital_id},
        jid(f"{p}bloco_operatorio2"): {"name": f"[H{hospital_id}] Bloco Operatório B", "wing": "surgical",   "role": "room", "hospital": hospital_id},
        jid(f"{p}bloco_operatorio3"): {"name": f"[H{hospital_id}] Bloco Operatório C", "wing": "surgical",   "role": "room", "hospital": hospital_id},

        jid(f"{p}sala_triagem1"): {"name": f"[H{hospital_id}] Triagem 1", "wing": "triage",    "role": "room", "hospital": hospital_id},
        jid(f"{p}sala_triagem2"): {"name": f"[H{hospital_id}] Triagem 2", "wing": "triage",    "role": "room", "hospital": hospital_id},

        jid(f"{p}internamento1"): {"name": f"[H{hospital_id}] Internamento 1", "wing": "inpatient", "role": "room", "hospital": hospital_id},
        jid(f"{p}internamento2"): {"name": f"[H{hospital_id}] Internamento 2", "wing": "inpatient", "role": "room", "hospital": hospital_id},
        jid(f"{p}internamento3"): {"name": f"[H{hospital_id}] Internamento 3", "wing": "inpatient", "role": "room", "hospital": hospital_id},
        jid(f"{p}internamento4"): {"name": f"[H{hospital_id}] Internamento 4", "wing": "inpatient", "role": "room", "hospital": hospital_id},

        jid(f"{p}enfermeiro1"): {"name": f"[H{hospital_id}] Enfermeira Ana Costa",    "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "morning"},
        jid(f"{p}enfermeiro2"): {"name": f"[H{hospital_id}] Enfermeiro Rui Sousa",    "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "afternoon"},
        jid(f"{p}enfermeiro3"): {"name": f"[H{hospital_id}] Enfermeira Clara Neves",  "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "night"},

        jid(f"{p}coord_triagem"):     {"name": f"[H{hospital_id}] Coordenador de Triagem",     "role": "infra", "hospital": hospital_id},
        jid(f"{p}coord_internamento"):{"name": f"[H{hospital_id}] Coordenador de Internamento", "role": "infra", "hospital": hospital_id},
        jid(f"{p}supervisor"):        {"name": f"[H{hospital_id}] Supervisor de Ala",           "role": "infra", "hospital": hospital_id},
    }


AGENT_REGISTRY = {}
AGENT_REGISTRY.update(_build_registry_for_hospital("", 1, None, None))
AGENT_REGISTRY.update(_build_registry_for_hospital("h2_", 2, None, None))
AGENT_REGISTRY[jid(UNIFIED_TRIAGE)] = {"name": "Triagem Geral Central", "role": "infra"}

# Legacy list helpers (H1 only — kept for backward compat with dashboard if needed)
MEDICOS = [k for k, v in AGENT_REGISTRY.items()
           if v.get("role") == "medic" and v.get("hospital") == 1]
MEDICOS_TRIAGEM = [k for k, v in AGENT_REGISTRY.items()
                   if v.get("role") == "triage_medic" and v.get("hospital") == 1]
SALAS = [k for k, v in AGENT_REGISTRY.items()
         if v.get("role") == "room" and v.get("wing") == "primary" and v.get("hospital") == 1]
EQUIPAMENTOS = [k for k, v in AGENT_REGISTRY.items()
                if v.get("role") == "room" and v.get("wing") == "specialized" and v.get("hospital") == 1]
BLOCOS = [k for k, v in AGENT_REGISTRY.items()
          if v.get("role") == "room" and v.get("wing") == "surgical" and v.get("hospital") == 1]
SALAS_TRIAGEM = [k for k, v in AGENT_REGISTRY.items()
                 if v.get("role") == "room" and v.get("wing") == "triage" and v.get("hospital") == 1]
INTERNAMENTO = [k for k, v in AGENT_REGISTRY.items()
                if v.get("role") == "room" and v.get("wing") == "inpatient" and v.get("hospital") == 1]

# Configuração de Logging
COLORS = {
    "RESET": "\033[0m",
    "RED": "\033[91m",
    "GREEN": "\033[92m",
    "YELLOW": "\033[93m",
    "BLUE": "\033[94m",
    "MAGENTA": "\033[95m",
    "CYAN": "\033[96m",
    "WHITE": "\033[97m",
    "BOLD": "\033[1m",
}

def log(agent_name: str, message: str, color: str = "WHITE"):
    """Terminal standard logger."""
    c = COLORS.get(color, COLORS["WHITE"])
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{c}[{ts}] [{agent_name}] {message}{COLORS['RESET']}")
