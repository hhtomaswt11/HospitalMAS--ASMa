"""
Layer 3 — Supervision Motor
"""

import json
from datetime import datetime

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *

GLOBAL_DASHBOARD = {}
RECENT_LOGS = []

def dump_state():
    try:
        with open("data/dashboard.json", "w", encoding="utf-8") as f:
            json.dump({
                "resources": GLOBAL_DASHBOARD,
                "logs": RECENT_LOGS,
                "registry": AGENT_REGISTRY
            }, f, ensure_ascii=False)
    except Exception:
        pass

_original_log = log
def log(agent_name, message, color="WHITE"):
    _original_log(agent_name, message, color)
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    RECENT_LOGS.append({"time": timestamp, "agent": agent_name, "message": message, "color": color})
    if len(RECENT_LOGS) > 40:
        RECENT_LOGS.pop(0)
    
    # We dump state on every log so the dashboard is incredibly snappy and real-time
    dump_state()

    if agent_name == SUPERVISOR:
        full_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open("data/log_supervisor.txt", "a", encoding="utf-8") as f:
                f.write(f"[{full_timestamp}] {message}\n")
        except Exception:
            pass


class Supervisor(Agent):
    """
    Supervisor Agent — Monitors emergencies, orchestrates preemption, and tracks the global hospital dashboard.
    """
    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)

    class MonitorBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=5)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "inform" and msg_type == "resource_status":
                data = json.loads(msg.body)
                r_jid = data.get("recurso_jid")
                GLOBAL_DASHBOARD[r_jid] = data
                
                estado = "LIVRE" if data["disponivel"] else f"OCUPADO(A) com {data.get('paciente_atual')}"
                nome_r = data.get("nome", data.get("nome_sala", data.get("nome_medico", "Recurso Desconhecido")))
                log(SUPERVISOR, f"[DASHBOARD] {nome_r} -> {estado}", "BLUE")

            elif performative == "inform" and msg_type == "emergency_alert":
                data = json.loads(msg.body)
                log(SUPERVISOR, f"[ALERTA-EMERGÊNCIA] Recebido alerta prioritário! Doente: {data['nome']} | Prioridade: {data['prioridade']}", "RED")
                log(SUPERVISOR, "[PREEMPÇÃO] A despoletar protocolo dinâmico de preempção...", "RED")

                preempt = Message(to=jid(COORD_CONS))
                preempt.set_metadata("performative", "request")
                preempt.set_metadata("type", "preemption_order")
                preempt.body = json.dumps({
                    "urgente_jid": data["doente_jid"],
                    "urgente_nome": data["nome"],
                    "prioridade": data["prioridade"],
                })
                preempt.thread = data["doente_jid"]
                await self.send(preempt)
                log(SUPERVISOR, f"[PREEMPÇÃO] Diretiva de preempção enviada para {COORD_CONS}.", "YELLOW")

            elif performative == "inform" and msg_type == "preemption_done":
                data = json.loads(msg.body)

                if data.get("status") == "resources_freed":
                    log(SUPERVISOR, "[PREEMPÇÃO-SUCESSO] Recursos libertados com sucesso por preempção.", "GREEN")

                    freed = Message(to=jid(COORD_URG))
                    freed.set_metadata("performative", "inform")
                    freed.set_metadata("type", "resources_freed")
                    freed.body = json.dumps({
                        "status": "resources_available",
                        "medico_jid": data.get("medico_jid"),
                        "sala_jid": data.get("sala_jid"),
                    })
                    await self.send(freed)
                    log(SUPERVISOR, f"[PREEMPÇÃO-SUCESSO] Coordenador de urgências notificado da disponibilidade.", "GREEN")
                else:
                    log(SUPERVISOR, "[PREEMPÇÃO-AVISO] Sem alocações de rotina para cancelar. Fila de espera mandatória.", "YELLOW")

    async def setup(self):
        log(SUPERVISOR, "Supervisor initialized.", "BOLD")
        self.add_behaviour(self.MonitorBehaviour())
