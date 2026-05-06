import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *


class CoordenadorCirurgias(Agent):

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
        self.pending_surgery_requests.append(data)
        self.pending_surgery_patient_ids.add(doente_jid)
        return True

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

        async def dispatch_next_surgery(self):
            if not self.agent.pending_surgery_requests:
                return False
            patient = self.agent.pending_surgery_requests[0]
            allocated = await self.run_surgery_contract_net(patient)
            if allocated:
                removed = self.agent.pending_surgery_requests.pop(0)
                self.agent.pending_surgery_patient_ids.discard(removed.get("doente_jid"))
                return True
            return False

        async def dispatch_surgery_batch(self, max_dispatches=DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.pending_surgery_requests:
                allocated = await self.dispatch_next_surgery()
                if not allocated:
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
                body = json.loads(reply.body)
                if perf == "propose":
                    if "sala_jid" in body:
                        bloco_propostas.append(body)
                    elif "medico_jid" in body:
                        medico_propostas.append(body)


            bloco_proposta = bloco_propostas[0] if bloco_propostas else None
            medico_proposta = medico_propostas[0] if medico_propostas else None

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
                })
                acc_m.thread = doente_jid
                await self.send(acc_m)

                for proposta in bloco_propostas:
                    s_jid = proposta.get("sala_jid")
                    if not s_jid or s_jid == bloco_proposta["sala_jid"]:
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
                    await self.send(notif)
                return True
            else:
                log(agent._coord_name,
                    f"[ALLOCATION-FAILED] No valid surgical resources available for {nome}.", "RED")
                return False

    async def setup(self):
        log(self._coord_name, "Coordenador de Cirurgias iniciado.", "MAGENTA")
        self.add_behaviour(self.SurgeryCoordinatorBehaviour())
