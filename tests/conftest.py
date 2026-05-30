"""Pequenos doubles de teste para evitar depender de um servidor XMPP/SPADE.

Os testes unitários deste projecto exercitam lógica pura. Para isso não é
necessário arrancar agentes reais nem ligar ao servidor XMPP.

Este ficheiro é carregado automaticamente pelo unittest (via sys.path) e pelo
pytest (como conftest.py) antes de qualquer ficheiro de testes da pasta.
"""
import sys
import os
import types

# ── Garante que a raiz do projecto está no sys.path ──────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ── Fake mínimo de slixmpp (usado por src.patch.apply_xmpp_patch) ────────────
slixmpp = types.ModuleType("slixmpp")


class _SlixClientXMPP:
    def connect(self, *args, **kwargs):
        return None


slixmpp.ClientXMPP = _SlixClientXMPP
sys.modules.setdefault("slixmpp", slixmpp)


# ── Fake completo de SPADE ────────────────────────────────────────────────────
spade = types.ModuleType("spade")
spade_agent = types.ModuleType("spade.agent")
spade_message = types.ModuleType("spade.message")
spade_behaviour = types.ModuleType("spade.behaviour")


class Agent:
    """Substituto mínimo de spade.agent.Agent para testes sem servidor XMPP."""

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
    """Substituto de spade.message.Message que regista metadados e body."""

    def __init__(self, to=None):
        self.to = to
        self.body = ""
        self.thread = None
        self._metadata = {}

    def set_metadata(self, key, value):
        self._metadata[key] = value

    def get_metadata(self, key):
        return self._metadata.get(key)

    def make_reply(self):
        reply = Message(to=str(self.to))
        reply.thread = self.thread
        return reply


class _BaseBehaviour:
    """Base partilhada pelos behaviours de teste — guarda mensagens enviadas."""

    def __init__(self, *args, **kwargs):
        self.agent = None
        self.sent_messages = []

    async def send(self, msg):
        self.sent_messages.append(msg)

    async def receive(self, timeout=None):
        return None


class CyclicBehaviour(_BaseBehaviour):
    pass


class OneShotBehaviour(_BaseBehaviour):
    pass


class PeriodicBehaviour(_BaseBehaviour):
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
