import asyncio
import json
import random

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *


class CoordenadorInternamento(Agent):
    """Coordinates inpatient admission with waiting queue when full."""

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        cfg = hospital_config or H1_CONFIG
        self._supervisor = cfg["supervisor"]
        self._internamento = cfg["internamento"]
        self._enfermeiros = cfg.get("enfermeiros", [])
        self._coord_name = str(agent_jid).split("@")[0]

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
                    log(self.agent._coord_name,
                        f"[INTERNAMENTO] Pedido recebido para {data.get('nome', '?')}", "YELLOW")
                    await self.dispatch_internment_batch()
                else:
                    log(self.agent._coord_name,
                        f"[INTERNAMENTO] Pedido duplicado ignorado para {data.get('nome', '?')}", "YELLOW")

            elif performative == "inform" and msg_type == "internment_finished":
                data = json.loads(msg.body)
                log(self.agent._coord_name,
                    f"[INTERNAMENTO] Alta concluida para {data.get('nome', '?')}", "GREEN")
                await self.dispatch_internment_batch()

        async def publish_waitlist(self):
            msg = Message(to=self.agent._supervisor)
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
            agent = self.agent
            doente_jid = patient_data.get("doente_jid")
            nome = patient_data.get("nome", "?")

            # ── Phase 1: CFP to all internment rooms ──
            for room_jid in agent._internamento:
                cfp = Message(to=room_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "internment_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

            room_proposal = None
            loop = asyncio.get_running_loop()
            deadline = loop.time() + INTERNMENT_CONTRACT_NET_RESPONSE_WAIT_SECONDS
            expected_replies = len(agent._internamento)
            received_replies = 0

            while received_replies < expected_replies:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                reply = await self.receive(timeout=remaining)
                if reply is None:
                    break
                if reply.thread != doente_jid:
                    if (reply.get_metadata("performative") == "request"
                            and reply.get_metadata("type") == "internment_request"):
                        extra = json.loads(reply.body)
                        if agent.enqueue_internment(extra):
                            await self.publish_waitlist()
                    continue
                received_replies += 1
                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)
                if perf == "propose" and "sala_jid" in body:
                    room_proposal = body
                    log(agent._coord_name,
                        f"[CONTRACT-NET] Quarto encontrado para {nome}: {body.get('nome_sala', '?')}.", "YELLOW")
                    # Removemos o break para ler todas as respostas e limpar a mailbox!

            if not room_proposal:
                log(agent._coord_name, f"[INTERNAMENTO] Sem quartos disponíveis para {nome}; mantido em fila.", "RED")
                return False

            # ── Phase 2: CFP to all nurses ──
            nurse_proposal = None
            if agent._enfermeiros:
                for nurse_jid in agent._enfermeiros:
                    cfp_n = Message(to=nurse_jid)
                    cfp_n.body = json.dumps(patient_data)
                    cfp_n.set_metadata("performative", "cfp")
                    cfp_n.set_metadata("type", "internment_cfp")
                    cfp_n.thread = doente_jid + "_nurse"
                    await self.send(cfp_n)

                deadline_n = loop.time() + INTERNMENT_CONTRACT_NET_RESPONSE_WAIT_SECONDS
                expected_n = len(agent._enfermeiros)
                received_n = 0
                while received_n < expected_n:
                    remaining = deadline_n - loop.time()
                    if remaining <= 0:
                        break
                    reply = await self.receive(timeout=remaining)
                    if reply is None:
                        break
                    if reply.thread != doente_jid + "_nurse":
                        continue
                    received_n += 1
                    perf = reply.get_metadata("performative")
                    body = json.loads(reply.body)
                    if perf == "propose" and "enfermeiro_jid" in body:
                        nurse_proposal = body
                        log(agent._coord_name,
                            f"[CONTRACT-NET] Enfermeiro/a encontrado/a para {nome}: "
                            f"{body.get('nome_enfermeiro', '?')}.", "YELLOW")
                        # Sem break para ler todos e limpar a mailbox

                if not nurse_proposal:
                    log(agent._coord_name,
                        f"[INTERNAMENTO] Sem enfermeiros disponíveis para {nome}; mantido em fila.", "RED")
                    return False

            # ── Phase 3: Accept both room and nurse ──
            duration = random.randint(INTERNAMENTO_MIN_SECONDS, INTERNAMENTO_MAX_SECONDS)

            acc_room = Message(to=room_proposal["sala_jid"])
            acc_room.set_metadata("performative", "accept-proposal")
            acc_room.body = json.dumps({"doente_jid": doente_jid, "nome": nome, "tipo": "Internamento"})
            acc_room.thread = doente_jid
            await self.send(acc_room)

            nurse_name = "?"
            if nurse_proposal:
                nurse_name = nurse_proposal.get("nome_enfermeiro", "?")
                acc_nurse = Message(to=nurse_proposal["enfermeiro_jid"])
                acc_nurse.set_metadata("performative", "accept-proposal")
                acc_nurse.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "sala_jid": room_proposal["sala_jid"],
                    "duration": duration,
                })
                acc_nurse.thread = doente_jid + "_nurse"
                await self.send(acc_nurse)

            # Notify requesting doctor (freed immediately)
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

            log(agent._coord_name,
                f"[INTERNAMENTO] {nome} admitido em {room_proposal.get('nome_sala', '?')} "
                f"com {nurse_name} por {duration}s.", "YELLOW")
            return True

    async def setup(self):
        log(self._coord_name, "Coordenador de Internamento iniciado.", "YELLOW")
        self.add_behaviour(self.InternamentoBehaviour())
