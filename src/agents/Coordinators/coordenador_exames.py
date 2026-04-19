import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *

class CoordenadorExames(Agent):

    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.pending_exam_requests = []
        self.pending_exam_patient_ids = set()

    def enqueue_exam_request(self, data):
        doente_jid = data.get("doente_jid")
        if not doente_jid:
            return False
        if doente_jid in self.pending_exam_patient_ids:
            return False
        self.pending_exam_requests.append(data)
        self.pending_exam_patient_ids.add(doente_jid)
        return True


    class ExamCoordinatorBehaviour(CyclicBehaviour):

        async def handle_out_of_band_message(self, msg):
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "exam_request":
                data = json.loads(msg.body)
                if self.agent.enqueue_exam_request(data):
                    log(COORD_EXAM,
                        f"[FILA-EXAME] Pedido enfileirado fora de banda: {data.get('nome', '?')}",
                        "YELLOW")
                else:
                    log(COORD_EXAM,
                        f"[FILA-EXAME] Pedido duplicado ignorado: {data.get('nome', '?')}",
                        "YELLOW")

        async def dispatch_next_exam(self):
            if not self.agent.pending_exam_requests:
                return False

            patient = self.agent.pending_exam_requests[0]
            allocated = await self.run_exam_contract_net(patient)
            if allocated:
                removed = self.agent.pending_exam_requests.pop(0)
                self.agent.pending_exam_patient_ids.discard(removed.get("doente_jid"))
                return True
            return False

        async def dispatch_exam_batch(self, max_dispatches=DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.pending_exam_requests:
                allocated = await self.dispatch_next_exam()
                if not allocated:
                    break
                dispatched += 1

        def get_exam_candidates(self, exam_specialty):
            equipamentos = [
                eq_jid
                for eq_jid in EQUIPAMENTOS
                if AGENT_REGISTRY.get(eq_jid, {}).get("specialty") == exam_specialty
            ]
            medicos = [
                m_jid
                for m_jid in MEDICOS
                if AGENT_REGISTRY.get(m_jid, {}).get("zone") == "exam"
                and AGENT_REGISTRY.get(m_jid, {}).get("specialty") == exam_specialty
            ]
            return equipamentos, medicos

        async def run(self):
            msg = await self.receive(timeout=COORDINATOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                if self.agent.pending_exam_requests:
                    await self.dispatch_exam_batch()
                return

            performative = msg.get_metadata("performative")
            msg_type     = msg.get_metadata("type")

            # ---- Pedido de exame ----
            if performative == "request" and msg_type == "exam_request":
                data = json.loads(msg.body)
                log(COORD_EXAM,
                    f"[PEDIDO] Pedido de diagnóstico MCDT recebido para: {data.get('nome', '?')}",
                    "CYAN")
                if self.agent.enqueue_exam_request(data):
                    await self.dispatch_exam_batch()
                else:
                    log(COORD_EXAM,
                        f"[FILA-EXAME] Pedido duplicado ignorado: {data.get('nome', '?')}",
                        "YELLOW")

            # Propostas chegam ao mesmo behaviour (sem template restritivo)
            # — tratadas dentro de run_exam_contract_net via receive().

        async def run_exam_contract_net(self, patient_data):
            """Contract-Net com equipamentos de exame."""
            nome       = patient_data.get("nome", "?")
            doente_jid = patient_data.get("doente_jid", "")
            exam_specialty = patient_data.get("especialidade", SPECIALTY_RX)
            equipamentos, medicos_exame = self.get_exam_candidates(exam_specialty)

            log(COORD_EXAM,
                f"[CONTRACT-NET] A iniciar negociação de DIAGNÓSTICO para {nome} (esp={exam_specialty})...",
                "CYAN",
            )

            if not equipamentos or not medicos_exame:
                log(
                    COORD_EXAM,
                    f"[ALLOCATION-FAILED] Sem recursos compatíveis para exame {exam_specialty} de {nome}.",
                    "RED",
                )
                return False

            # 1) CFP a todos os equipamentos
            for eq_jid in equipamentos:
                cfp = Message(to=eq_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "exam_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_EXAM, f"[CFP] CFP enviado para equipamento {eq_jid}", "CYAN")

            for m_jid in medicos_exame:
                cfp = Message(to=m_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "exam_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_EXAM, f"[CFP] CFP enviado para médico de exame {m_jid}", "CYAN")

            # 2) Recolher respostas com early-stopping e deadline de segurança.

            equipamento_propostas = []
            medico_propostas = []

            loop = asyncio.get_running_loop()
            deadline = loop.time() + CONTRACT_NET_RESPONSE_WAIT_SECONDS
            expected_replies = len(equipamentos) + len(medicos_exame)
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
                    await self.handle_out_of_band_message(reply)
                    continue

                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)

                if perf == "propose":
                    if "sala_jid" in body:
                        equipamento_propostas.append(body)
                        log(
                            COORD_EXAM,
                            f"[PROPOSTA] Proposta de equipamento: {body.get('nome_sala', '?')}",
                            "CYAN",
                        )
                    elif "medico_jid" in body:
                        medico_propostas.append(body)
                        log(
                            COORD_EXAM,
                            f"[PROPOSTA] Proposta de médico: {body.get('nome_medico', '?')}",
                            "CYAN",
                        )
                elif perf == "reject-proposal":
                    log(COORD_EXAM,
                        f"[PROPOSTA] Proposta rejeitada: {body.get('motivo', '?')}",
                        "YELLOW")

                if equipamento_propostas and medico_propostas:
                    log(
                        COORD_EXAM,
                        f"[CONTRACT-NET] Early-stop ativado para {nome}: par equipamento+médico encontrado.",
                        "CYAN",
                    )
                    break

            # 3) Adjudicar
            equipamento_proposta = equipamento_propostas[0] if equipamento_propostas else None
            medico_proposta = medico_propostas[0] if medico_propostas else None

            if equipamento_proposta and medico_proposta:
                acc_eq = Message(to=equipamento_proposta["sala_jid"])
                acc_eq.set_metadata("performative", "accept-proposal")
                acc_eq.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                })
                acc_eq.thread = doente_jid
                await self.send(acc_eq)

                acc_med = Message(to=medico_proposta["medico_jid"])
                acc_med.set_metadata("performative", "accept-proposal")
                acc_med.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "sala_jid": equipamento_proposta["sala_jid"],
                    "especialidade": exam_specialty,
                })
                acc_med.thread = doente_jid
                await self.send(acc_med)

                # Rejeitar os proponentes não selecionados.
                for proposta in equipamento_propostas:
                    sala_jid = proposta.get("sala_jid")
                    if not sala_jid or sala_jid == equipamento_proposta["sala_jid"]:
                        continue
                    rej = Message(to=sala_jid)
                    rej.set_metadata("performative", "reject-proposal")
                    rej.body = json.dumps({
                        "motivo": "Proposta não selecionada",
                        "doente_jid": doente_jid,
                    })
                    rej.thread = doente_jid
                    await self.send(rej)

                for proposta in medico_propostas:
                    medico_jid = proposta.get("medico_jid")
                    if not medico_jid or medico_jid == medico_proposta["medico_jid"]:
                        continue
                    rej = Message(to=medico_jid)
                    rej.set_metadata("performative", "reject-proposal")
                    rej.body = json.dumps({
                        "motivo": "Proposta não selecionada",
                        "doente_jid": doente_jid,
                    })
                    rej.thread = doente_jid
                    await self.send(rej)

                log(COORD_EXAM,
                    f"[ALOCAÇÃO] DIAGNÓSTICO AGENDADO: {nome} → "
                    f"Equipamento={equipamento_proposta.get('nome_sala', '?')}, "
                    f"Médico={medico_proposta.get('nome_medico', '?')}",
                    "BOLD")

                # NOTIFICAR SOLICITANTE (Médico)
                solicitante = patient_data.get("solicitante")
                if solicitante:
                    notif = Message(to=solicitante)
                    notif.set_metadata("performative", "inform")
                    notif.set_metadata("type", "allocation_confirmed")
                    notif.body = json.dumps({
                        "doente_jid": doente_jid,
                        "sala_jid": equipamento_proposta["sala_jid"],
                        "medico_jid": medico_proposta["medico_jid"],
                        "especialidade": exam_specialty,
                        "procedure": "exam"
                    })
                    await self.send(notif)
                return True
            else:
                log(COORD_EXAM,
                    f"[ALLOCATION-FAILED] Sem alocação completa de exame para {nome} (esp={exam_specialty}).",
                    "RED")
                return False

    async def setup(self):
        log(COORD_EXAM, "Coordenador de Exames iniciado.", "CYAN")
        # SEM TEMPLATE — filtragem manual no run()
        self.add_behaviour(self.ExamCoordinatorBehaviour())
