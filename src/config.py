import os
from datetime import datetime
from dotenv import load_dotenv

#load_dotenv()

from src.patch import apply_xmpp_patch
apply_xmpp_patch()

# Configuração do Servidor XMPP
XMPP_SERVER = os.getenv("XMPP_SERVER", "127.0.0.1")
PASSWORD = os.getenv("XMPP_PASSWORD", "password")

def jid(name: str) -> str:
    return f"{name}@{XMPP_SERVER}"

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

COORD_CONS = "coord_consultas"
COORD_URG = "coord_urgencias"
COORD_EXAM = "coord_exames"
COORD_CIR = "coord_cirurgias"
COORD_TRI = "coord_triagem"
COORD_INT = "coord_internamento"
TRIAGEM = COORD_TRI
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

# Compatibilidade com nomes antigos
SALA_RAIOX = SALA_RAIOX1
SALA_TAC = SALA_TAC1

BLOCO_OPERATORIO1 = "bloco_operatorio1"
BLOCO_OPERATORIO2 = "bloco_operatorio2"
BLOCO_OPERATORIO3 = "bloco_operatorio3"

# Valores da Simulação
SIMULATION_DURATION = 300  # segundos
ARRIVAL_RATE_NORMAL = 0.2  # pacientes por segundo (média de 1 a cada 2s)
ARRIVAL_RATE_URGENT = 0.05 # pacientes por segundo (média de 1 a cada 20s)

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
SPECIALTY_CIRURGIA = "cirurgiao"
SPECIALTY_PEDIATRIA = "pediatra"
SPECIALTY_ORTOPEDIA = "ortopedia"
SPECIALTY_CARDIOLOGIA = "cardiologia"

ROUTINE_SPECIALTIES = [
    SPECIALTY_PEDIATRIA,
    SPECIALTY_ORTOPEDIA,
    SPECIALTY_CARDIOLOGIA,
]

URGENT_TRIAGE_SPECIALTIES = list(ROUTINE_SPECIALTIES)

# Agentes
AGENT_REGISTRY = {
    jid(MEDICO1): {
        "name": "Dr. Jose Silva",
        "type": "Especialista",
        "role": "medic",
        "zone": "normal",
        "specialty": SPECIALTY_PEDIATRIA,
    },
    jid(MEDICO2): {
        "name": "Dra. Beatriz Santos",
        "type": "Especialista",
        "role": "medic",
        "zone": "normal",
        "specialty": SPECIALTY_ORTOPEDIA,
    },
    jid(MEDICO3): {
        "name": "Dr. Henrique Costa",
        "type": "Especialista",
        "role": "medic",
        "zone": "normal",
        "specialty": SPECIALTY_CARDIOLOGIA,
    },
    jid(MEDICO4): {
        "name": "Dr. Ricardo Lima",
        "type": "Especialista",
        "role": "medic",
        "zone": "surgical",
        "specialty": SPECIALTY_CIRURGIA,
    },
    jid(MEDICO5): {
        "name": "Dra. Ana Leal",
        "type": "Especialista",
        "role": "medic",
        "zone": "exam",
        "specialty": SPECIALTY_RX,
    },
    jid(MEDICO6): {
        "name": "Dr. Hugo Ribeiro",
        "type": "Especialista",
        "role": "medic",
        "zone": "exam",
        "specialty": SPECIALTY_TAC,
    },
    jid(MEDICO7): {
        "name": "Dra. Marta Faria",
        "type": "Especialista",
        "role": "medic",
        "zone": "exam",
        "specialty": SPECIALTY_ANALISES,
    },
    jid(MEDICO8): {
        "name": "Dr. Paulo Rocha",
        "type": "Especialista",
        "role": "medic",
        "zone": "normal",
        "specialty": SPECIALTY_PEDIATRIA,
    },
    jid(MEDICO9): {
        "name": "Dra. Rita Goncalves",
        "type": "Especialista",
        "role": "medic",
        "zone": "normal",
        "specialty": SPECIALTY_ORTOPEDIA,
    },
    jid(MEDICO10): {
        "name": "Dr. Bruno Martins",
        "type": "Especialista",
        "role": "medic",
        "zone": "normal",
        "specialty": SPECIALTY_CARDIOLOGIA,
    },
    jid(MEDICO11): {
        "name": "Dra. Sara Pires",
        "type": "Especialista",
        "role": "medic",
        "zone": "exam",
        "specialty": SPECIALTY_RX,
    },
    jid(MEDICO12): {
        "name": "Dr. Andre Lopes",
        "type": "Especialista",
        "role": "medic",
        "zone": "exam",
        "specialty": SPECIALTY_TAC,
    },
    jid(MEDICO13): {
        "name": "Dra. Mariana Teixeira",
        "type": "Especialista",
        "role": "medic",
        "zone": "exam",
        "specialty": SPECIALTY_ANALISES,
    },
    jid(MEDICO_TRIAGEM1): {
        "name": "Dr. Tiago Pinto",
        "type": "Triagem",
        "role": "triage_medic",
        "zone": "triage",
    },
    jid(MEDICO_TRIAGEM2): {
        "name": "Dra. Leonor Viana",
        "type": "Triagem",
        "role": "triage_medic",
        "zone": "triage",
    },

    jid(SALA1): {"name": "Consultorio 1", "wing": "primary", "role": "room"},
    jid(SALA2): {"name": "Consultorio 2", "wing": "primary", "role": "room"},
    jid(SALA3): {"name": "Consultorio 3", "wing": "primary", "role": "room"},
    jid(SALA4): {"name": "Consultorio 4", "wing": "primary", "role": "room"},
    jid(SALA5): {"name": "Consultorio 5", "wing": "primary", "role": "room"},
    jid(SALA6): {"name": "Consultorio 6", "wing": "primary", "role": "room"},
    jid(SALA7): {"name": "Consultorio 7", "wing": "primary", "role": "room"},
    jid(SALA8): {"name": "Consultorio 8", "wing": "primary", "role": "room"},
    jid(SALA9): {"name": "Consultorio 9", "wing": "primary", "role": "room"},
    jid(SALA10): {"name": "Consultorio 10", "wing": "primary", "role": "room"},

    jid(SALA_RAIOX1): {"name": "Sala de Raio-X 1","wing": "specialized","role": "room","specialty": SPECIALTY_RX},
    jid(SALA_RAIOX2): {"name": "Sala de Raio-X 2","wing": "specialized","role": "room","specialty": SPECIALTY_RX},
    jid(SALA_TAC1): {"name": "Sala de TAC 1", "wing": "specialized", "role": "room","specialty": SPECIALTY_TAC},
    jid(SALA_TAC2): {"name": "Sala de TAC 2", "wing": "specialized", "role": "room","specialty": SPECIALTY_TAC},
    jid(SALA_ANALISES1): {"name": "Sala de Analises 1", "wing": "specialized", "role": "room","specialty": SPECIALTY_ANALISES},
    jid(SALA_ANALISES2): {"name": "Sala de Analises 2", "wing": "specialized", "role": "room","specialty": SPECIALTY_ANALISES},

    jid(BLOCO_OPERATORIO1): {"name": "Bloco Operatório A", "wing": "surgical", "role": "room"},
    jid(BLOCO_OPERATORIO2): {"name": "Bloco Operatório B", "wing": "surgical", "role": "room"},
    jid(BLOCO_OPERATORIO3): {"name": "Bloco Operatório C", "wing": "surgical", "role": "room"},

    jid(SALA_TRIAGEM1): {"name": "Triagem 1", "wing": "triage", "role": "room"},
    jid(SALA_TRIAGEM2): {"name": "Triagem 2", "wing": "triage", "role": "room"},

    jid(INTERNAMENTO1): {"name": "Internamento 1", "wing": "inpatient", "role": "room"},
    jid(INTERNAMENTO2): {"name": "Internamento 2", "wing": "inpatient", "role": "room"},
    jid(INTERNAMENTO3): {"name": "Internamento 3", "wing": "inpatient", "role": "room"},
    jid(INTERNAMENTO4): {"name": "Internamento 4", "wing": "inpatient", "role": "room"},

    jid(COORD_TRI): {"name": "Coordenador de Triagem", "role": "infra"},
    jid(COORD_INT): {"name": "Coordenador de Internamento", "role": "infra"},
    jid(SUPERVISOR): {"name": "Supervisor de Ala", "role": "infra"},
}

MEDICOS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "medic"]
MEDICOS_TRIAGEM = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "triage_medic"]
SALAS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "room" and v.get("wing") == "primary"]
EQUIPAMENTOS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "room" and v.get("wing") == "specialized"]
BLOCOS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "room" and v.get("wing") == "surgical"]
SALAS_TRIAGEM = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "room" and v.get("wing") == "triage"]
INTERNAMENTO = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "room" and v.get("wing") == "inpatient"]

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
