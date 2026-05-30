import json
import os
import time
import traceback
from datetime import datetime

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.message import Message

from src.config import *
from src.state_store import WAITLIST_QUEUES, dashboard_store


def dump_state(sim_time=None, source_supervisor=None, source_hospital_id=None):
    """Compatibility wrapper used by the dashboard/simulation code."""
    dashboard_store.dump_state(
        sim_time=sim_time,
        source_supervisor=source_supervisor,
        source_hospital_id=source_hospital_id,
    )


_original_log = log


def log(agent_name, message, color="WHITE"):
    _original_log(agent_name, message, color)
    dashboard_store.append_log(agent_name, message, color)

    if "supervisor" in str(agent_name).lower():
        full_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            os.makedirs("data", exist_ok=True)
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
        self._sim_start_time = time.time() - (8 * SIM_HOUR_SECONDS)

    class PeriodicDumperBehaviour(PeriodicBehaviour):
        async def run(self):
            elapsed = time.time() - self.agent._sim_start_time
            total_hours = elapsed / SIM_HOUR_SECONDS
            absolute_hours = total_hours

            day = int(absolute_hours // 24) + 1
            hour = int(absolute_hours % 24)
            minute = int((absolute_hours - int(absolute_hours)) * 60)
            sim_time = {"day": day, "hour": hour, "minute": minute}

            # Any supervisor can persist the global snapshot. The shared state is
            # centralised in state_store.py and protected by a lock.
            dump_state(
                sim_time,
                source_supervisor=self.agent._supervisor_name,
                source_hospital_id=self.agent._hospital_id,
            )

    class MonitorBehaviour(CyclicBehaviour):
        async def run(self):
            try:
                msg = await self.receive(timeout=SUPERVISOR_RECEIVE_TIMEOUT_SECONDS)
                if msg is None:
                    return

                performative = msg.get_metadata("performative")
                msg_type = msg.get_metadata("type")

                if performative == "inform" and msg_type == "resource_status":
                    data = json.loads(msg.body)
                    r_jid = data.get("recurso_jid")
                    if not r_jid:
                        return

                    dashboard_store.update_resource_status(r_jid, data)

                    if r_jid not in AGENT_REGISTRY:
                        AGENT_REGISTRY[r_jid] = {
                            "name": data.get("nome", r_jid.split("@")[0]),
                            "role": "patient" if "doente" in r_jid.lower() else "infra",
                            "type": "Dinâmico",
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
                            "type": patient_type,
                        }

                    estado = "LIVRE" if data["disponivel"] else f"OCUPADO(A) com {data.get('paciente_atual')}"
                    nome_r = data.get("nome", data.get("nome_sala", data.get("nome_medico", "Recurso Desconhecido")))
                    log(self.agent._supervisor_name, f"[DASHBOARD] {nome_r} -> {estado}", "BLUE")

                elif performative == "inform" and msg_type == "waitlist_update":
                    data = json.loads(msg.body)
                    queue_name = data.get("queue")
                    patients = data.get("patients", [])
                    by_specialty = data.get("by_specialty")
                    scheduled = data.get("scheduled", [])
                    scheduled_by_specialty = data.get("scheduled_by_specialty")

                    if queue_name not in WAITLIST_QUEUES:
                        log(
                            self.agent._supervisor_name,
                            f"[SALA-ESPERA] Fila desconhecida ignorada: {queue_name}",
                            "YELLOW",
                        )
                        return

                    h_key = dashboard_store.update_waitlist(
                        self.agent._hospital_id,
                        queue_name,
                        patients,
                        by_specialty=by_specialty,
                        scheduled=scheduled,
                        scheduled_by_specialty=scheduled_by_specialty,
                    )

                    log(
                        self.agent._supervisor_name,
                        f"[SALA-ESPERA] Fila '{h_key}' atualizada "
                        f"({len(patients)} pendentes, {len(scheduled)} agendados/em curso).",
                        "YELLOW",
                    )

                elif performative == "inform" and msg_type == "emergency_alert":
                    data = json.loads(msg.body)
                    p_jid = data.get("doente_jid")
                    if p_jid:
                        current = AGENT_REGISTRY.get(p_jid, {})
                        AGENT_REGISTRY[p_jid] = {
                            "name": data.get("nome", current.get("name", p_jid.split("@")[0])),
                            "role": "patient",
                            "type": "Urgência",
                        }
                    log(
                        self.agent._supervisor_name,
                        f"[ALERTA-EMERGÊNCIA] Recebido alerta prioritário! "
                        f"Doente: {data['nome']} | Prioridade: {data['prioridade']}",
                        "RED",
                    )

                elif performative == "inform" and msg_type == "routing_update":
                    data = json.loads(msg.body)
                    entry = dashboard_store.add_routing(
                        data,
                        supervisor_jid=str(self.agent.jid),
                        hospital_id=self.agent._hospital_id,
                    )

                    patient_name = entry.get("nome", "?")
                    dest_str = str(entry.get("dest", "")).lower()
                    dest_h = "H1" if "h1" in dest_str or ("coord_" in dest_str and "h2" not in dest_str) else "H2"
                    log(self.agent._supervisor_name, f"[ROUTING] {patient_name} encaminhado para {dest_h}", "MAGENTA")

                elif performative == "inform" and msg_type == "metrics_event":
                    data = json.loads(msg.body)
                    result = dashboard_store.record_metrics_event(self.agent._hospital_id, data)
                    if not result.get("ignored"):
                        log(
                            self.agent._supervisor_name,
                            f"[MÉTRICAS] Evento registado: {data.get('event')} | "
                            f"doente={data.get('nome', data.get('doente_jid', '?'))}",
                            "CYAN",
                        )

                elif performative == "cfp" and msg_type == "load_query":
                    req_data = json.loads(msg.body)
                    requested_specialty = req_data.get("especialidade")
                    tipo = req_data.get("tipo", "Normal")
                    h_id = self.agent._hospital_id

                    load = dashboard_store.get_load_metrics(h_id, tipo, requested_specialty)

                    reply = msg.make_reply()
                    reply.set_metadata("performative", "propose")
                    reply.set_metadata("type", "load_response")
                    reply.body = json.dumps({
                        **load,
                        "hospital_id": h_id,
                        "supervisor_jid": str(self.agent.jid),
                    })
                    await self.send(reply)
                    log(
                        self.agent._supervisor_name,
                        f"[LOAD-QUERY] Respondido: esp={requested_specialty}, "
                        f"spec_load={load['specialty_load']} (fila={load['pending_specialty_load']}, agenda={load['scheduled_specialty_load']}), "
                        f"total={load['total_load']} (fila={load['pending_total_load']}, agenda={load['scheduled_total_load']})",
                        "CYAN",
                    )

                elif performative == "request" and msg_type == "preemption_order":
                    # Refuse preemption requests that target routine consultations.
                    data = json.loads(msg.body)
                    target_queue = data.get("target_queue") or data.get("queue") or ""
                    patient_tipo = data.get("tipo") or data.get("type") or ""
                    if str(target_queue).lower().startswith("routine") or str(patient_tipo).lower() == "normal":
                        log(
                            self.agent._supervisor_name,
                            f"[PREEMPÇÃO-IGNORADA] Recusado pedido de preempção para fila rotina: {data.get('doente_jid')}",
                            "YELLOW",
                        )
                        reply = msg.make_reply()
                        reply.set_metadata("performative", "inform")
                        reply.set_metadata("type", "preemption_refused")
                        reply.body = json.dumps({"reason": "routine consultations are not preemptable"})
                        await self.send(reply)
                    else:
                        log(
                            self.agent._supervisor_name,
                            f"[PREEMPÇÃO] Pedido recebido de urgências para {data.get('doente_jid')}.",
                            "RED",
                        )
            except Exception as e:
                print(f"[SUPERVISOR-ERROR] Error in MonitorBehaviour: {e}")
                traceback.print_exc()

    async def setup(self):
        log(self._supervisor_name, "Supervisor initialized.", "BOLD")
        self.add_behaviour(self.MonitorBehaviour())
        self.add_behaviour(self.PeriodicDumperBehaviour(period=SUPERVISOR_DUMP_INTERVAL_SECONDS))
