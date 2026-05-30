"""Pequenos doubles de teste para evitar depender de um servidor XMPP/SPADE.

Os testes unitários abaixo exercitam lógica pura do projeto. Para isso não é
necessário arrancar agentes reais nem ligar ao servidor XMPP.
"""
import sys
import types


# Fake mínimo de slixmpp usado por src.patch.apply_xmpp_patch().
slixmpp = types.ModuleType("slixmpp")


class ClientXMPP:
    def connect(self, *args, **kwargs):
        return None


slixmpp.ClientXMPP = ClientXMPP
sys.modules.setdefault("slixmpp", slixmpp)


# Fake mínimo de SPADE usado em imports de agentes/coordenadores.
spade = types.ModuleType("spade")
spade_agent = types.ModuleType("spade.agent")
spade_message = types.ModuleType("spade.message")
spade_behaviour = types.ModuleType("spade.behaviour")


class Agent:
    def __init__(self, jid, password, *args, **kwargs):
        self.jid = jid
        self.password = password
        self.behaviours = []

    def add_behaviour(self, behaviour, template=None):
        behaviour.agent = self
        self.behaviours.append((behaviour, template))

    async def stop(self):
        return None


class Message:
    def __init__(self, to=None):
        self.to = to
        self.body = ""
        self.thread = None
        self._metadata = {}

    def set_metadata(self, key, value):
        self._metadata[key] = value

    def get_metadata(self, key):
        return self._metadata.get(key)


class _Behaviour:
    def __init__(self, *args, **kwargs):
        self.agent = None
        self.sent_messages = []

    async def send(self, msg):
        self.sent_messages.append(msg)

    async def receive(self, timeout=None):
        return None


class CyclicBehaviour(_Behaviour):
    pass


class OneShotBehaviour(_Behaviour):
    pass


class PeriodicBehaviour(_Behaviour):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.period = kwargs.get("period")


spade_agent.Agent = Agent
spade_message.Message = Message
spade_behaviour.CyclicBehaviour = CyclicBehaviour
spade_behaviour.OneShotBehaviour = OneShotBehaviour
spade_behaviour.PeriodicBehaviour = PeriodicBehaviour

sys.modules.setdefault("spade", spade)
sys.modules.setdefault("spade.agent", spade_agent)
sys.modules.setdefault("spade.message", spade_message)
sys.modules.setdefault("spade.behaviour", spade_behaviour)
