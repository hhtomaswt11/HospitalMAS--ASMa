import json

from spade.agent import Agent
from spade.behaviour import OneShotBehaviour
from spade.message import Message

from src.config import *

class AgenteDoente(Agent):
    """
    Represents a patient emitting a clinical request.
    """
    def __init__(self, agent_jid, password, nome_doente, tipo_entrada="Normal",
                 sintomas="", prioridade=0, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.nome_doente = nome_doente
        self.tipo_entrada = tipo_entrada
        self.sintomas = sintomas
        self.prioridade = prioridade

    class SendRequestBehaviour(OneShotBehaviour):
        async def run(self):
            agent = self.agent
            body = json.dumps({
                "doente_jid": str(agent.jid),
                "nome": agent.nome_doente,
                "tipo": agent.tipo_entrada,
                "sintomas": agent.sintomas,
                "prioridade": agent.prioridade,
            })

            if agent.tipo_entrada == "Normal":
                dest = jid(COORD_CONS)
                log(agent.nome_doente, f"[PEDIDO] A emitir pedido de consulta de ROTINA para {COORD_CONS}", "GREEN")
            else:
                dest = jid(TRIAGEM)
                log(agent.nome_doente, f"[PEDIDO] A emitir pedido de EMERGÊNCIA para {TRIAGEM} (sintomas: {agent.sintomas})", "RED")

            msg = Message(to=dest)
            msg.body = body
            msg.set_metadata("performative", "request")
            msg.set_metadata("type", "patient_request")
            msg.thread = str(agent.jid)
            await self.send(msg)
            log(agent.nome_doente, "[SUCESSO] Pedido enviado com sucesso.", "GREEN")

    async def setup(self):
        log(self.nome_doente, f"AgenteDoente initialized (type={self.tipo_entrada})", "GREEN")
        self.add_behaviour(self.SendRequestBehaviour())


