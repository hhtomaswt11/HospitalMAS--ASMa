import json
import time

from spade.agent import Agent
from spade.behaviour import OneShotBehaviour
from spade.message import Message

from src.config import SUPERVISOR, jid


class ResourceAgent(Agent):

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.disponivel = True
        self.paciente_atual = None
        # hospital_config contains all hospital-specific JIDs.
        # Falls back to H1 defaults so existing callsites with no config still work.
        self.hospital_config = hospital_config or {}
        self._supervisor_jid = self.hospital_config.get("supervisor", jid(SUPERVISOR))

    def get_resource_name(self):
        raise NotImplementedError

    def clear_assignment(self):
        """Liberta o recurso e limpa todos os campos auxiliares de alocação."""
        self.disponivel = True
        self.paciente_atual = None
        for field in (
            "current_assignment_type",
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
                      "on_shift", "current_assignment_type", "consult_mode"):
            val = getattr(self, field, None)
            if val is not None:
                payload[field] = val
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
