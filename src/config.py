import os
from datetime import datetime
#from dotenv import load_dotenv

# load_dotenv()

from src.patch import apply_xmpp_patch
apply_xmpp_patch()

# Configuração do Servidor XMPP
XMPP_SERVER = os.getenv("XMPP_SERVER", "127.0.0.1")
PASSWORD = os.getenv("XMPP_PASSWORD", "password")

def jid(name: str) -> str:
    return f"{name}@{XMPP_SERVER}"

# ────────────────────────────────────────────────────────────
#  Nomes base dos agentes
# ────────────────────────────────────────────────────────────
# Mantido como fallback histórico em alguns agentes/fluxos.
SUPERVISOR = "supervisor"


def numbered_names(prefix: str, base: str, start: int, end: int) -> list[str]:
    """Gera nomes de agentes no formato '<prefix><base><n>'."""
    return [f"{prefix}{base}{i}" for i in range(start, end + 1)]


def prefixed(prefix: str, name: str) -> str:
    """Aplica o prefixo do hospital a um nome lógico de agente/recurso."""
    return f"{prefix}{name}"


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
    "consultation": 15 / 60.0,
    "emergency":    15 / 60.0,
    "exam":         20 / 60.0,
    "surgery":      1.0,  # dynamic, will be overridden
    "triage":       0.1,
    "internment":   2.0,
}

# Valores da Simulação
SIMULATION_WEEKS = 1
# Duração real da demonstração. Por defeito fica em 3 minutos para a defesa;
# se for preciso correr uma semana simulada completa, definir SIMULATION_DURATION=1680 no ambiente.
SIMULATION_DURATION = int(os.getenv("SIMULATION_DURATION", "45"))
ARRIVAL_RATE_NORMAL_BASE = float(os.getenv("ARRIVAL_RATE_NORMAL", "1.5"))
ARRIVAL_RATE_URGENT_BASE = float(os.getenv("ARRIVAL_RATE_URGENT", "0.75"))
# Mantém nomes antigos para compatibilidade com o main_sim e documentação.
ARRIVAL_RATE_NORMAL = ARRIVAL_RATE_NORMAL_BASE
ARRIVAL_RATE_URGENT = ARRIVAL_RATE_URGENT_BASE

# Perfil simples de afluência ao longo do dia simulado.
# Cada tuplo é (hora_inicio, hora_fim, multiplicador_da_taxa_base).
# O gerador usa estes multiplicadores para variar o intervalo médio entre chegadas.
ARRIVAL_PROFILE_NORMAL = [
    (8, 10, 1.8),   # pico da manhã
    (10, 12, 1.1),
    (12, 14, 0.6),  # período mais calmo
    (14, 18, 1.25), # tarde normal/alta
    (18, 20, 0.75), # fim do dia mais calmo
]
ARRIVAL_PROFILE_URGENT = [
    (0, 8, 0.65),
    (8, 10, 1.25),
    (10, 14, 0.85),
    (14, 18, 1.10),
    (18, 24, 0.75),
]
ARRIVAL_CLOSED_RETRY_SECONDS = 5

def arrival_rate_for_hour(tipo_entrada: str, hour: float, base_rate=None) -> float:
    """Devolve a taxa de chegada para a hora simulada atual.

    A taxa final é: taxa_base * multiplicador_do_período. Para consultas
    de rotina, fora da janela administrativa 08h-20h a taxa é zero.
    """
    is_normal = tipo_entrada == "Normal"
    if is_normal and not (ROUTINE_START_H <= hour < ROUTINE_END_H):
        return 0.0

    base = base_rate if base_rate is not None else (
        ARRIVAL_RATE_NORMAL_BASE if is_normal else ARRIVAL_RATE_URGENT_BASE
    )
    profile = ARRIVAL_PROFILE_NORMAL if is_normal else ARRIVAL_PROFILE_URGENT
    hour = hour % 24
    for start, end, multiplier in profile:
        if start <= hour < end:
            return max(0.0, base * multiplier)
    return max(0.0, base)

# Probability that a newly spawned patient is redirected to the central triage agent
PROB_CENTRAL_TRIAGE = 0.3

# Temporização (segundos)
SUPERVISOR_DUMP_INTERVAL_SECONDS = 1
SUPERVISOR_RECEIVE_TIMEOUT_SECONDS = 5

COORDINATOR_RECEIVE_TIMEOUT_SECONDS = 1
COORDINATOR_PROPOSAL_TIMEOUT_SECONDS = 1.5
RESOURCE_RECEIVE_TIMEOUT_SECONDS = 10
DISPATCH_BATCH_LIMIT = 2
ROUTINE_DISPATCH_BATCH_LIMIT = 4

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
ROUTINE_RESERVATION_CONFIRM_TIMEOUT_SECONDS = 2


# Consulta de rotina com agenda por slots (tempo simulado)
# A consulta clínica dura 15 minutos, mas os slots são espaçados de 20 minutos
# para criar uma pequena folga operacional entre consultas consecutivas.
CONSULTATION_SLOT_MINUTES = 20
CONSULTATION_SLOT_SECONDS = SIM_HOUR_SECONDS * (CONSULTATION_SLOT_MINUTES / 60.0)

CONSULTATION_DURATION_NORMAL_SECONDS = SIM_HOUR_SECONDS * (15 / 60.0)
CONSULTATION_DURATION_URGENT_SECONDS = SIM_HOUR_SECONDS * (15 / 60.0)
EXAM_RESULTS_WAIT_SECONDS = 2  # mantido por compatibilidade; o fluxo agora espera por exam_result real
PROCEDURE_RESULT_TIMEOUT_SECONDS = 15  # mantido por compatibilidade
EXAM_RESULT_TIMEOUT_SECONDS = 60
SURGERY_RESULT_TIMEOUT_SECONDS = 90
SURGERY_DURATION_SECONDS = 10  # Fallback
EXAM_DURATION_SECONDS = SIM_HOUR_SECONDS * (20 / 60.0)
TRIAGE_CLASSIFICATION_SECONDS = 1

CENTRAL_TRIAGE_DIAGNOSIS_SECONDS = 2  # time for central triage agent to diagnose
LOAD_QUERY_RESPONSE_WAIT_SECONDS = 3  # timeout to collect load_query responses

SIM_INFRA_READY_WAIT_SECONDS = 2
SIM_PROGRESS_TICK_SECONDS = 5

# Por defeito o dashboard é lançado manualmente, como descrito no README.
# Definir AUTO_START_DASHBOARD=1 permite voltar ao comportamento antigo.
AUTO_START_DASHBOARD = os.getenv("AUTO_START_DASHBOARD", "0").lower() in {"1", "true", "yes", "sim"}

# Probabilidades de Fluxo Clínico
PROB_EXAM_URGENT = 0.8  # 80% dos urgentes vão a exame
PROB_EXAM_NORMAL = 0.2  # 20% dos de rotina vão a exame
PROB_SURGERY_AFTER_EXAM = 0.5  # 50% dos que fazem exame vão para cirurgia
PROB_INTERNAMENTO_URGENT = 0.4

INTERNAMENTO_MIN_SECONDS = 15
INTERNAMENTO_MAX_SECONDS = 30

URGENT_PRIORITY_MIN = 0
URGENT_PRIORITY_MAX = 3
ROUTINE_SURGERY_PRIORITY = 5

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
    medicos_consultas_routine_names, medicos_consultas_emergency_names,
    salas_consultas_routine_names, salas_consultas_emergency_names,
    equipamentos_map, blocos_names,
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
        "medicos_consultas_routine": [jid(m) for m in medicos_consultas_routine_names],
        "medicos_consultas_emergency": [jid(m) for m in medicos_consultas_emergency_names],
        "salas_consultas_routine": [jid(s) for s in salas_consultas_routine_names],
        "salas_consultas_emergency": [jid(s) for s in salas_consultas_emergency_names],
        # Compat: mantém a chave histórica usada no bootstrap de recursos.
        "salas": [jid(s) for s in (salas_consultas_routine_names + salas_consultas_emergency_names)],
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
    coord_cons_name="coord_consultas", coord_urg_name="coord_urgencias",
    coord_exam_name="coord_exames", coord_cir_name="coord_cirurgias",
    coord_tri_name="coord_triagem", coord_int_name="coord_internamento",
    medicos_names=numbered_names("", "medico", 1, 30),
    medicos_triagem_names=numbered_names("", "medico_triagem", 1, 3),
    medicos_consultas_routine_names=[f"medico{i}" for i in [1, 2, 3, 12, 13, 14]],
    medicos_consultas_emergency_names=[f"medico{i}" for i in [4, 5, 6, 15, 16, 17, 23, 24, 25]],
    salas_consultas_routine_names=numbered_names("", "sala", 1, 7),
    salas_consultas_emergency_names=numbered_names("", "sala", 8, 10),
    equipamentos_map=[
        ("sala_raiox1", SPECIALTY_RX), ("sala_raiox2", SPECIALTY_RX),
        ("sala_tac1", SPECIALTY_TAC), ("sala_tac2", SPECIALTY_TAC),
        ("sala_analises1", SPECIALTY_ANALISES), ("sala_analises2", SPECIALTY_ANALISES),
    ],
    blocos_names=numbered_names("", "bloco_operatorio", 1, 3),
    salas_triagem_names=numbered_names("", "sala_triagem", 1, 2),
    internamento_names=numbered_names("", "internamento", 1, 4),
    enfermeiros_names=numbered_names("", "enfermeiro", 1, 6),
)

# ── Hospital 2 config ──
H2_PREFIX = "h2_"
H2_CONFIG = build_hospital_config(
    supervisor_name=prefixed(H2_PREFIX, "supervisor"),
    coord_cons_name=prefixed(H2_PREFIX, "coord_consultas"),
    coord_urg_name=prefixed(H2_PREFIX, "coord_urgencias"),
    coord_exam_name=prefixed(H2_PREFIX, "coord_exames"),
    coord_cir_name=prefixed(H2_PREFIX, "coord_cirurgias"),
    coord_tri_name=prefixed(H2_PREFIX, "coord_triagem"),
    coord_int_name=prefixed(H2_PREFIX, "coord_internamento"),
    medicos_names=numbered_names(H2_PREFIX, "medico", 1, 30),
    medicos_triagem_names=numbered_names(H2_PREFIX, "medico_triagem", 1, 3),
    medicos_consultas_routine_names=[prefixed(H2_PREFIX, f"medico{i}") for i in [1, 2, 3, 12, 13, 14]],
    medicos_consultas_emergency_names=[prefixed(H2_PREFIX, f"medico{i}") for i in [4, 5, 6, 15, 16, 17, 23, 24, 25]],
    salas_consultas_routine_names=numbered_names(H2_PREFIX, "sala", 1, 7),
    salas_consultas_emergency_names=numbered_names(H2_PREFIX, "sala", 8, 10),
    equipamentos_map=[
        (prefixed(H2_PREFIX, "sala_raiox1"), SPECIALTY_RX),
        (prefixed(H2_PREFIX, "sala_raiox2"), SPECIALTY_RX),
        (prefixed(H2_PREFIX, "sala_tac1"), SPECIALTY_TAC),
        (prefixed(H2_PREFIX, "sala_tac2"), SPECIALTY_TAC),
        (prefixed(H2_PREFIX, "sala_analises1"), SPECIALTY_ANALISES),
        (prefixed(H2_PREFIX, "sala_analises2"), SPECIALTY_ANALISES),
    ],
    blocos_names=numbered_names(H2_PREFIX, "bloco_operatorio", 1, 3),
    salas_triagem_names=numbered_names(H2_PREFIX, "sala_triagem", 1, 2),
    internamento_names=numbered_names(H2_PREFIX, "internamento", 1, 4),
    enfermeiros_names=numbered_names(H2_PREFIX, "enfermeiro", 1, 6),
)

# ────────────────────────────────────────────────────────────
#  Agent Registry (used by Dashboard / Supervisor)
# ────────────────────────────────────────────────────────────
def _build_registry_for_hospital(prefix, hospital_id, doctor_names=None, names=None):
    """Build registry entries for one hospital. prefix='' for H1, 'h2_' for H2."""
    p = prefix
    reg = {}
    
    # Morning shift
    reg[jid(f"{p}medico1")] = {"name": f"[H{hospital_id}] Dr(a). Routine Pediatria", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_PEDIATRIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico2")] = {"name": f"[H{hospital_id}] Dr(a). Routine Ortopedia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_ORTOPEDIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico3")] = {"name": f"[H{hospital_id}] Dr(a). Routine Cardiologia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_CARDIOLOGIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "morning"}
    
    reg[jid(f"{p}medico4")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Pediatria", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_PEDIATRIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico5")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Ortopedia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_ORTOPEDIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico6")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Cardiologia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_CARDIOLOGIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "morning"}
    
    reg[jid(f"{p}medico7")] = {"name": f"[H{hospital_id}] Dr(a). RX", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_RX, "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico8")] = {"name": f"[H{hospital_id}] Dr(a). TAC", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_TAC, "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico9")] = {"name": f"[H{hospital_id}] Dr(a). Analises", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id, "shift": "morning"}
    
    reg[jid(f"{p}medico10")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 1", "type": "Especialista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico11")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 2", "type": "Especialista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "morning"}

    # Afternoon shift
    reg[jid(f"{p}medico12")] = {"name": f"[H{hospital_id}] Dr(a). Routine Pediatria", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_PEDIATRIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico13")] = {"name": f"[H{hospital_id}] Dr(a). Routine Ortopedia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_ORTOPEDIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico14")] = {"name": f"[H{hospital_id}] Dr(a). Routine Cardiologia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_CARDIOLOGIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "afternoon"}
    
    reg[jid(f"{p}medico15")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Pediatria", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_PEDIATRIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico16")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Ortopedia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_ORTOPEDIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico17")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Cardiologia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_CARDIOLOGIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "afternoon"}
    
    reg[jid(f"{p}medico18")] = {"name": f"[H{hospital_id}] Dr(a). RX", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_RX, "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico19")] = {"name": f"[H{hospital_id}] Dr(a). TAC", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_TAC, "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico20")] = {"name": f"[H{hospital_id}] Dr(a). Analises", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id, "shift": "afternoon"}
    
    reg[jid(f"{p}medico21")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 1", "type": "Especialista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico22")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 2", "type": "Especialista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "afternoon"}

    # Night shift
    reg[jid(f"{p}medico23")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Pediatria", "type": "Urgencista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_PEDIATRIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "night"}
    reg[jid(f"{p}medico24")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Ortopedia", "type": "Urgencista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_ORTOPEDIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "night"}
    reg[jid(f"{p}medico25")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Cardiologia", "type": "Urgencista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_CARDIOLOGIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "night"}
    
    reg[jid(f"{p}medico26")] = {"name": f"[H{hospital_id}] Dr(a). RX", "type": "Urgencista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_RX, "hospital": hospital_id, "shift": "night"}
    reg[jid(f"{p}medico27")] = {"name": f"[H{hospital_id}] Dr(a). TAC", "type": "Urgencista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_TAC, "hospital": hospital_id, "shift": "night"}
    reg[jid(f"{p}medico28")] = {"name": f"[H{hospital_id}] Dr(a). Analises", "type": "Urgencista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id, "shift": "night"}
    
    reg[jid(f"{p}medico29")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 1", "type": "Urgencista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "night"}
    reg[jid(f"{p}medico30")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 2", "type": "Urgencista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "night"}

    reg[jid(f"{p}medico_triagem1")] = {"name": f"[H{hospital_id}] Dr. Tiago Pinto",   "type": "Triagem", "role": "triage_medic", "zone": "triage", "specialty": SPECIALTY_TRIAGEM, "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico_triagem2")] = {"name": f"[H{hospital_id}] Dra. Leonor Viana", "type": "Triagem", "role": "triage_medic", "zone": "triage", "specialty": SPECIALTY_TRIAGEM, "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico_triagem3")] = {"name": f"[H{hospital_id}] Dr(a). Triagem 3", "type": "Triagem", "role": "triage_medic", "zone": "triage", "specialty": SPECIALTY_TRIAGEM, "hospital": hospital_id, "shift": "night"}

    reg[jid(f"{p}sala1")] =  {"name": f"[H{hospital_id}] Consultorio 1",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala2")] =  {"name": f"[H{hospital_id}] Consultorio 2",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala3")] =  {"name": f"[H{hospital_id}] Consultorio 3",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala4")] =  {"name": f"[H{hospital_id}] Consultorio 4",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala5")] =  {"name": f"[H{hospital_id}] Consultorio 5",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala6")] =  {"name": f"[H{hospital_id}] Consultorio 6",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala7")] =  {"name": f"[H{hospital_id}] Consultorio 7",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala8")] =  {"name": f"[H{hospital_id}] Consultorio 8",  "wing": "primary",    "role": "room", "category": "emergency", "hospital": hospital_id}
    reg[jid(f"{p}sala9")] =  {"name": f"[H{hospital_id}] Consultorio 9",  "wing": "primary",    "role": "room", "category": "emergency", "hospital": hospital_id}
    reg[jid(f"{p}sala10")] = {"name": f"[H{hospital_id}] Consultorio 10", "wing": "primary",    "role": "room", "category": "emergency", "hospital": hospital_id}

    reg[jid(f"{p}sala_raiox1")] =   {"name": f"[H{hospital_id}] Sala de Raio-X 1",  "wing": "specialized", "role": "room", "specialty": SPECIALTY_RX,       "hospital": hospital_id}
    reg[jid(f"{p}sala_raiox2")] =   {"name": f"[H{hospital_id}] Sala de Raio-X 2",  "wing": "specialized", "role": "room", "specialty": SPECIALTY_RX,       "hospital": hospital_id}
    reg[jid(f"{p}sala_tac1")] =     {"name": f"[H{hospital_id}] Sala de TAC 1",      "wing": "specialized", "role": "room", "specialty": SPECIALTY_TAC,      "hospital": hospital_id}
    reg[jid(f"{p}sala_tac2")] =     {"name": f"[H{hospital_id}] Sala de TAC 2",      "wing": "specialized", "role": "room", "specialty": SPECIALTY_TAC,      "hospital": hospital_id}
    reg[jid(f"{p}sala_analises1")] ={"name": f"[H{hospital_id}] Sala de Analises 1", "wing": "specialized", "role": "room", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id}
    reg[jid(f"{p}sala_analises2")] ={"name": f"[H{hospital_id}] Sala de Analises 2", "wing": "specialized", "role": "room", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id}

    reg[jid(f"{p}bloco_operatorio1")] = {"name": f"[H{hospital_id}] Bloco Operatório A", "wing": "surgical",   "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}bloco_operatorio2")] = {"name": f"[H{hospital_id}] Bloco Operatório B", "wing": "surgical",   "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}bloco_operatorio3")] = {"name": f"[H{hospital_id}] Bloco Operatório C", "wing": "surgical",   "role": "room", "hospital": hospital_id}

    reg[jid(f"{p}sala_triagem1")] = {"name": f"[H{hospital_id}] Triagem 1", "wing": "triage",    "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}sala_triagem2")] = {"name": f"[H{hospital_id}] Triagem 2", "wing": "triage",    "role": "room", "hospital": hospital_id}

    reg[jid(f"{p}internamento1")] = {"name": f"[H{hospital_id}] Internamento 1", "wing": "inpatient", "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}internamento2")] = {"name": f"[H{hospital_id}] Internamento 2", "wing": "inpatient", "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}internamento3")] = {"name": f"[H{hospital_id}] Internamento 3", "wing": "inpatient", "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}internamento4")] = {"name": f"[H{hospital_id}] Internamento 4", "wing": "inpatient", "role": "room", "hospital": hospital_id}

    reg[jid(f"{p}enfermeiro1")] = {"name": f"[H{hospital_id}] Enf. Internamento 1", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "morning"}
    reg[jid(f"{p}enfermeiro2")] = {"name": f"[H{hospital_id}] Enf. Internamento 2", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "morning"}
    reg[jid(f"{p}enfermeiro3")] = {"name": f"[H{hospital_id}] Enf. Internamento 3", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "afternoon"}
    reg[jid(f"{p}enfermeiro4")] = {"name": f"[H{hospital_id}] Enf. Internamento 4", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "afternoon"}
    reg[jid(f"{p}enfermeiro5")] = {"name": f"[H{hospital_id}] Enf. Internamento 5", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "night"}
    reg[jid(f"{p}enfermeiro6")] = {"name": f"[H{hospital_id}] Enf. Internamento 6", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "night"}

    reg[jid(f"{p}coord_triagem")] =     {"name": f"[H{hospital_id}] Coordenador de Triagem",     "role": "infra", "hospital": hospital_id}
    reg[jid(f"{p}coord_internamento")] ={"name": f"[H{hospital_id}] Coordenador de Internamento", "role": "infra", "hospital": hospital_id}
    reg[jid(f"{p}supervisor")] =        {"name": f"[H{hospital_id}] Supervisor de Ala",           "role": "infra", "hospital": hospital_id}
    
    return reg


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
