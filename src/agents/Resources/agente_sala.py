import json

from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.agents.Resources.resource_agent import ResourceAgent

from src.config import *

class AgenteSala(ResourceAgent):
    """
    Manages the temporal availability of a consultation room or clinical specific equipment.
    """
    def __init__(self, agent_jid, password, nome_sala="Sala", **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.nome_sala = nome_sala

    def get_resource_name(self):
        return self.nome_sala

    class HandleProposalsBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=RESOURCE_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            agent = self.agent

            if performative == "cfp":
                data = json.loads(msg.body)
                log(agent.nome_sala, f"[CFP] Call for Proposal received for patient {data.get('nome', '?')}", "MAGENTA")

                reply = msg.make_reply()
                if agent.disponivel:
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "sala_jid": str(agent.jid),
                        "nome_sala": agent.nome_sala,
                        "slot": "next_available",
                    })
                    log(agent.nome_sala, "[PROPOSAL] Proposal emitted (Status: Available).", "MAGENTA")
                else:
                    reply.set_metadata("performative", "reject-proposal")
                    reply.body = json.dumps({
                        "sala_jid": str(agent.jid),
                        "motivo": "Room occupied logically.",
                    })
                    log(agent.nome_sala, "[PROPOSAL] CFP rejected (Status: Occupied).", "MAGENTA")
                await self.send(reply)

            elif performative == "accept-proposal":
                data = json.loads(msg.body)
                agent.disponivel = False
                agent.paciente_atual = data.get("doente_jid")
                log(agent.nome_sala, f"[ALLOCATION] Allocation ACCEPTED for {data.get('nome', '?')}", "BLUE")
                await self.agent.send_status(self)

            elif performative == "inform" and msg.get_metadata("type") == "release":
                prev = agent.paciente_atual
                agent.disponivel = True
                agent.paciente_atual = None
                log(agent.nome_sala, f"[LIBERTAÇÃO] Procedimento concluído com sucesso. Instalação livre (doente anterior: {prev}).", "GREEN")
                await self.agent.send_status(self)

            elif performative == "cancel":
                prev = agent.paciente_atual
                agent.disponivel = True
                agent.paciente_atual = None
                log(agent.nome_sala, f"[PREEMPTION] Preemption triggered. Resource freed (previous patient ID: {prev}).", "RED")
                await self.agent.send_status(self)

                reply = msg.make_reply()
                reply.set_metadata("performative", "inform")
                reply.set_metadata("type", "cancel_confirmed")
                reply.body = json.dumps({
                    "sala_jid": str(agent.jid),
                    "status": "freed",
                })
                await self.send(reply)

    async def setup(self):
        log(self.nome_sala, f"AgenteSala initialized (available={self.disponivel})", "MAGENTA")
        self.add_behaviour(self.StartupStatusBehaviour())
        self.add_behaviour(self.HandleProposalsBehaviour())
