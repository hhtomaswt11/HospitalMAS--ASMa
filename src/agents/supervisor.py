import json
import asyncio
from datetime import datetime

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *

GLOBAL_DASHBOARD = {}
GLOBAL_WAITLIST = {
    "routine": [],
    "routine_by_specialty": {},
    "emergency": [],
    "emergency_by_specialty": {},
    "triage": [],
    "internment": [],
}
RECENT_LOGS = []

def dump_state():
    try:
        with open("data/dashboard.json", "w", encoding="utf-8") as f:
            json.dump({
                "resources": GLOBAL_DASHBOARD,
                "waitlist": GLOBAL_WAITLIST,
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

    if agent_name == SUPERVISOR:
        full_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open("data/log_supervisor.txt", "a", encoding="utf-8") as f:
                f.write(f"[{full_timestamp}] {message}\n")
        except Exception:
            pass


class Supervisor(Agent):

    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)

    class PeriodicDumperBehaviour(CyclicBehaviour):
        async def run(self):
            dump_state()
            await asyncio.sleep(SUPERVISOR_DUMP_INTERVAL_SECONDS)

    class MonitorBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=SUPERVISOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "inform" and msg_type == "resource_status":
                data = json.loads(msg.body)
                r_jid = data.get("recurso_jid")
                GLOBAL_DASHBOARD[r_jid] = data
                
                # Dynamic registry update (for newly spawned agents)
                if r_jid not in AGENT_REGISTRY:
                    AGENT_REGISTRY[r_jid] = {
                        "name": data.get("nome", r_jid.split("@")[0]),
                        "role": "patient" if "doente" in r_jid.lower() else "infra",
                        "type": "Dinâmico"
                    }
                
                # Also register the patient being treated
                p_jid = data.get("paciente_atual")
                if p_jid:
                    room_info = AGENT_REGISTRY.get(r_jid, {})
                    room_wing = room_info.get("wing")
                    current_patient = AGENT_REGISTRY.get(p_jid, {})
                    current_type = str(current_patient.get("type", ""))

                    if room_wing == "triage" or "urg" in current_type.lower():
                        patient_type = "Urgência"
                    else:
                        patient_type = current_type or "Em Atendimento"

                    AGENT_REGISTRY[p_jid] = {
                        "name": current_patient.get("name", p_jid.split("@")[0].capitalize()),
                        "role": "patient",
                        "type": patient_type
                    }

                estado = "LIVRE" if data["disponivel"] else f"OCUPADO(A) com {data.get('paciente_atual')}"
                nome_r = data.get("nome", data.get("nome_sala", data.get("nome_medico", "Recurso Desconhecido")))
                log(SUPERVISOR, f"[DASHBOARD] {nome_r} -> {estado}", "BLUE")

            elif performative == "inform" and msg_type == "waitlist_update":
                data = json.loads(msg.body)
                queue_name = data.get("queue")
                patients = data.get("patients", [])
                by_specialty = data.get("by_specialty")
                if queue_name in GLOBAL_WAITLIST:
                    GLOBAL_WAITLIST[queue_name] = patients
                    grouped_key = f"{queue_name}_by_specialty"
                    if grouped_key in GLOBAL_WAITLIST and by_specialty is not None:
                        GLOBAL_WAITLIST[grouped_key] = by_specialty
                    log(SUPERVISOR,
                        f"[SALA-ESPERA] Fila '{queue_name}' atualizada ({len(patients)} doentes).",
                        "YELLOW")

            elif performative == "inform" and msg_type == "emergency_alert":
                data = json.loads(msg.body)
                p_jid = data.get("doente_jid")
                
                # Keep urgent patients marked as "Urgência" even after they are in treatment.
                if p_jid:
                    current = AGENT_REGISTRY.get(p_jid, {})
                    AGENT_REGISTRY[p_jid] = {
                        "name": data.get("nome", current.get("name", p_jid.split("@")[0])),
                        "role": "patient",
                        "type": "Urgência"
                    }

                log(SUPERVISOR, f"[ALERTA-EMERGÊNCIA] Recebido alerta prioritário! Doente: {data['nome']} | Prioridade: {data['prioridade']}", "RED")

            elif performative == "request" and msg_type == "preemption_request":
                data = json.loads(msg.body)
                urgente_jid = data.get("urgente_jid") or data.get("doente_jid")
                urgente_nome = data.get("urgente_nome") or data.get("nome", "?")
                prioridade = data.get("prioridade")

                if not urgente_jid:
                    log(
                        SUPERVISOR,
                        "[PREEMPÇÃO-ERRO] Pedido de preempção inválido: urgente_jid em falta.",
                        "RED",
                    )
                    return

                log(SUPERVISOR, f"[PREEMPÇÃO] Pedido recebido de urgências para {urgente_nome}.", "RED")
                log(SUPERVISOR, "[PREEMPÇÃO] A despoletar protocolo dinâmico de preempção...", "RED")

                preempt = Message(to=jid(COORD_CONS))
                preempt.set_metadata("performative", "request")
                preempt.set_metadata("type", "preemption_order")
                preempt.body = json.dumps({
                    "urgente_jid": urgente_jid,
                    "urgente_nome": urgente_nome,
                    "prioridade": prioridade,
                })
                preempt.thread = urgente_jid
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

                    # Mesmo sem preempção efetiva, os recursos já podem estar livres.
                    # Notificamos o coordenador de urgências para evitar deadlock.
                    freed = Message(to=jid(COORD_URG))
                    freed.set_metadata("performative", "inform")
                    freed.set_metadata("type", "resources_freed")
                    freed.body = json.dumps({
                        "status": "resources_available",
                    })
                    await self.send(freed)
                    log(SUPERVISOR, "[PREEMPÇÃO-AVISO] Coordenador de urgências notificado para avançar com a fila.", "YELLOW")

    async def setup(self):
        log(SUPERVISOR, "Supervisor initialized.", "BOLD")
        self.add_behaviour(self.MonitorBehaviour())
        self.add_behaviour(self.PeriodicDumperBehaviour())
