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

SALA1 = "sala1"
SALA2 = "sala2"
SALA3 = "sala3"

COORD_CONS = "coord_consultas"
COORD_URG = "coord_urgencias"
COORD_EXAM = "coord_exames"
COORD_CIR = "coord_cirurgias"
TRIAGEM = "triagem"
SUPERVISOR = "supervisor"

SALA_RAIOX = "sala_raiox"
SALA_TAC = "sala_tac"
BLOCO_OPERATORIO1 = "bloco_operatorio1"
BLOCO_OPERATORIO2 = "bloco_operatorio2"

# Valores da Simulação
SIMULATION_DURATION = 300  # segundos
ARRIVAL_RATE_NORMAL = 0.5  # pacientes por segundo (média de 1 a cada 2s)
ARRIVAL_RATE_URGENT = 0.05 # pacientes por segundo (média de 1 a cada 20s)

# Probabilidades de Fluxo Clínico
PROB_EXAM_URGENT = 0.8  # 80% dos urgentes vão a exame
PROB_EXAM_NORMAL = 0.2  # 20% dos de rotina vão a exame
PROB_SURGERY_AFTER_EXAM = 0.5  # 50% dos que fazem exame vão para cirurgia

# Agentes
AGENT_REGISTRY = {
    jid(MEDICO1): {"name": "Dr. José Silva", "type": "Pediatra", "role": "medic"},
    jid(MEDICO2): {"name": "Dra. Beatriz Santos", "type": "Pediatra", "role": "medic"},
    jid(MEDICO3): {"name": "Dr. Ricardo Lima", "type": "Cirurgião", "role": "medic"},

    jid(SALA1): {"name": "Consultório 1", "wing": "primary", "role": "room"},
    jid(SALA2): {"name": "Consultório 2", "wing": "primary", "role": "room"},
    jid(SALA3): {"name": "Consultório 3", "wing": "primary", "role": "room"},

    jid(SALA_RAIOX): {"name": "Sala de Raio-X", "wing": "specialized", "role": "room"},
    jid(SALA_TAC): {"name": "Sala de TAC", "wing": "specialized", "role": "room"},

    jid(BLOCO_OPERATORIO1): {"name": "Bloco Operatório A", "wing": "surgical", "role": "room"},
    jid(BLOCO_OPERATORIO2): {"name": "Bloco Operatório B", "wing": "surgical", "role": "room"},

    jid(TRIAGEM): {"name": "Triagem Principal", "role": "infra"},
    jid(SUPERVISOR): {"name": "Supervisor de Ala", "role": "infra"},
}

MEDICOS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "medic"]
SALAS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "room" and v.get("wing") == "primary"]
EQUIPAMENTOS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "room" and v.get("wing") == "specialized"]
BLOCOS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "room" and v.get("wing") == "surgical"]

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
