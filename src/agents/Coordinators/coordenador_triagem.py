import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *


class CoordenadorTriagem(Agent):

    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.pending_triage = []
        self.pending_triage_patient_ids = set()

    def enqueue_triage_request(self, data):
        doente_jid = data.get("doente_jid")
        if not doente_jid:
            return False
        if doente_jid in self.pending_triage_patient_ids:
            return False
        self.pending_triage.append(data)
        self.pending_triage_patient_ids.add(doente_jid)
        return True

    class TriageCoordinatorBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=COORDINATOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                if self.agent.pending_triage:
                    await self.dispatch_triage_batch()
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "patient_request":
                data = json.loads(msg.body)
                log(COORD_TRI, f"[TRIAGEM] Pedido de urgencia recebido: {data.get('nome', '?')}", "YELLOW")
                if self.agent.enqueue_triage_request(data):
                    await self.publish_waitlist()
                    await self.dispatch_triage_batch()
                else:
                    log(COORD_TRI, f"[TRIAGEM] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")

        async def publish_waitlist(self):
            msg = Message(to=jid(SUPERVISOR))
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "waitlist_update")
            msg.body = json.dumps({
                "queue": "triage",
                "patients": [
                    {
                        "doente_jid": p.get("doente_jid"),
                        "nome": p.get("nome", "?"),
                        "tipo": p.get("tipo", "Urgencia"),
                        "prioridade": p.get("prioridade"),
                    }
                    for p in self.agent.pending_triage
                ],
            })
            await self.send(msg)

        async def dispatch_next_triage(self):
            if not self.agent.pending_triage:
                return False

            patient = self.agent.pending_triage[0]
            allocated = await self.run_triage_contract_net(patient)
            if allocated:
                removed = self.agent.pending_triage.pop(0)
                self.agent.pending_triage_patient_ids.discard(removed.get("doente_jid"))
                await self.publish_waitlist()
                return True
            return False

        async def dispatch_triage_batch(self, max_dispatches=DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.pending_triage:
                allocated = await self.dispatch_next_triage()
                if not allocated:
                    break
                dispatched += 1

        async def run_triage_contract_net(self, patient_data):
            nome = patient_data.get("nome", "?")
            doente_jid = patient_data.get("doente_jid")

            for medico_jid in MEDICOS_TRIAGEM:
                cfp = Message(to=medico_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "triage_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

            for sala_jid in SALAS_TRIAGEM:
                cfp = Message(to=sala_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "triage_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

            medico_propostas = []
            sala_propostas = []
            expected_replies = len(MEDICOS_TRIAGEM) + len(SALAS_TRIAGEM)

            loop = asyncio.get_running_loop()
            deadline = loop.time() + TRIAGE_CONTRACT_NET_RESPONSE_WAIT_SECONDS
            received_replies = 0

            while received_replies < expected_replies:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break

                reply = await self.receive(timeout=remaining)
                if reply is None:
                    break

                received_replies += 1
                if reply.thread != doente_jid:
                    if (
                        reply.get_metadata("performative") == "request"
                        and reply.get_metadata("type") == "patient_request"
                    ):
                        extra = json.loads(reply.body)
                        if self.agent.enqueue_triage_request(extra):
                            await self.publish_waitlist()
                    continue

                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)
                if perf == "propose":
                    if "medico_jid" in body:
                        medico_propostas.append(body)
                    elif "sala_jid" in body:
                        sala_propostas.append(body)

                if medico_propostas and sala_propostas:
                    log(
                        COORD_TRI,
                        f"[CONTRACT-NET] Early-stop ativado para {nome}: par triagem encontrado.",
                        "YELLOW",
                    )
                    break

            medico_proposta = medico_propostas[0] if medico_propostas else None
            sala_proposta = sala_propostas[0] if sala_propostas else None

            if medico_proposta and sala_proposta:
                acc_m = Message(to=medico_proposta["medico_jid"])
                acc_m.set_metadata("performative", "accept-proposal")
                acc_m.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": "Urgencia",
                    "sala_jid": sala_proposta["sala_jid"],
                })
                acc_m.thread = doente_jid
                await self.send(acc_m)

                acc_s = Message(to=sala_proposta["sala_jid"])
                acc_s.set_metadata("performative", "accept-proposal")
                acc_s.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": "Urgencia",
                })
                acc_s.thread = doente_jid
                await self.send(acc_s)

                log(COORD_TRI, f"[TRIAGEM] Triagem alocada para {nome}.", "YELLOW")
                return True

            log(COORD_TRI, f"[TRIAGEM] Sem recursos para triagem de {nome}; mantido em fila.", "RED")
            return False

    async def setup(self):
        log(COORD_TRI, "Coordenador de Triagem iniciado.", "YELLOW")
        self.add_behaviour(self.TriageCoordinatorBehaviour())
