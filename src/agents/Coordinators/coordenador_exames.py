import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *


class CoordenadorExames(Agent):

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        cfg = hospital_config or H1_CONFIG
        self.hospital_config = cfg
        self._medicos = cfg["medicos"]
        self._equipamentos = cfg["equipamentos"]
        self._equipamentos_specialty = cfg["equipamentos_specialty"]
        self._coord_name = str(agent_jid).split("@")[0]

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
                    log(self.agent._coord_name,
                        f"[FILA-EXAME] Pedido enfileirado fora de banda: {data.get('nome', '?')}", "YELLOW")
                else:
                    log(self.agent._coord_name,
                        f"[FILA-EXAME] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")

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
                eq_jid for eq_jid in self.agent._equipamentos
                if self.agent._equipamentos_specialty.get(eq_jid) == exam_specialty
            ]
            medicos = [
                m_jid for m_jid in self.agent._medicos
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
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "exam_request":
                data = json.loads(msg.body)
                log(self.agent._coord_name,
                    f"[PEDIDO] Pedido de diagnóstico MCDT recebido para: {data.get('nome', '?')}", "CYAN")
                if self.agent.enqueue_exam_request(data):
                    await self.dispatch_exam_batch()
                else:
                    log(self.agent._coord_name,
                        f"[FILA-EXAME] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")

        async def run_exam_contract_net(self, patient_data):
            agent = self.agent
            nome = patient_data.get("nome", "?")
            doente_jid = patient_data.get("doente_jid", "")
            exam_specialty = patient_data.get("especialidade", SPECIALTY_RX)
            equipamentos, medicos_exame = self.get_exam_candidates(exam_specialty)

            log(agent._coord_name,
                f"[CONTRACT-NET] A iniciar negociação de DIAGNÓSTICO para {nome} (esp={exam_specialty})...",
                "CYAN")

            if not equipamentos or not medicos_exame:
                log(agent._coord_name,
                    f"[ALLOCATION-FAILED] Sem recursos compatíveis para exame {exam_specialty} de {nome}.",
                    "RED")
                return False

            for eq_jid in equipamentos:
                cfp = Message(to=eq_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "exam_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

            for m_jid in medicos_exame:
                cfp = Message(to=m_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "exam_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

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
                if reply.thread != doente_jid:
                    await self.handle_out_of_band_message(reply)
                    continue
                received_replies += 1
                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)
                if perf == "propose":
                    if "sala_jid" in body:
                        equipamento_propostas.append(body)
                    elif "medico_jid" in body:
                        medico_propostas.append(body)


            equipamento_proposta = equipamento_propostas[0] if equipamento_propostas else None
            medico_proposta = medico_propostas[0] if medico_propostas else None

            if equipamento_proposta and medico_proposta:
                acc_eq = Message(to=equipamento_proposta["sala_jid"])
                acc_eq.set_metadata("performative", "accept-proposal")
                acc_eq.body = json.dumps({"doente_jid": doente_jid, "nome": nome})
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

                for proposta in equipamento_propostas:
                    s_jid = proposta.get("sala_jid")
                    if not s_jid or s_jid == equipamento_proposta["sala_jid"]:
                        continue
                    rej = Message(to=s_jid)
                    rej.set_metadata("performative", "reject-proposal")
                    rej.body = json.dumps({"motivo": "Proposta não selecionada", "doente_jid": doente_jid})
                    rej.thread = doente_jid
                    await self.send(rej)

                for proposta in medico_propostas:
                    m_jid = proposta.get("medico_jid")
                    if not m_jid or m_jid == medico_proposta["medico_jid"]:
                        continue
                    rej = Message(to=m_jid)
                    rej.set_metadata("performative", "reject-proposal")
                    rej.body = json.dumps({"motivo": "Proposta não selecionada", "doente_jid": doente_jid})
                    rej.thread = doente_jid
                    await self.send(rej)

                log(agent._coord_name,
                    f"[ALOCAÇÃO] DIAGNÓSTICO AGENDADO: {nome} → "
                    f"Equipamento={equipamento_proposta.get('nome_sala', '?')}, "
                    f"Médico={medico_proposta.get('nome_medico', '?')}", "BOLD")

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
                log(agent._coord_name,
                    f"[ALLOCATION-FAILED] Sem alocação completa de exame para {nome} (esp={exam_specialty}).",
                    "RED")
                return False

    async def setup(self):
        log(self._coord_name, "Coordenador de Exames iniciado.", "CYAN")
        self.add_behaviour(self.ExamCoordinatorBehaviour())
