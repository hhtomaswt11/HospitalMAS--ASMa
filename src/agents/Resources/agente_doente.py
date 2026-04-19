import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message

from src.config import *

class AgenteDoente(Agent):
    
    def __init__(self, agent_jid, password, nome_doente, tipo_entrada="Normal",
                 especialidade=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.nome_doente = nome_doente
        self.tipo_entrada = tipo_entrada
        self.especialidade = especialidade

    class SendRequestBehaviour(OneShotBehaviour):
        async def run(self):
            agent = self.agent
            body = json.dumps({
                "doente_jid": str(agent.jid),
                "nome": agent.nome_doente,
                "tipo": agent.tipo_entrada,
                "especialidade": agent.especialidade,
            })

            if agent.tipo_entrada == "Normal":
                dest = jid(COORD_CONS)
                log(
                    agent.nome_doente,
                    f"[PEDIDO] Consulta de ROTINA para {COORD_CONS} (esp={agent.especialidade})",
                    "GREEN",
                )
            else:
                dest = jid(COORD_TRI)
                log(agent.nome_doente, f"[PEDIDO] EMERGENCIA enviada para {COORD_TRI}", "RED")

            msg = Message(to=dest)
            msg.body = body
            msg.set_metadata("performative", "request")
            msg.set_metadata("type", "patient_request")
            msg.thread = str(agent.jid)
            await self.send(msg)
            log(agent.nome_doente, "[SUCESSO] Pedido enviado com sucesso.", "GREEN")

    class ReceiveStatusBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=RESOURCE_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                return

            msg_type = msg.get_metadata("type") or "sem_tipo"
            try:
                payload = json.loads(msg.body) if msg.body else {}
            except Exception:
                payload = {"raw": msg.body}

            resumo = payload.get("estado") or payload.get("status") or payload.get("nome") or str(payload)
            log(self.agent.nome_doente, f"[STATUS] Atualização recebida ({msg_type}): {resumo}", "CYAN")

    async def setup(self):
        log(self.nome_doente, f"AgenteDoente initialized (type={self.tipo_entrada})", "GREEN")
        self.add_behaviour(self.SendRequestBehaviour())
        self.add_behaviour(self.ReceiveStatusBehaviour())


