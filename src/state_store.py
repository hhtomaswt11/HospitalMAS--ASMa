"""Thread-safe state store for the hospital simulation dashboard.

This module is the single owner of dashboard runtime state.  The two
Supervisor agents run in the same Python process, so module-level state in
``supervisor.py`` could be overwritten accidentally by whichever supervisor
wrote last.  Keeping the shared state here centralises locking, namespacing and
snapshot generation.
"""
from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from datetime import datetime
from threading import RLock
from typing import Any, Dict, Iterable, Optional

from src.config import AGENT_REGISTRY

WAITLIST_QUEUES = ("routine", "emergency", "triage", "internment")


def _initial_waitlist_state() -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    for queue in WAITLIST_QUEUES:
        state[queue] = []
        state[f"{queue}_by_specialty"] = {}
        state[f"{queue}_scheduled"] = []
        state[f"{queue}_scheduled_by_specialty"] = {}
    return state


def _initial_hospital_metrics() -> Dict[str, Any]:
    return {
        "attended_by_type": {
            "routine": 0,
            "emergency": 0,
        },
        "wait_time_seconds": {
            "routine": [],
            "emergency": [],
        },
        "average_wait_seconds": {
            "routine": None,
            "emergency": None,
            "overall": None,
        },
        "failed_after_retries": 0,
        "failed_after_retries_by_procedure": {},
        "failed_after_retries_by_reason": {},
    }


def _safe_json_key(item: Any) -> str:
    if isinstance(item, dict):
        return item.get("doente_jid") or item.get("jid") or json.dumps(item, sort_keys=True, ensure_ascii=False)
    return str(item)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class DashboardStateStore:
    def __init__(self) -> None:
        self.lock = RLock()
        self.dashboard: Dict[str, Dict[str, Any]] = {}
        self.waitlist: Dict[str, Any] = _initial_waitlist_state()
        self.routing_history = []
        self.recent_logs = []
        self.metrics: Dict[str, Any] = self._initial_metrics()
        self._attended_patient_ids = set()
        self._failed_patient_ids = set()

    def _initial_metrics(self) -> Dict[str, Any]:
        return {
            "by_hospital": {
                "h1": _initial_hospital_metrics(),
                "h2": _initial_hospital_metrics(),
            },
            "events": [],
            "notes": [
                "Tempo de espera = início real da primeira consulta - instante de criação do agente doente.",
                "Falhas após retentativas contam procedimentos que esgotaram o limite configurado.",
            ],
        }

    # ─────────────────────────────────────────────────────────────
    # Basic helpers
    # ─────────────────────────────────────────────────────────────
    def _dedupe_patients(self, items: Iterable[Any]) -> list:
        merged = []
        seen = set()
        for item in items:
            if not item:
                continue
            key = _safe_json_key(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def _merge_specialty_maps(self, maps: Iterable[Dict[str, Any]]) -> Dict[str, list]:
        merged: Dict[str, list] = {}
        for by_specialty in maps:
            if not isinstance(by_specialty, dict):
                continue
            for specialty, patients in by_specialty.items():
                merged.setdefault(specialty, [])
                merged[specialty] = self._dedupe_patients(merged[specialty] + list(patients or []))
        return merged

    def _matching_hospital_keys(self, suffix: str) -> list[str]:
        return [
            key for key in self.waitlist
            if key.startswith("h") and key[1:2].isdigit() and key.endswith(suffix)
        ]

    def _rebuild_aggregated_waitlist(self, queue_name: str) -> None:
        patient_keys = self._matching_hospital_keys(f"_{queue_name}")
        scheduled_keys = self._matching_hospital_keys(f"_{queue_name}_scheduled")
        specialty_keys = self._matching_hospital_keys(f"_{queue_name}_by_specialty")
        scheduled_specialty_keys = self._matching_hospital_keys(f"_{queue_name}_scheduled_by_specialty")

        self.waitlist[queue_name] = self._dedupe_patients(
            patient for key in patient_keys for patient in self.waitlist.get(key, [])
        )
        self.waitlist[f"{queue_name}_scheduled"] = self._dedupe_patients(
            patient for key in scheduled_keys for patient in self.waitlist.get(key, [])
        )
        self.waitlist[f"{queue_name}_by_specialty"] = self._merge_specialty_maps(
            self.waitlist.get(key, {}) for key in specialty_keys
        )
        self.waitlist[f"{queue_name}_scheduled_by_specialty"] = self._merge_specialty_maps(
            self.waitlist.get(key, {}) for key in scheduled_specialty_keys
        )

    @staticmethod
    def _belongs_to_hospital(agent_jid: str, hospital_id: int) -> bool:
        info = AGENT_REGISTRY.get(agent_jid, {})
        if info.get("hospital") == hospital_id:
            return True
        local_name = str(agent_jid).split("@")[0]
        if hospital_id == 2:
            return local_name.startswith("h2_")
        return not local_name.startswith("h2_")

    @staticmethod
    def _hospital_key(hospital_id: int | str | None) -> str:
        try:
            hid = int(hospital_id or 1)
        except (TypeError, ValueError):
            hid = 1
        return f"h{hid}"

    @staticmethod
    def _normalise_patient_type(value: Any) -> str:
        text = str(value or "").lower()
        if "urg" in text or "emerg" in text:
            return "emergency"
        return "routine"

    # ─────────────────────────────────────────────────────────────
    # Public update methods
    # ─────────────────────────────────────────────────────────────
    def append_log(self, agent_name: str, message: str, color: str = "WHITE") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            self.recent_logs.append({"time": timestamp, "agent": agent_name, "message": message, "color": color})
            if len(self.recent_logs) > 40:
                self.recent_logs.pop(0)

    def update_resource_status(self, resource_jid: str, data: Dict[str, Any]) -> None:
        with self.lock:
            self.dashboard[resource_jid] = data

    def update_waitlist(
        self,
        hospital_id: int,
        queue_name: str,
        patients: list,
        by_specialty: Optional[Dict[str, Any]] = None,
        scheduled: Optional[list] = None,
        scheduled_by_specialty: Optional[Dict[str, Any]] = None,
    ) -> str:
        if queue_name not in WAITLIST_QUEUES:
            raise ValueError(f"Fila desconhecida: {queue_name}")

        with self.lock:
            h_key = f"h{hospital_id}_{queue_name}"
            self.waitlist[h_key] = patients or []
            if by_specialty is not None:
                self.waitlist[f"{h_key}_by_specialty"] = by_specialty
            self.waitlist[f"{h_key}_scheduled"] = scheduled or []
            if scheduled_by_specialty is not None:
                self.waitlist[f"{h_key}_scheduled_by_specialty"] = scheduled_by_specialty
            self._rebuild_aggregated_waitlist(queue_name)
            return h_key

    def add_routing(self, data: Dict[str, Any], supervisor_jid: str, hospital_id: int) -> Dict[str, Any]:
        entry = dict(data)
        entry["time"] = datetime.now().strftime("%H:%M:%S")
        entry.setdefault("supervisor_jid", supervisor_jid)
        entry.setdefault("hospital_id", hospital_id)
        with self.lock:
            self.routing_history.append(entry)
            if len(self.routing_history) > 30:
                self.routing_history.pop(0)
        return entry

    def get_load_metrics(self, hospital_id: int, tipo: str, requested_specialty: Optional[str]) -> Dict[str, Any]:
        base = "emergency" if tipo == "Urgencia" else "routine"
        base_key = f"h{hospital_id}_{base}"
        spec_key = f"{base_key}_by_specialty"
        with self.lock:
            pending_total = len(self.waitlist.get(base_key, []))
            scheduled_total = len(self.waitlist.get(f"{base_key}_scheduled", []))
            by_spec = self.waitlist.get(spec_key, {})
            scheduled_by_spec = self.waitlist.get(f"{base_key}_scheduled_by_specialty", {})
            pending_spec = len(by_spec.get(requested_specialty, [])) if requested_specialty else 0
            scheduled_spec = len(scheduled_by_spec.get(requested_specialty, [])) if requested_specialty else 0
        return {
            "specialty_load": pending_spec + scheduled_spec,
            "total_load": pending_total + scheduled_total,
            "pending_specialty_load": pending_spec,
            "scheduled_specialty_load": scheduled_spec,
            "pending_total_load": pending_total,
            "scheduled_total_load": scheduled_total,
        }

    # ─────────────────────────────────────────────────────────────
    # Metrics
    # ─────────────────────────────────────────────────────────────
    def record_metrics_event(self, hospital_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        event_type = data.get("event") or data.get("event_type")
        if event_type == "patient_started":
            return self.record_patient_started(hospital_id, data)
        if event_type == "patient_failed_after_retries":
            return self.record_patient_failed_after_retries(hospital_id, data)
        return {"ignored": True, "reason": f"unknown event {event_type}"}

    def record_patient_started(self, hospital_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        patient_id = data.get("doente_jid") or data.get("patient_id")
        if not patient_id:
            return {"ignored": True, "reason": "missing patient id"}

        h_key = self._hospital_key(hospital_id)
        patient_type = self._normalise_patient_type(data.get("patient_type") or data.get("tipo") or data.get("tipo_original"))
        actual_start = _safe_float(data.get("actual_start_at")) or time.time()
        spawned_at = _safe_float(data.get("spawned_at") or data.get("created_at"))

        event = {
            "event": "patient_started",
            "hospital": h_key.upper(),
            "doente_jid": patient_id,
            "nome": data.get("nome"),
            "patient_type": patient_type,
            "actual_start_at": actual_start,
        }
        if spawned_at is not None:
            event["spawned_at"] = spawned_at
            event["wait_seconds"] = max(0.0, actual_start - spawned_at)

        with self.lock:
            if patient_id in self._attended_patient_ids:
                return {"ignored": True, "reason": "duplicate patient_started"}
            self._attended_patient_ids.add(patient_id)

            hospital_metrics = self.metrics["by_hospital"].setdefault(h_key, _initial_hospital_metrics())
            hospital_metrics["attended_by_type"][patient_type] = hospital_metrics["attended_by_type"].get(patient_type, 0) + 1
            if "wait_seconds" in event:
                waits = hospital_metrics["wait_time_seconds"].setdefault(patient_type, [])
                waits.append(event["wait_seconds"])
                self._recalculate_average_waits(hospital_metrics)

            self.metrics["events"].append(event)
            if len(self.metrics["events"]) > 50:
                self.metrics["events"].pop(0)
        return event

    def record_patient_failed_after_retries(self, hospital_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        patient_id = data.get("doente_jid") or data.get("patient_id")
        if not patient_id:
            return {"ignored": True, "reason": "missing patient id"}

        h_key = self._hospital_key(hospital_id)
        procedure = str(data.get("procedure") or "unknown")
        reason = str(data.get("reason") or data.get("motivo") or "sem_motivo")

        event = {
            "event": "patient_failed_after_retries",
            "hospital": h_key.upper(),
            "doente_jid": patient_id,
            "nome": data.get("nome"),
            "procedure": procedure,
            "reason": reason,
            "retry_count": data.get("retry_count"),
            "time": time.time(),
        }

        # Include procedure in the de-duplication key because the same patient may
        # fail different downstream services at different points of the flow.
        failure_key = (patient_id, procedure)
        with self.lock:
            if failure_key in self._failed_patient_ids:
                return {"ignored": True, "reason": "duplicate patient_failed_after_retries"}
            self._failed_patient_ids.add(failure_key)

            hospital_metrics = self.metrics["by_hospital"].setdefault(h_key, _initial_hospital_metrics())
            hospital_metrics["failed_after_retries"] += 1
            by_proc = hospital_metrics["failed_after_retries_by_procedure"]
            by_proc[procedure] = by_proc.get(procedure, 0) + 1
            by_reason = hospital_metrics["failed_after_retries_by_reason"]
            by_reason[reason] = by_reason.get(reason, 0) + 1

            self.metrics["events"].append(event)
            if len(self.metrics["events"]) > 50:
                self.metrics["events"].pop(0)
        return event

    @staticmethod
    def _recalculate_average_waits(hospital_metrics: Dict[str, Any]) -> None:
        wait_map = hospital_metrics.get("wait_time_seconds", {})
        avg = hospital_metrics.setdefault("average_wait_seconds", {})
        all_waits = []
        for patient_type in ("routine", "emergency"):
            waits = [float(v) for v in wait_map.get(patient_type, [])]
            all_waits.extend(waits)
            avg[patient_type] = round(sum(waits) / len(waits), 2) if waits else None
        avg["overall"] = round(sum(all_waits) / len(all_waits), 2) if all_waits else None

    # ─────────────────────────────────────────────────────────────
    # Snapshot / persistence
    # ─────────────────────────────────────────────────────────────
    def _hospital_waitlist_view(self, hospital_id: int) -> Dict[str, Any]:
        prefix = f"h{hospital_id}_"
        view: Dict[str, Any] = {}
        for queue in WAITLIST_QUEUES:
            h_key = f"{prefix}{queue}"
            view[h_key] = deepcopy(self.waitlist.get(h_key, []))
            view[f"{h_key}_by_specialty"] = deepcopy(self.waitlist.get(f"{h_key}_by_specialty", {}))
            view[f"{h_key}_scheduled"] = deepcopy(self.waitlist.get(f"{h_key}_scheduled", []))
            view[f"{h_key}_scheduled_by_specialty"] = deepcopy(self.waitlist.get(f"{h_key}_scheduled_by_specialty", {}))

            # Flat keys for consumers that read a single-hospital snapshot.
            view[queue] = deepcopy(view[h_key])
            view[f"{queue}_by_specialty"] = deepcopy(view[f"{h_key}_by_specialty"])
            view[f"{queue}_scheduled"] = deepcopy(view[f"{h_key}_scheduled"])
            view[f"{queue}_scheduled_by_specialty"] = deepcopy(view[f"{h_key}_scheduled_by_specialty"])
        return view

    def _metrics_snapshot(self, hospital_id: int | None = None) -> Dict[str, Any]:
        metrics = deepcopy(self.metrics)
        if hospital_id is None:
            return metrics
        h_key = self._hospital_key(hospital_id)
        return {
            "by_hospital": {h_key: metrics.get("by_hospital", {}).get(h_key, _initial_hospital_metrics())},
            "events": [event for event in metrics.get("events", []) if event.get("hospital") == h_key.upper()],
            "notes": metrics.get("notes", []),
        }

    def build_state_snapshot(
        self,
        sim_time: Optional[Dict[str, Any]] = None,
        source_supervisor: Optional[str] = None,
        hospital_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        with self.lock:
            if hospital_id is None:
                resources = deepcopy(self.dashboard)
                waitlist = deepcopy(self.waitlist)
                registry = deepcopy(AGENT_REGISTRY)
            else:
                resources = deepcopy({
                    jid_: data for jid_, data in self.dashboard.items()
                    if self._belongs_to_hospital(jid_, hospital_id)
                })
                waitlist = self._hospital_waitlist_view(hospital_id)
                registry = deepcopy({
                    jid_: data for jid_, data in AGENT_REGISTRY.items()
                    if data.get("role") == "patient" or self._belongs_to_hospital(jid_, hospital_id)
                })

            return {
                "resources": resources,
                "waitlist": waitlist,
                "routing": deepcopy(self.routing_history),
                "logs": deepcopy(self.recent_logs),
                "registry": registry,
                "metrics": self._metrics_snapshot(hospital_id),
                "sim_time": sim_time or {"day": 1, "hour": 0, "minute": 0},
                "last_writer": source_supervisor,
                "hospital_id": hospital_id,
            }

    @staticmethod
    def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, path)

    def dump_state(
        self,
        sim_time: Optional[Dict[str, Any]] = None,
        source_supervisor: Optional[str] = None,
        source_hospital_id: Optional[int] = None,
    ) -> None:
        try:
            os.makedirs("data", exist_ok=True)
            global_state = self.build_state_snapshot(sim_time, source_supervisor, hospital_id=None)
            hospital_state = (
                self.build_state_snapshot(sim_time, source_supervisor, hospital_id=source_hospital_id)
                if source_hospital_id is not None else None
            )
            self._write_json_atomic("data/dashboard.json", global_state)
            if hospital_state is not None:
                self._write_json_atomic(f"data/dashboard_h{source_hospital_id}.json", hospital_state)
        except Exception as exc:
            print(f"[STATE-STORE] dump_state failed: {exc}")


# Singleton usado pelos dois Supervisores.
dashboard_store = DashboardStateStore()
