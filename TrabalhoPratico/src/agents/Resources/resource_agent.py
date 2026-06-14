import json
import time

from spade.agent import Agent
from spade.behaviour import OneShotBehaviour, PeriodicBehaviour
from spade.message import Message

from src.config import (
    SUPERVISOR, jid, log,
    SIM_HOUR_SECONDS, SIM_DAY_SECONDS, SIM_WEEK_SECONDS,
    WEEKLY_MAX_HOURS, AGENT_REGISTRY, PROCEDURE_HOURS
)


class ResourceAgent(Agent):

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.disponivel = True
        self.paciente_atual = None
        self.hospital_config = hospital_config or {}
        self._supervisor_jid = self.hospital_config.get("supervisor", jid(SUPERVISOR))

        # Scheduling / Shift logic moved from subclasses
        self.max_weekly_hours = WEEKLY_MAX_HOURS
        self.weekly_hours_used = 0.0
        self._sim_start_time = time.time() - (8 * SIM_HOUR_SECONDS)
        
        profile = AGENT_REGISTRY.get(str(agent_jid), {})
        self._shift_type = profile.get("shift", "morning")
        self.on_shift = self.compute_shift_state()
        self.current_assignment_type = None

    def compute_shift_state(self) -> bool:
        elapsed = time.time() - self._sim_start_time
        dia_simulado_s = elapsed % SIM_DAY_SECONDS
        if self._shift_type == "morning":
            return 8 * SIM_HOUR_SECONDS <= dia_simulado_s < 16 * SIM_HOUR_SECONDS
        if self._shift_type == "afternoon":
            return 16 * SIM_HOUR_SECONDS <= dia_simulado_s < 24 * SIM_HOUR_SECONDS
        return 0 <= dia_simulado_s < 8 * SIM_HOUR_SECONDS

    def sync_shift_state(self, log_change: bool = True) -> bool:
        should_be_on_shift = self.compute_shift_state()
        changed = should_be_on_shift != self.on_shift
        self.on_shift = should_be_on_shift
        if changed and log_change:
            estado = "ENTROU em turno" if should_be_on_shift else "SAIU do turno"
            log(self.get_resource_name(),
                f"[ESCALA] {self.get_resource_name()} {estado} (turno={self._shift_type}).",
                "YELLOW")
        return changed

    def add_hours(self, procedure_type: str, hours=None):
        """Soma a duração real do ato clínico à carga semanal do recurso.

        Antes era somada 1h por defeito, o que inflacionava consultas de
        15 minutos e exames. Quando a duração não é passada explicitamente
        (ex.: cirurgia dinâmica), usa PROCEDURE_HOURS do config.py.
        """
        if hours is None:
            hours = float(PROCEDURE_HOURS.get(procedure_type, 1.0))
        self.weekly_hours_used += hours
        log(self.get_resource_name(),
            f"[HORAS] {self.get_resource_name()} acumulou {self.weekly_hours_used:.2f}/{self.max_weekly_hours}h semanais "
            f"(+{hours:.2f}h por {procedure_type}).", "YELLOW")

    def get_resource_name(self):
        raise NotImplementedError

    def clear_assignment(self):
        """Liberta o recurso e limpa apenas os campos de alocação ATIVA."""
        self.disponivel = True
        self.paciente_atual = None
        
        # Only clear assignment type if it's not a reservation
        current = getattr(self, "current_assignment_type", None)
        if current and not str(current).endswith("_reserved") and current != "reserved":
            self.current_assignment_type = None

        for field in (
            "sala_atual",
            "mcdt_atual",
            "bloco_atual",
            "sala_triagem",
        ):
            if hasattr(self, field):
                setattr(self, field, None)

    def build_status_payload(self):
        payload = {
            "recurso_jid": str(self.jid),
            "nome": self.get_resource_name(),
            "disponivel": self.disponivel,
            "paciente_atual": self.paciente_atual,
            "last_activity": time.time(),
        }
        # Optional scheduling fields — subclasses set these attributes
        for field in ("role", "weekly_hours_used", "max_weekly_hours",
                      "on_shift", "current_assignment_type", "consult_mode", "zone", "specialty"):
            val = getattr(self, field, None)
            if val is not None:
                payload[field] = val

        agenda = getattr(self, "agenda", None)
        if isinstance(agenda, dict):
            payload["agenda_count"] = len(agenda)
            future_slots = []
            for doente_jid, entry in agenda.items():
                if not isinstance(entry, dict):
                    continue
                start_at = entry.get("consultation_start_at") or entry.get("exam_start_at") or entry.get("surgery_start_at")
                if start_at is None:
                    continue
                try:
                    future_slots.append((float(start_at), doente_jid, entry))
                except Exception:
                    continue
            if future_slots:
                future_slots.sort(key=lambda item: item[0])
                start_at, doente_jid, entry = future_slots[0]
                payload["next_scheduled_at"] = start_at
                payload["next_scheduled_patient"] = doente_jid
                payload["next_scheduled_patient_name"] = entry.get("nome", doente_jid)
        return payload

    def build_status_message(self):
        msg = Message(to=self._supervisor_jid)
        msg.set_metadata("performative", "inform")
        msg.set_metadata("type", "resource_status")
        msg.body = json.dumps(self.build_status_payload())
        return msg

    async def send_status(self, behaviour):
        await behaviour.send(self.build_status_message())

    class StartupStatusBehaviour(OneShotBehaviour):
        async def run(self):
            await self.agent.send_status(self)

    class ShiftRotationBehaviour(PeriodicBehaviour):
        async def run(self):
            if self.agent.sync_shift_state(log_change=True):
                await self.agent.send_status(self)

    class WeeklyResetBehaviour(PeriodicBehaviour):
        async def run(self):
            elapsed = time.time() - self.agent._sim_start_time
            current_week = int(elapsed // SIM_WEEK_SECONDS)
            if current_week > getattr(self.agent, 'last_week_reset', 0):
                self.agent.last_week_reset = current_week
                self.agent.weekly_hours_used = 0
                log(self.agent.get_resource_name(), 
                    f"[RESET SEMANAL] {self.agent.get_resource_name()} reiniciou as suas {self.agent.max_weekly_hours}h semanais.", 
                    "MAGENTA")
                await self.agent.send_status(self)
