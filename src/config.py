"""
Global configurations for the Multi-Agent Hospital System.
"""
import os
from datetime import datetime
from dotenv import load_dotenv

#load_dotenv()

from src.patch import apply_xmpp_patch
apply_xmpp_patch()

# XMPP Server Configuration
XMPP_SERVER = os.getenv("XMPP_SERVER", "127.0.0.1")
PASSWORD = os.getenv("XMPP_PASSWORD", "password")

def jid(name: str) -> str:
    return f"{name}@{XMPP_SERVER}"

# Agent Names
MEDICO1 = "medico1"
SALA1 = "sala1"
COORD_CONS = "coord_consultas"
COORD_URG = "coord_urgencias"
COORD_EXAM = "coord_exames"
COORD_CIR = "coord_cirurgias"
TRIAGEM = "triagem"
SUPERVISOR = "supervisor"
DOENTE_N1 = "doente_normal1"
DOENTE_N2 = "doente_normal2"
DOENTE_U1 = "doente_urgente1"
SALA_RAIOX = "sala_raiox"
BLOCO_OPERATORIO = "bloco_operatorio"

# Agent Resource Mapping (Registry)
# This serves as the source of truth for names and visual roles in the dashboard.
AGENT_REGISTRY = {
    jid(MEDICO1): {"name": "Dr. José", "type": "Pediatra", "role": "medic"},
    jid(SALA1): {"name": "Consultório 1", "wing": "primary", "role": "room"},
    jid(SALA_RAIOX): {"name": "Sala de Raio-X", "wing": "specialized", "role": "room"},
    jid(BLOCO_OPERATORIO): {"name": "Bloco Operatório", "wing": "surgical", "role": "room"},
    
    # Patients (Dynamic names mapped by JID)
    jid(DOENTE_N1): {"name": "João", "type": "Rotina", "role": "patient"},
    jid(DOENTE_N2): {"name": "Maria", "type": "Rotina", "role": "patient"},
    jid(DOENTE_U1): {"name": "Pedro", "type": "Urgência", "role": "patient"},

    # Infrastructure / Coordinators (Optional for visual registry)
    jid(TRIAGEM): {"name": "Triagem Principal", "role": "infra"},
    jid(SUPERVISOR): {"name": "Supervisor de Ala", "role": "infra"},
}

# Global Resource Lists (Derived from Registry for consistency)
MEDICOS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "medic"]
SALAS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "room" and v.get("wing") == "primary"]
EQUIPAMENTOS = [k for k, v in AGENT_REGISTRY.items() if v.get("role") == "room" and v.get("wing") == "specialized"]
# For backward compatibility with existing hardcoded lists
BLOCOS = [jid(BLOCO_OPERATORIO)]

# Logging Configuration
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
