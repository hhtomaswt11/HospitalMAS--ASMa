import asyncio
import json
import random
import time

from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.agents.Coordinators.coordenador_base import CoordenadorBase
from src.config import *


class CoordenadorInternamento(CoordenadorBase):
    """Coordena internamento com fila, backoff, limite de tentativas e waitlist no dashboard."""

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, hospital_config=hospital_config, **kwargs)
        cfg = self.hospital_config
        self._internamento = cfg["internamento"]
        self._enfermeiros = cfg.get("enfermeiros", [])

    class InternamentoBehaviour(CyclicBehaviour):
        async def handle_out_of_band_message(self, msg):
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")
            if performative == "request" and msg_type == "internment_request":
                extra = json.loads(msg.body)
                if self.agent.enqueue(extra):
                    await self.publish_waitlist()
                    log(self.agent._coord_name,
                        f"[INTERNAMENTO] Pedido enfileirado fora de banda: {extra.get('nome', '?')}",
                        "YELLOW")
            elif performative == "inform" and msg_type == "internment_finished":
                data = json.loads(msg.body)
                log(self.agent._coord_name,
                    f"[INTERNAMENTO] Alta concluída fora de banda para {data.get('nome', '?')}",
                    "GREEN")
                await self.dispatch_internment_batch()
            else:
                return

        async def run(self):
            msg = await self.receive(timeout=COORDINATOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                if self.agent.pending_requests:
                    await self.dispatch_internment_batch()
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "internment_request":
                data = json.loads(msg.body)
                if self.agent.enqueue(data):
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
            else:
                await self.handle_out_of_band_message(msg)

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
                        "retry_count": p.get("_retry_count", 0),
                        "next_retry_at": p.get("_next_retry_at", 0.0),
                    }
                    for p in self.agent.pending_requests
                ],
            })
            await self.send(msg)

        async def notify_internment_failure(self, patient_data, reason):
            doente_jid = patient_data.get("doente_jid")
            nome = patient_data.get("nome", "?")
            solicitante = patient_data.get("solicitante")

            if solicitante:
                notif = Message(to=solicitante)
                notif.set_metadata("performative", "inform")
                notif.set_metadata("type", "internment_failed")
                notif.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "motivo": reason,
                    "procedure": "internment",
                })
                notif.thread = doente_jid
                await self.send(notif)

            if doente_jid:
                discharge = Message(to=doente_jid)
                discharge.set_metadata("performative", "inform")
                discharge.set_metadata("type", "discharge")
                discharge.body = json.dumps({"estado": "Alta/observacao por internamento indisponivel"})
                discharge.thread = doente_jid
                await self.send(discharge)

            log(self.agent._coord_name,
                f"[INTERNAMENTO-FALHADO] {nome}: {reason}. Doente/solicitante notificados.",
                "RED")

        async def dispatch_next_internment(self):
            idx = self.agent.get_ready_index()
            if idx is None:
                return False

            patient = self.agent.pending_requests[idx]
            allocated = await self.run_internment_contract_net(patient)
            if allocated:
                removed = self.agent.pending_requests.pop(idx)
                self.agent.pending_patient_ids.discard(removed.get("doente_jid"))
                await self.publish_waitlist()
                return True

            delay, retries, failed = self.agent.schedule_retry(
                patient, INTERNMENT_MAX_RETRIES, INTERNMENT_RETRY_BASE_SECONDS, INTERNMENT_RETRY_MAX_SECONDS)
            if failed:
                removed = self.agent.pending_requests.pop(idx)
                self.agent.pending_patient_ids.discard(removed.get("doente_jid"))
                await self.notify_internment_failure(
                    removed,
                    f"sem quarto/enfermeiro disponível após {INTERNMENT_MAX_RETRIES} tentativas",
                )
                await self.agent.notify_metric_abandoned(
                    self,
                    doente_jid=removed.get("doente_jid", ""),
                    nome=removed.get("nome", "?"),
                    tipo=removed.get("tipo_original", removed.get("tipo", "urgencia")),
                    motivo=f"internamento: sem quarto/enfermeiro após {INTERNMENT_MAX_RETRIES} tentativas",
                    procedimento="internamento",
                )
                await self.publish_waitlist()
                return True

            await self.publish_waitlist()
            log(self.agent._coord_name,
                f"[INTERNAMENTO] Re-tentativa para {patient.get('nome', '?')} adiada {delay:.0f}s "
                f"(tentativa={retries}/{INTERNMENT_MAX_RETRIES}).",
                "YELLOW")
            return False

        async def dispatch_internment_batch(self, max_dispatches=DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.pending_requests:
                progressed = await self.dispatch_next_internment()
                if not progressed:
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

            room_propostas = []
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
                    await self.handle_out_of_band_message(reply)
                    continue
                received_replies += 1
                perf = reply.get_metadata("performative")
                try:
                    body = json.loads(reply.body) if reply.body else {}
                except Exception:
                    body = {}
                if perf == "propose" and "sala_jid" in body:
                    room_propostas.append(body)
                    log(agent._coord_name,
                        f"[CONTRACT-NET] Quarto candidato para {nome}: {body.get('nome_sala', '?')} "
                        f"(score={body.get('score', 999)}).", "YELLOW")

            room_proposal = min(room_propostas, key=lambda p: p.get("score", 999)) if room_propostas else None
            if not room_proposal:
                log(agent._coord_name, f"[INTERNAMENTO] Sem quartos disponíveis para {nome}; mantido em fila.", "RED")
                return False

            # ── Phase 2: CFP to all nurses ──
            nurse_propostas = []
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
                        await self.handle_out_of_band_message(reply)
                        continue
                    received_n += 1
                    perf = reply.get_metadata("performative")
                    try:
                        body = json.loads(reply.body) if reply.body else {}
                    except Exception:
                        body = {}
                    if perf == "propose" and "enfermeiro_jid" in body:
                        nurse_propostas.append(body)
                        log(agent._coord_name,
                            f"[CONTRACT-NET] Enfermeiro/a candidato/a para {nome}: "
                            f"{body.get('nome_enfermeiro', '?')} (score={body.get('score', 999)}).", "YELLOW")

                nurse_proposal = min(nurse_propostas, key=lambda p: p.get("score", 999)) if nurse_propostas else None
                if not nurse_proposal:
                    await agent.reject_all(self, room_propostas, "sala_jid", doente_jid, "Sem enfermeiro disponível")
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
            await agent.reject_unselected(self, room_propostas, room_proposal["sala_jid"], "sala_jid", doente_jid, "Proposta não selecionada")

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
                await agent.reject_unselected(self, nurse_propostas, nurse_proposal["enfermeiro_jid"], "enfermeiro_jid", doente_jid + "_nurse", "Proposta não selecionada")

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
                notif.thread = doente_jid
                await self.send(notif)

            if doente_jid:
                notif_doente = Message(to=doente_jid)
                notif_doente.set_metadata("performative", "inform")
                notif_doente.set_metadata("type", "allocation_confirmed")
                notif_doente.body = json.dumps({
                    "procedure": "internment",
                    "sala_jid": room_proposal["sala_jid"],
                    "enfermeiro_jid": nurse_proposal.get("enfermeiro_jid") if nurse_proposal else None,
                    "duration": duration
                })
                notif_doente.thread = doente_jid
                await self.send(notif_doente)

            log(agent._coord_name,
                f"[INTERNAMENTO] {nome} admitido em {room_proposal.get('nome_sala', '?')} "
                f"com {nurse_name} por {duration}s.", "YELLOW")
            return True

    async def setup(self):
        log(self._coord_name, "Coordenador de Internamento iniciado.", "YELLOW")
        self.add_behaviour(self.InternamentoBehaviour())
