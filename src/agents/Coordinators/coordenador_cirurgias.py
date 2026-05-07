import asyncio
import json
import time

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *


class CoordenadorCirurgias(Agent):
    """Coordena cirurgias com fila, backoff e resultado explícito para o médico solicitante."""

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        cfg = hospital_config or H1_CONFIG
        self._medicos = cfg["medicos"]
        self._blocos = cfg["blocos"]
        self._coord_name = str(agent_jid).split("@")[0]

        self.pending_surgery_requests = []
        self.pending_surgery_patient_ids = set()

    def enqueue_surgery_request(self, data):
        doente_jid = data.get("doente_jid")
        if not doente_jid:
            return False
        if doente_jid in self.pending_surgery_patient_ids:
            return False
        data.setdefault("_retry_count", 0)
        data.setdefault("_next_retry_at", 0.0)
        self.pending_surgery_requests.append(data)
        self.pending_surgery_patient_ids.add(doente_jid)
        return True

    def get_ready_surgery_index(self):
        now = time.monotonic()
        for idx, request in enumerate(self.pending_surgery_requests):
            if float(request.get("_next_retry_at", 0.0)) <= now:
                return idx
        return None

    def schedule_surgery_retry(self, data):
        retries = int(data.get("_retry_count", 0)) + 1
        data["_retry_count"] = retries
        if retries >= SURGERY_MAX_RETRIES:
            return None, retries, True
        delay = min(SURGERY_RETRY_BASE_SECONDS * (2 ** (retries - 1)), SURGERY_RETRY_MAX_SECONDS)
        data["_next_retry_at"] = time.monotonic() + delay
        return delay, retries, False

    class SurgeryCoordinatorBehaviour(CyclicBehaviour):

        async def handle_out_of_band_message(self, msg):
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")
            if performative == "request" and msg_type == "surgery_request":
                data = json.loads(msg.body)
                if self.agent.enqueue_surgery_request(data):
                    log(self.agent._coord_name,
                        f"[FILA-CIR] Pedido enfileirado fora de banda: {data.get('nome', '?')}", "YELLOW")
                else:
                    log(self.agent._coord_name,
                        f"[FILA-CIR] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")
            else:
                return

        async def notify_surgery_failure(self, patient_data, reason):
            doente_jid = patient_data.get("doente_jid")
            nome = patient_data.get("nome", "?")
            solicitante = patient_data.get("solicitante")
            payload = {
                "doente_jid": doente_jid,
                "nome": nome,
                "estado": "cirurgia_falhada",
                "motivo": reason,
            }
            if solicitante:
                result = Message(to=solicitante)
                result.set_metadata("performative", "inform")
                result.set_metadata("type", "surgery_result")
                result.body = json.dumps(payload)
                result.thread = doente_jid
                await self.send(result)
            elif doente_jid:
                discharge = Message(to=doente_jid)
                discharge.set_metadata("performative", "inform")
                discharge.set_metadata("type", "discharge")
                discharge.body = json.dumps({"estado": "Alta/observacao por cirurgia indisponivel"})
                discharge.thread = doente_jid
                await self.send(discharge)
            log(self.agent._coord_name,
                f"[CIRURGIA-FALHADA] {nome}: {reason}. Solicitante notificado.",
                "RED")

        async def dispatch_next_surgery(self):
            idx = self.agent.get_ready_surgery_index()
            if idx is None:
                return False

            patient = self.agent.pending_surgery_requests[idx]
            allocated = await self.run_surgery_contract_net(patient)
            if allocated:
                removed = self.agent.pending_surgery_requests.pop(idx)
                self.agent.pending_surgery_patient_ids.discard(removed.get("doente_jid"))
                return True

            delay, retries, failed = self.agent.schedule_surgery_retry(patient)
            if failed:
                removed = self.agent.pending_surgery_requests.pop(idx)
                self.agent.pending_surgery_patient_ids.discard(removed.get("doente_jid"))
                await self.notify_surgery_failure(
                    removed,
                    f"sem bloco/cirurgião disponível após {SURGERY_MAX_RETRIES} tentativas",
                )
                return True

            log(self.agent._coord_name,
                f"[FILA-CIR] Re-tentativa para {patient.get('nome', '?')} adiada {delay:.0f}s "
                f"(tentativa={retries}/{SURGERY_MAX_RETRIES}).",
                "YELLOW")
            return False

        async def dispatch_surgery_batch(self, max_dispatches=DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.pending_surgery_requests:
                progressed = await self.dispatch_next_surgery()
                if not progressed:
                    break
                dispatched += 1

        async def run(self):
            msg = await self.receive(timeout=COORDINATOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                if self.agent.pending_surgery_requests:
                    await self.dispatch_surgery_batch()
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "surgery_request":
                data = json.loads(msg.body)
                log(self.agent._coord_name,
                    f"[PEDIDO] Pedido de cirurgia recebido para: {data.get('nome', '?')}", "MAGENTA")
                if self.agent.enqueue_surgery_request(data):
                    await self.dispatch_surgery_batch()
                else:
                    log(self.agent._coord_name,
                        f"[FILA-CIR] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")
            else:
                await self.handle_out_of_band_message(msg)

        async def reject_unselected(self, propostas, selected_jid, jid_key, doente_jid, motivo):
            for proposta in propostas:
                target = proposta.get(jid_key)
                if not target or target == selected_jid:
                    continue
                rej = Message(to=target)
                rej.set_metadata("performative", "reject-proposal")
                rej.body = json.dumps({"motivo": motivo, "doente_jid": doente_jid})
                rej.thread = doente_jid
                await self.send(rej)

        async def reject_all(self, propostas, jid_key, doente_jid, motivo):
            await self.reject_unselected(propostas, None, jid_key, doente_jid, motivo)

        async def run_surgery_contract_net(self, patient_data):
            agent = self.agent
            nome = patient_data.get("nome", "?")
            doente_jid = patient_data.get("doente_jid", "")

            medicos_cirurgia = [
                m_jid for m_jid in agent._medicos
                if AGENT_REGISTRY.get(m_jid, {}).get("specialty") == SPECIALTY_CIRURGIA
            ]

            log(agent._coord_name,
                f"[CONTRACT-NET] A iniciar negociação CIRÚRGICA para {nome}...", "MAGENTA")

            for b_jid in agent._blocos:
                cfp = Message(to=b_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "surgery_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

            for m_jid in medicos_cirurgia:
                cfp = Message(to=m_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "surgery_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

            bloco_propostas = []
            medico_propostas = []
            expected_replies = len(agent._blocos) + len(medicos_cirurgia)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + CONTRACT_NET_RESPONSE_WAIT_SECONDS
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
                if perf == "propose":
                    if "sala_jid" in body:
                        bloco_propostas.append(body)
                    elif "medico_jid" in body:
                        medico_propostas.append(body)

            bloco_proposta = min(bloco_propostas, key=lambda p: p.get("score", 999)) if bloco_propostas else None
            medico_proposta = min(medico_propostas, key=lambda p: p.get("score", 999)) if medico_propostas else None

            if bloco_proposta and medico_proposta:
                acc_b = Message(to=bloco_proposta["sala_jid"])
                acc_b.set_metadata("performative", "accept-proposal")
                acc_b.body = json.dumps({"doente_jid": doente_jid, "nome": nome})
                acc_b.thread = doente_jid
                await self.send(acc_b)

                acc_m = Message(to=medico_proposta["medico_jid"])
                acc_m.set_metadata("performative", "accept-proposal")
                acc_m.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "sala_jid": bloco_proposta["sala_jid"],
                    "solicitante": patient_data.get("solicitante"),
                    "tipo_original": patient_data.get("tipo_original", patient_data.get("tipo")),
                })
                acc_m.thread = doente_jid
                await self.send(acc_m)

                await self.reject_unselected(bloco_propostas, bloco_proposta["sala_jid"], "sala_jid", doente_jid, "Proposta não selecionada")
                await self.reject_unselected(medico_propostas, medico_proposta["medico_jid"], "medico_jid", doente_jid, "Proposta não selecionada")

                log(agent._coord_name,
                    f"[ALOCAÇÃO] CIRURGIA AGENDADA: {nome} → "
                    f"Bloco={bloco_proposta.get('nome_sala', '?')}, "
                    f"Cirurgião={medico_proposta.get('nome_medico', '?')}", "BOLD")

                solicitante = patient_data.get("solicitante")
                if solicitante:
                    notif = Message(to=solicitante)
                    notif.set_metadata("performative", "inform")
                    notif.set_metadata("type", "allocation_confirmed")
                    notif.body = json.dumps({
                        "doente_jid": doente_jid,
                        "sala_jid": bloco_proposta["sala_jid"],
                        "procedure": "surgery"
                    })
                    notif.thread = doente_jid
                    await self.send(notif)
                return True

            await self.reject_all(bloco_propostas, "sala_jid", doente_jid, "Sem par bloco/cirurgião completo")
            await self.reject_all(medico_propostas, "medico_jid", doente_jid, "Sem par bloco/cirurgião completo")
            log(agent._coord_name,
                f"[ALLOCATION-FAILED] No valid surgical resources available for {nome}.", "RED")
            return False

    async def setup(self):
        log(self._coord_name, "Coordenador de Cirurgias iniciado.", "MAGENTA")
        self.add_behaviour(self.SurgeryCoordinatorBehaviour())
