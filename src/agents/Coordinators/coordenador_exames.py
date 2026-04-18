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


    class ExamCoordinatorBehaviour(CyclicBehaviour):

        async def handle_out_of_band_message(self, msg):
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "exam_request":
                data = json.loads(msg.body)
                self.agent.pending_exam_requests.append(data)
                log(COORD_EXAM,
                    f"[FILA-EXAME] Pedido enfileirado fora de banda: {data.get('nome', '?')}",
                    "YELLOW")

        async def dispatch_next_exam(self):
            if not self.agent.pending_exam_requests:
                return

            patient = self.agent.pending_exam_requests[0]
            allocated = await self.run_exam_contract_net(patient)
            if allocated:
                self.agent.pending_exam_requests.pop(0)

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
                    await self.dispatch_next_exam()
                return

            performative = msg.get_metadata("performative")
            msg_type     = msg.get_metadata("type")

            # ---- Pedido de exame ----
            if performative == "request" and msg_type == "exam_request":
                data = json.loads(msg.body)
                log(COORD_EXAM,
                    f"[PEDIDO] Pedido de diagnóstico MCDT recebido para: {data.get('nome', '?')}",
                    "CYAN")
                self.agent.pending_exam_requests.append(data)
                await self.dispatch_next_exam()

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
                return

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

            # 2) Aguardar respostas
            await asyncio.sleep(CONTRACT_NET_RESPONSE_WAIT_SECONDS)

            equipamento_proposta = None
            medico_proposta = None

            for _ in range(len(equipamentos) + len(medicos_exame)):
                reply = await self.receive(timeout=COORDINATOR_PROPOSAL_TIMEOUT_SECONDS)
                if reply is None:
                    continue

                if reply.thread != doente_jid:
                    await self.handle_out_of_band_message(reply)
                    continue

                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)

                if perf == "propose":
                    if "sala_jid" in body:
                        equipamento_proposta = body
                        log(
                            COORD_EXAM,
                            f"[PROPOSTA] Proposta de equipamento: {body.get('nome_sala', '?')}",
                            "CYAN",
                        )
                    elif "medico_jid" in body:
                        medico_proposta = body
                        log(
                            COORD_EXAM,
                            f"[PROPOSTA] Proposta de médico: {body.get('nome_medico', '?')}",
                            "CYAN",
                        )
                elif perf == "reject-proposal":
                    log(COORD_EXAM,
                        f"[PROPOSTA] Proposta rejeitada: {body.get('motivo', '?')}",
                        "YELLOW")

            # 3) Adjudicar
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
            else:
                log(COORD_EXAM,
                    f"[ALLOCATION-FAILED] Sem alocação completa de exame para {nome} (esp={exam_specialty}).",
                    "RED")

    async def setup(self):
        log(COORD_EXAM, "Coordenador de Exames iniciado.", "CYAN")
        # SEM TEMPLATE — filtragem manual no run()
        self.add_behaviour(self.ExamCoordinatorBehaviour())
