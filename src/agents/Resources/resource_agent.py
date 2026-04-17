import json
import time

from spade.agent import Agent
from spade.behaviour import OneShotBehaviour
from spade.message import Message

from src.config import SUPERVISOR, jid


class ResourceAgent(Agent):

    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.disponivel = True
        self.paciente_atual = None

    def get_resource_name(self):
        raise NotImplementedError

    def build_status_payload(self):
        return {
            "recurso_jid": str(self.jid),
            "nome": self.get_resource_name(),
            "disponivel": self.disponivel,
            "paciente_atual": self.paciente_atual,
            "last_activity": time.time(),
        }

    def build_status_message(self):
        msg = Message(to=jid(SUPERVISOR))
        msg.set_metadata("performative", "inform")
        msg.set_metadata("type", "resource_status")
        msg.body = json.dumps(self.build_status_payload())
        return msg

    async def send_status(self, behaviour):
        await behaviour.send(self.build_status_message())

    class StartupStatusBehaviour(OneShotBehaviour):
        async def run(self):
            await self.agent.send_status(self)
