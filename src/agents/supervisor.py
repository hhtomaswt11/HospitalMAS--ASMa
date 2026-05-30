import json
import asyncio
import os
import time
import traceback
from copy import deepcopy
from datetime import datetime
from threading import RLock

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.message import Message

from src.config import *

# ─────────────────────────────────────────────────────────────
# Estado partilhado do dashboard
# ─────────────────────────────────────────────────────────────
# Os dois supervisores correm no mesmo processo e, por isso, partilham estas
# estruturas de módulo. Mantemos este estado global para o dashboard central,
# mas todas as filas são guardadas por hospital (h1_*, h2_*) e os campos
# agregados sem prefixo são reconstruídos por merge, nunca por overwrite.
STATE_LOCK = RLock()
WAITLIST_QUEUES = ("routine", "emergency", "triage", "internment")


def _initial_waitlist_state():
    state = {}
    for queue in WAITLIST_QUEUES:
        state[queue] = []
        state[f"{queue}_by_specialty"] = {}
        state[f"{queue}_scheduled"] = []
        state[f"{queue}_scheduled_by_specialty"] = {}
    return state


GLOBAL_DASHBOARD = {}
GLOBAL_WAITLIST = _initial_waitlist_state()
GLOBAL_ROUTING_HISTORY = []
RECENT_LOGS = []


def _dedupe_patients(items):
    """Merge de listas de pacientes sem duplicar o mesmo doente."""
    merged = []
    seen = set()
    for item in items:
        if not item:
            continue
        if isinstance(item, dict):
            key = item.get("doente_jid") or item.get("jid") or json.dumps(item, sort_keys=True, ensure_ascii=False)
        else:
            key = str(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _merge_specialty_maps(maps):
    merged = {}
    for by_specialty in maps:
        if not isinstance(by_specialty, dict):
            continue
        for specialty, patients in by_specialty.items():
            merged.setdefault(specialty, [])
            merged[specialty] = _dedupe_patients(merged[specialty] + list(patients or []))
    return merged


def _matching_hospital_keys(suffix):
    return [key for key in GLOBAL_WAITLIST if key.startswith("h") and key[1:2].isdigit() and key.endswith(suffix)]


def _rebuild_aggregated_waitlist(queue_name):
    """Reconstrói as chaves globais a partir das chaves h1_*/h2_* existentes."""
    patient_keys = _matching_hospital_keys(f"_{queue_name}")
    scheduled_keys = _matching_hospital_keys(f"_{queue_name}_scheduled")
    specialty_keys = _matching_hospital_keys(f"_{queue_name}_by_specialty")
    scheduled_specialty_keys = _matching_hospital_keys(f"_{queue_name}_scheduled_by_specialty")

    GLOBAL_WAITLIST[queue_name] = _dedupe_patients(
        patient for key in patient_keys for patient in GLOBAL_WAITLIST.get(key, [])
    )
    GLOBAL_WAITLIST[f"{queue_name}_scheduled"] = _dedupe_patients(
        patient for key in scheduled_keys for patient in GLOBAL_WAITLIST.get(key, [])
    )
    GLOBAL_WAITLIST[f"{queue_name}_by_specialty"] = _merge_specialty_maps(
        GLOBAL_WAITLIST.get(key, {}) for key in specialty_keys
    )
    GLOBAL_WAITLIST[f"{queue_name}_scheduled_by_specialty"] = _merge_specialty_maps(
        GLOBAL_WAITLIST.get(key, {}) for key in scheduled_specialty_keys
    )


def _belongs_to_hospital(agent_jid, hospital_id):
    info = AGENT_REGISTRY.get(agent_jid, {})
    if info.get("hospital") == hospital_id:
        return True

    local_name = str(agent_jid).split("@")[0]
    if hospital_id == 2:
        return local_name.startswith("h2_")
    return not local_name.startswith("h2_")


def _hospital_waitlist_view(hospital_id):
    """Constrói uma vista isolada da lista de espera para um hospital."""
    prefix = f"h{hospital_id}_"
    view = {}
    for queue in WAITLIST_QUEUES:
        h_key = f"{prefix}{queue}"
        view[h_key] = deepcopy(GLOBAL_WAITLIST.get(h_key, []))
        view[f"{h_key}_by_specialty"] = deepcopy(GLOBAL_WAITLIST.get(f"{h_key}_by_specialty", {}))
        view[f"{h_key}_scheduled"] = deepcopy(GLOBAL_WAITLIST.get(f"{h_key}_scheduled", []))
        view[f"{h_key}_scheduled_by_specialty"] = deepcopy(GLOBAL_WAITLIST.get(f"{h_key}_scheduled_by_specialty", {}))

        # Chaves sem prefixo para compatibilidade com consumidores que leem
        # apenas um hospital isolado.
        view[queue] = deepcopy(view[h_key])
        view[f"{queue}_by_specialty"] = deepcopy(view[f"{h_key}_by_specialty"])
        view[f"{queue}_scheduled"] = deepcopy(view[f"{h_key}_scheduled"])
        view[f"{queue}_scheduled_by_specialty"] = deepcopy(view[f"{h_key}_scheduled_by_specialty"])
    return view


def _build_state_snapshot(sim_time=None, source_supervisor=None, hospital_id=None):
    if hospital_id is None:
        resources = deepcopy(GLOBAL_DASHBOARD)
        waitlist = deepcopy(GLOBAL_WAITLIST)
        registry = deepcopy(AGENT_REGISTRY)
    else:
        resources = deepcopy({
            jid_: data for jid_, data in GLOBAL_DASHBOARD.items()
            if _belongs_to_hospital(jid_, hospital_id)
        })
        waitlist = _hospital_waitlist_view(hospital_id)
        registry = deepcopy({
            jid_: data for jid_, data in AGENT_REGISTRY.items()
            if data.get("role") == "patient" or _belongs_to_hospital(jid_, hospital_id)
        })

    return {
        "resources": resources,
        "waitlist": waitlist,
        "routing": deepcopy(GLOBAL_ROUTING_HISTORY),
        "logs": deepcopy(RECENT_LOGS),
        "registry": registry,
        "sim_time": sim_time or {"day": 1, "hour": 0, "minute": 0},
        "last_writer": source_supervisor,
        "hospital_id": hospital_id,
    }


def _write_json_atomic(path, data):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, path)


def dump_state(sim_time=None, source_supervisor=None, source_hospital_id=None):
    """Persiste snapshots coerentes do dashboard.

    - data/dashboard.json: vista global agregada dos dois hospitais;
    - data/dashboard_h1.json / dashboard_h2.json: vista isolada do hospital que escreveu.

    A escrita é atómica para evitar JSON corrompido quando os dois supervisores
    escrevem quase ao mesmo tempo.
    """
    try:
        with STATE_LOCK:
            os.makedirs("data", exist_ok=True)
            global_state = _build_state_snapshot(sim_time, source_supervisor, hospital_id=None)
            hospital_state = (
                _build_state_snapshot(sim_time, source_supervisor, hospital_id=source_hospital_id)
                if source_hospital_id is not None else None
            )

        _write_json_atomic("data/dashboard.json", global_state)
        if hospital_state is not None:
            _write_json_atomic(f"data/dashboard_h{source_hospital_id}.json", hospital_state)
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

            # Qualquer supervisor pode persistir o snapshot global. Isto evita
            # depender exclusivamente do H1 para atualizar o dashboard central.
            dump_state(sim_time, source_supervisor=self.agent._supervisor_name, source_hospital_id=self.agent._hospital_id)

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
                    if not r_jid:
                        return
                    with STATE_LOCK:
                        GLOBAL_DASHBOARD[r_jid] = data

                        if r_jid not in AGENT_REGISTRY:
                            AGENT_REGISTRY[r_jid] = {
                                "name": data.get("nome", r_jid.split("@")[0]),
                                "role": "patient" if "doente" in r_jid.lower() else "infra",
                                "type": "Dinâmico"
                            }

                    p_jid = data.get("paciente_atual")
                    if p_jid:
                        with STATE_LOCK:
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
                    scheduled = data.get("scheduled", [])
                    scheduled_by_specialty = data.get("scheduled_by_specialty")
                    if queue_name not in WAITLIST_QUEUES:
                        log(self.agent._supervisor_name,
                            f"[SALA-ESPERA] Fila desconhecida ignorada: {queue_name}",
                            "YELLOW")
                        return

                    with STATE_LOCK:
                        # 1. Atualiza sempre a fila por hospital. Ex.: h1_routine, h2_emergency.
                        h_key = f"h{self.agent._hospital_id}_{queue_name}"
                        GLOBAL_WAITLIST[h_key] = patients

                        # 2. Atualiza agrupamentos/agenda também por hospital.
                        if by_specialty is not None:
                            GLOBAL_WAITLIST[f"{h_key}_by_specialty"] = by_specialty
                        GLOBAL_WAITLIST[f"{h_key}_scheduled"] = scheduled
                        if scheduled_by_specialty is not None:
                            GLOBAL_WAITLIST[f"{h_key}_scheduled_by_specialty"] = scheduled_by_specialty

                        # 3. Reconstrói a vista agregada global por merge.
                        # Antes, o último supervisor a escrever ganhava e apagava a fila do outro hospital.
                        _rebuild_aggregated_waitlist(queue_name)

                    log(self.agent._supervisor_name,
                        f"[SALA-ESPERA] Fila '{h_key}' atualizada "
                        f"({len(patients)} pendentes, {len(scheduled)} agendados/em curso).",
                        "YELLOW")

                elif performative == "inform" and msg_type == "emergency_alert":
                    data = json.loads(msg.body)
                    p_jid = data.get("doente_jid")
                    if p_jid:
                        with STATE_LOCK:
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
                    data.setdefault("supervisor_jid", str(self.agent.jid))
                    data.setdefault("hospital_id", self.agent._hospital_id)
                    with STATE_LOCK:
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

                    with STATE_LOCK:
                        pending_total = len(GLOBAL_WAITLIST.get(base_key, []))
                        scheduled_total = len(GLOBAL_WAITLIST.get(f"{base_key}_scheduled", []))
                        by_spec = GLOBAL_WAITLIST.get(spec_key, {})
                        scheduled_by_spec = GLOBAL_WAITLIST.get(f"{base_key}_scheduled_by_specialty", {})
                        pending_spec = len(by_spec.get(requested_specialty, [])) if requested_specialty else 0
                        scheduled_spec = len(scheduled_by_spec.get(requested_specialty, [])) if requested_specialty else 0
                        spec_load = pending_spec + scheduled_spec
                        total_load = pending_total + scheduled_total

                    reply = msg.make_reply()
                    reply.set_metadata("performative", "propose")
                    reply.set_metadata("type", "load_response")
                    reply.body = json.dumps({
                        "specialty_load": spec_load,
                        "total_load": total_load,
                        "pending_specialty_load": pending_spec,
                        "scheduled_specialty_load": scheduled_spec,
                        "pending_total_load": pending_total,
                        "scheduled_total_load": scheduled_total,
                        "hospital_id": h_id,
                        "supervisor_jid": str(self.agent.jid),
                    })
                    await self.send(reply)
                    log(self.agent._supervisor_name,
                        f"[LOAD-QUERY] Respondido: esp={requested_specialty}, "
                        f"spec_load={spec_load} (fila={pending_spec}, agenda={scheduled_spec}), "
                        f"total={total_load} (fila={pending_total}, agenda={scheduled_total})", "CYAN")

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
                print(f"[SUPERVISOR-ERROR] Error in MonitorBehaviour: {e}")
                traceback.print_exc()

    async def setup(self):
        log(self._supervisor_name, "Supervisor initialized.", "BOLD")
        self.add_behaviour(self.MonitorBehaviour())
        self.add_behaviour(self.PeriodicDumperBehaviour(period=SUPERVISOR_DUMP_INTERVAL_SECONDS))
