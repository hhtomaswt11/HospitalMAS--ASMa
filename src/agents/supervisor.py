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
GLOBAL_ROUTING_HISTORY = []
RECENT_LOGS = []

def dump_state(sim_time=None):
    try:
        with open("data/dashboard.json", "w", encoding="utf-8") as f:
            json.dump({
                "resources": GLOBAL_DASHBOARD,
                "waitlist": GLOBAL_WAITLIST,
                "routing": GLOBAL_ROUTING_HISTORY,
                "logs": RECENT_LOGS,
                "registry": AGENT_REGISTRY,
                "sim_time": sim_time or {"day": 1, "hour": 0, "minute": 0}
            }, f, ensure_ascii=False)
    except Exception as exc:
        print(f"[SUPERVISOR] dump_state failed: {exc}")

_original_log = log
def log(agent_name, message, color="WHITE"):
    _original_log(agent_name, message, color)

    timestamp = datetime.now().strftime("%H:%M:%S")
    RECENT_LOGS.append({"time": timestamp, "agent": agent_name, "message": message, "color": color})
    if len(RECENT_LOGS) > 40:
        RECENT_LOGS.pop(0)

    if "supervisor" in str(agent_name).lower():
        full_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open("data/log_supervisor.txt", "a", encoding="utf-8") as f:
                f.write(f"[{full_timestamp}] [{agent_name}] {message}\n")
        except Exception:
            pass


class Supervisor(Agent):

    def __init__(self, agent_jid, password, hospital_config=None, hospital_id=1, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        cfg = hospital_config or H1_CONFIG
        self._hospital_id = hospital_id
        self._coord_cons = cfg["coord_cons"]
        self._coord_urg = cfg["coord_urg"]
        self._supervisor_name = str(agent_jid).split("@")[0]
        import time
        self._sim_start_time = time.time()

    class PeriodicDumperBehaviour(CyclicBehaviour):
        async def run(self):
            if self.agent._hospital_id == 1:
                import time
                elapsed = time.time() - self.agent._sim_start_time
                total_hours = elapsed / SIM_HOUR_SECONDS
                absolute_hours = total_hours
                
                day = int(absolute_hours // 24) + 1
                hour = int(absolute_hours % 24)
                minute = int((absolute_hours - int(absolute_hours)) * 60)
                sim_time = {"day": day, "hour": hour, "minute": minute}
                
                dump_state(sim_time)
            await asyncio.sleep(SUPERVISOR_DUMP_INTERVAL_SECONDS)

    class MonitorBehaviour(CyclicBehaviour):
        async def run(self):
            try:
                msg = await self.receive(timeout=SUPERVISOR_RECEIVE_TIMEOUT_SECONDS)
                if msg is None:
                    return

                performative = msg.get_metadata("performative")
                msg_type = msg.get_metadata("type")
                
                # Debug output to stdout to see every message hitting the supervisor
                # print(f"[{self.agent._supervisor_name}] RX: {msg_type} ({performative}) from {msg.sender}")

                if performative == "inform" and msg_type == "resource_status":
                    data = json.loads(msg.body)
                    r_jid = data.get("recurso_jid")
                    GLOBAL_DASHBOARD[r_jid] = data

                    if r_jid not in AGENT_REGISTRY:
                        AGENT_REGISTRY[r_jid] = {
                            "name": data.get("nome", r_jid.split("@")[0]),
                            "role": "patient" if "doente" in r_jid.lower() else "infra",
                            "type": "Dinâmico"
                        }

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
                    log(self.agent._supervisor_name, f"[DASHBOARD] {nome_r} -> {estado}", "BLUE")

                elif performative == "inform" and msg_type == "waitlist_update":
                    data = json.loads(msg.body)
                    queue_name = data.get("queue")
                    patients = data.get("patients", [])
                    by_specialty = data.get("by_specialty")
                    # 1. Update hospital-namespaced key
                    h_key = f"h{self.agent._hospital_id}_{queue_name}"
                    GLOBAL_WAITLIST[h_key] = patients
                    
                    # 2. Update specialty grouping for this hospital
                    grouped_key = f"{h_key}_by_specialty"
                    if by_specialty is not None:
                        GLOBAL_WAITLIST[grouped_key] = by_specialty
                    
                    # 3. Aggregated key (for backward compatibility or global views)
                    # We overwrite with latest or we could merge, but for now we just 
                    # ensure the key exists so old dashboard code doesn't crash.
                    GLOBAL_WAITLIST[queue_name] = patients
                    if by_specialty is not None:
                        GLOBAL_WAITLIST[f"{queue_name}_by_specialty"] = by_specialty
                    
                    log(self.agent._supervisor_name,
                        f"[SALA-ESPERA] Fila '{h_key}' atualizada ({len(patients)} doentes).",
                        "YELLOW")

                elif performative == "inform" and msg_type == "emergency_alert":
                    data = json.loads(msg.body)
                    p_jid = data.get("doente_jid")
                    if p_jid:
                        current = AGENT_REGISTRY.get(p_jid, {})
                        AGENT_REGISTRY[p_jid] = {
                            "name": data.get("nome", current.get("name", p_jid.split("@")[0])),
                            "role": "patient",
                            "type": "Urgência"
                        }
                    log(self.agent._supervisor_name,
                        f"[ALERTA-EMERGÊNCIA] Recebido alerta prioritário! "
                        f"Doente: {data['nome']} | Prioridade: {data['prioridade']}", "RED")

                elif performative == "inform" and msg_type == "routing_update":
                    data = json.loads(msg.body)
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    data["time"] = timestamp
                    GLOBAL_ROUTING_HISTORY.append(data)
                    if len(GLOBAL_ROUTING_HISTORY) > 30:
                        GLOBAL_ROUTING_HISTORY.pop(0)
                    
                    patient_name = data.get("nome", "?")
                    dest_str = str(data.get("dest", "")).lower()
                    dest_h = "H1" if "h1" in dest_str or ("coord_" in dest_str and "h2" not in dest_str) else "H2"
                    log(self.agent._supervisor_name, 
                        f"[ROUTING] {patient_name} encaminhado para {dest_h}", "MAGENTA")

                elif performative == "cfp" and msg_type == "load_query":
                    req_data = json.loads(msg.body)
                    requested_specialty = req_data.get("especialidade")
                    tipo = req_data.get("tipo", "Normal")
                    h_id = self.agent._hospital_id

                    # Pick the right queue key based on patient type
                    if tipo == "Urgencia":
                        base_key = f"h{h_id}_emergency"
                        spec_key = f"h{h_id}_emergency_by_specialty"
                    else:
                        base_key = f"h{h_id}_routine"
                        spec_key = f"h{h_id}_routine_by_specialty"

                    total_load = len(GLOBAL_WAITLIST.get(base_key, []))
                    by_spec = GLOBAL_WAITLIST.get(spec_key, {})
                    spec_load = len(by_spec.get(requested_specialty, [])) if requested_specialty else 0

                    reply = msg.make_reply()
                    reply.set_metadata("performative", "propose")
                    reply.set_metadata("type", "load_response")
                    reply.body = json.dumps({
                        "specialty_load": spec_load,
                        "total_load": total_load,
                        "hospital_id": h_id,
                        "supervisor_jid": str(self.agent.jid),
                    })
                    await self.send(reply)
                    log(self.agent._supervisor_name,
                        f"[LOAD-QUERY] Respondido: esp={requested_specialty}, "
                        f"spec_load={spec_load}, total={total_load}", "CYAN")

                elif performative == "request" and msg_type == "preemption_order":
                    # Refuse preemption requests that target routine consultations.
                    data = json.loads(msg.body)
                    target_queue = data.get("target_queue") or data.get("queue") or ""
                    patient_tipo = data.get("tipo") or data.get("type") or ""
                    # If the request is aiming at routine consultations, ignore/refuse it.
                    if str(target_queue).lower().startswith("routine") or str(patient_tipo).lower() == "normal":
                        log(self.agent._supervisor_name,
                            f"[PREEMPÇÃO-IGNORADA] Recusado pedido de preempção para fila rotina: {data.get('doente_jid')}",
                            "YELLOW")
                        reply = msg.make_reply()
                        reply.set_metadata("performative", "inform")
                        reply.set_metadata("type", "preemption_refused")
                        reply.body = json.dumps({"reason": "routine consultations are not preemptable"})
                        await self.send(reply)
                    else:
                        # For non-routine preemption requests let existing flows handle them
                        log(self.agent._supervisor_name,
                            f"[PREEMPÇÃO] Pedido recebido de urgências para {data.get('doente_jid')}.", "RED")
            except Exception as e:
                import traceback
                print(f"[SUPERVISOR-ERROR] Error in MonitorBehaviour: {e}")
                traceback.print_exc()

    async def setup(self):
        log(self._supervisor_name, "Supervisor initialized.", "BOLD")
        self.add_behaviour(self.MonitorBehaviour())
        self.add_behaviour(self.PeriodicDumperBehaviour())
