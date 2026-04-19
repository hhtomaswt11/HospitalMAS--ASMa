import asyncio
import json
import random

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *


class CoordenadorInternamento(Agent):
    """Coordinates inpatient admission with waiting queue when full."""

    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.pending_internments = []
        self.pending_internment_patient_ids = set()

    def enqueue_internment(self, data):
        doente_jid = data.get("doente_jid")
        if not doente_jid:
            return False
        if doente_jid in self.pending_internment_patient_ids:
            return False
        self.pending_internments.append(data)
        self.pending_internment_patient_ids.add(doente_jid)
        return True

    class InternamentoBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=COORDINATOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                if self.agent.pending_internments:
                    await self.dispatch_internment_batch()
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "internment_request":
                data = json.loads(msg.body)
                if self.agent.enqueue_internment(data):
                    await self.publish_waitlist()
                    log(COORD_INT, f"[INTERNAMENTO] Pedido recebido para {data.get('nome', '?')}", "YELLOW")
                    await self.dispatch_internment_batch()
                else:
                    log(COORD_INT, f"[INTERNAMENTO] Pedido duplicado ignorado para {data.get('nome', '?')}", "YELLOW")

            elif performative == "inform" and msg_type == "internment_finished":
                data = json.loads(msg.body)
                log(COORD_INT, f"[INTERNAMENTO] Alta concluida para {data.get('nome', '?')}", "GREEN")
                await self.dispatch_internment_batch()

        async def publish_waitlist(self):
            msg = Message(to=jid(SUPERVISOR))
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "waitlist_update")
            msg.body = json.dumps({
                "queue": "internment",
                "patients": [
                    {
                        "doente_jid": p.get("doente_jid"),
                        "nome": p.get("nome", "?"),
                        "tipo": "Internamento",
                    }
                    for p in self.agent.pending_internments
                ],
            })
            await self.send(msg)

        async def dispatch_next_internment(self):
            if not self.agent.pending_internments:
                return False

            patient = self.agent.pending_internments[0]
            allocated = await self.run_internment_contract_net(patient)
            if allocated:
                removed = self.agent.pending_internments.pop(0)
                self.agent.pending_internment_patient_ids.discard(removed.get("doente_jid"))
                await self.publish_waitlist()
                return True
            return False

        async def dispatch_internment_batch(self, max_dispatches=DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.pending_internments:
                allocated = await self.dispatch_next_internment()
                if not allocated:
                    break
                dispatched += 1

        async def run_internment_contract_net(self, patient_data):
            doente_jid = patient_data.get("doente_jid")
            nome = patient_data.get("nome", "?")

            for room_jid in INTERNAMENTO:
                cfp = Message(to=room_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "internment_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

            room_proposal = None

            loop = asyncio.get_running_loop()
            deadline = loop.time() + INTERNMENT_CONTRACT_NET_RESPONSE_WAIT_SECONDS
            expected_replies = len(INTERNAMENTO)
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
                        and reply.get_metadata("type") == "internment_request"
                    ):
                        extra = json.loads(reply.body)
                        if self.agent.enqueue_internment(extra):
                            await self.publish_waitlist()
                    continue

                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)
                if perf == "propose" and "sala_jid" in body:
                    room_proposal = body
                    log(
                        COORD_INT,
                        f"[CONTRACT-NET] Early-stop ativado para {nome}: vaga encontrada.",
                        "YELLOW",
                    )
                    break

            if room_proposal:
                acc = Message(to=room_proposal["sala_jid"])
                acc.set_metadata("performative", "accept-proposal")
                acc.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": "Internamento",
                })
                acc.thread = doente_jid
                await self.send(acc)

                duration = random.randint(INTERNAMENTO_MIN_SECONDS, INTERNAMENTO_MAX_SECONDS)
                solicitante = patient_data.get("solicitante")
                if solicitante:
                    notif = Message(to=solicitante)
                    notif.set_metadata("performative", "inform")
                    notif.set_metadata("type", "allocation_confirmed")
                    notif.body = json.dumps({
                        "doente_jid": doente_jid,
                        "nome": nome,
                        "sala_jid": room_proposal["sala_jid"],
                        "duration": duration,
                        "procedure": "internment",
                    })
                    await self.send(notif)

                log(COORD_INT, f"[INTERNAMENTO] {nome} admitido em {room_proposal.get('nome_sala', '?')} por {duration}s.", "YELLOW")
                return True

            log(COORD_INT, f"[INTERNAMENTO] Sem vagas para {nome}; mantido em fila.", "RED")
            return False

    async def setup(self):
        log(COORD_INT, "Coordenador de Internamento iniciado.", "YELLOW")
        self.add_behaviour(self.InternamentoBehaviour())
