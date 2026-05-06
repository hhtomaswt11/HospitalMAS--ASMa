import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *


class CoordenadorUrgencias(Agent):

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        cfg = hospital_config or H1_CONFIG
        self.hospital_config = cfg
        self._supervisor = cfg["supervisor"]
        self._medicos = cfg["medicos"]
        self._salas = cfg["salas"]
        self._coord_cons = cfg["coord_cons"]
        self._coord_name = str(agent_jid).split("@")[0]

        self.pending_urgencies = []
        self.pending_urgency_patient_ids = set()
        self.preemption_requested_patient_ids = set()

    def enqueue_urgency(self, data):
        doente_jid = data.get("doente_jid")
        if not doente_jid:
            return False
        if doente_jid in self.pending_urgency_patient_ids:
            return False
        self.pending_urgencies.append(data)
        self.pending_urgency_patient_ids.add(doente_jid)
        self.pending_urgencies.sort(key=lambda p: p.get("prioridade", URGENT_PRIORITY_MAX))
        return True

    def get_emergency_waitlist(self):
        return [
            {
                "doente_jid": p.get("doente_jid"),
                "nome": p.get("nome", "?"),
                "tipo": p.get("tipo", "Urgencia"),
                "prioridade": p.get("prioridade", 9),
                "especialidade": p.get("especialidade"),
            }
            for p in self.pending_urgencies
        ]

    def get_emergency_waitlist_by_specialty(self):
        by_specialty = {}
        for p in self.pending_urgencies:
            specialty = p.get("especialidade") or "sem_especialidade"
            by_specialty.setdefault(specialty, []).append({
                "doente_jid": p.get("doente_jid"),
                "nome": p.get("nome", "?"),
                "tipo": p.get("tipo", "Urgencia"),
                "prioridade": p.get("prioridade", 9),
                "especialidade": p.get("especialidade"),
            })
        return by_specialty

    class EmergencyCoordinatorBehaviour(CyclicBehaviour):

        async def send_routine_unblock(self):
            gate = Message(to=self.agent._coord_cons)
            gate.set_metadata("performative", "inform")
            gate.set_metadata("type", "routine_gate")
            gate.body = json.dumps({"blocked_specialties": [], "hold": False})
            await self.send(gate)

        async def handle_out_of_band_message(self, msg):
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")
            if performative == "request" and msg_type == "triaged_patient":
                data = json.loads(msg.body)
                if self.agent.enqueue_urgency(data):
                    await self.publish_waitlist()
                    log(self.agent._coord_name,
                        f"[FILA-URG] Pedido triado enfileirado fora de banda: {data.get('nome', '?')} "
                        f"(prioridade={data.get('prioridade', '?')})", "YELLOW")
                else:
                    log(self.agent._coord_name,
                        f"[FILA-URG] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")

        async def publish_waitlist(self):
            msg = Message(to=self.agent._supervisor)
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "waitlist_update")
            msg.body = json.dumps({
                "queue": "emergency",
                "patients": self.agent.get_emergency_waitlist(),
                "by_specialty": self.agent.get_emergency_waitlist_by_specialty(),
            })
            await self.send(msg)

            blocked_specialties = sorted({
                p.get("especialidade")
                for p in self.agent.pending_urgencies
                if p.get("especialidade")
            })
            gate = Message(to=self.agent._coord_cons)
            gate.set_metadata("performative", "inform")
            gate.set_metadata("type", "routine_gate")
            gate.body = json.dumps({
                "blocked_specialties": blocked_specialties,
                "hold": len(blocked_specialties) > 0,
            })
            await self.send(gate)

        async def dispatch_next_emergency(self):
            if not self.agent.pending_urgencies:
                return False
            patient = self.agent.pending_urgencies[0]
            allocated = await self.run_emergency_contract_net(patient)
            if allocated:
                removed = self.agent.pending_urgencies.pop(0)
                self.agent.pending_urgency_patient_ids.discard(removed.get("doente_jid"))
                self.agent.preemption_requested_patient_ids.discard(removed.get("doente_jid"))
                await self.publish_waitlist()
                if not self.agent.pending_urgencies:
                    await self.send_routine_unblock()
                return True
            else:
                doente_jid = patient.get("doente_jid")
                if doente_jid and doente_jid not in self.agent.preemption_requested_patient_ids:
                    preempt = Message(to=self.agent._supervisor)
                    preempt.set_metadata("performative", "request")
                    preempt.set_metadata("type", "preemption_request")
                    preempt.body = json.dumps({
                        "urgente_jid": doente_jid,
                        "urgente_nome": patient.get("nome", "?"),
                        "prioridade": patient.get("prioridade"),
                        "especialidade": patient.get("especialidade"),
                    })
                    preempt.thread = doente_jid
                    await self.send(preempt)
                    self.agent.preemption_requested_patient_ids.add(doente_jid)
                    log(self.agent._coord_name,
                        f"[PREEMPÇÃO] Pedido de preempção enviado ao Supervisor para {patient.get('nome', '?')}.",
                        "RED")
                return False

        async def dispatch_emergency_batch(self, max_dispatches=DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.pending_urgencies:
                allocated = await self.dispatch_next_emergency()
                if not allocated:
                    break
                dispatched += 1

        async def run(self):
            msg = await self.receive(timeout=COORDINATOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                if self.agent.pending_urgencies:
                    log(self.agent._coord_name,
                        "[RETRY] Sem eventos novos; a re-tentar despacho da urgência pendente.", "YELLOW")
                    await self.dispatch_emergency_batch()
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "triaged_patient":
                data = json.loads(msg.body)
                log(self.agent._coord_name,
                    f"[PEDIDO] Pedido triado de emergência recebido: {data['nome']} "
                    f"(prioridade={data['prioridade']})", "RED")
                if self.agent.enqueue_urgency(data):
                    await self.publish_waitlist()
                    await self.dispatch_emergency_batch()
                else:
                    log(self.agent._coord_name,
                        f"[FILA-URG] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")

            elif performative == "inform" and msg_type == "resources_freed":
                log(self.agent._coord_name,
                    "[NOTIFICAÇÃO] Confirmação de preempção recebida do Supervisor.", "GREEN")
                if self.agent.pending_urgencies:
                    head = self.agent.pending_urgencies[0].get("doente_jid")
                    if head:
                        self.agent.preemption_requested_patient_ids.discard(head)
                    await self.dispatch_emergency_batch()

        async def run_emergency_contract_net(self, patient_data):
            agent = self.agent
            nome = patient_data["nome"]
            doente_jid = patient_data["doente_jid"]
            requested_specialty = patient_data.get("especialidade")

            medicos_candidatos = [
                m_jid
                for m_jid in agent._medicos
                if AGENT_REGISTRY.get(m_jid, {}).get("zone") == "normal"
                and AGENT_REGISTRY.get(m_jid, {}).get("specialty") == requested_specialty
            ]

            if not medicos_candidatos:
                log(agent._coord_name,
                    f"[CFP-FILTER] Sem médicos compatíveis (esp={requested_specialty}) para {nome}.",
                    "YELLOW")
                return False

            log(agent._coord_name,
                f"[CONTRACT-NET] A iniciar negociação de EMERGÊNCIA para {nome}...", "RED")

            for m_jid in medicos_candidatos:
                cfp = Message(to=m_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "emergency_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

            for s_jid in agent._salas:
                cfp = Message(to=s_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "emergency_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

            medico_propostas = []
            sala_propostas = []
            expected_replies = len(medicos_candidatos) + len(agent._salas)

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
                    if "medico_jid" in body:
                        medico_propostas.append(body)
                    elif "sala_jid" in body:
                        sala_propostas.append(body)
                # Removido break precoce para processar todas as respostas

            medico_proposta = medico_propostas[0] if medico_propostas else None
            sala_proposta = sala_propostas[0] if sala_propostas else None

            if medico_proposta and sala_proposta:
                acc_m = Message(to=medico_proposta["medico_jid"])
                acc_m.set_metadata("performative", "accept-proposal")
                acc_m.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": patient_data.get("tipo", "Urgencia"),
                    "sala_jid": sala_proposta["sala_jid"]
                })
                acc_m.thread = doente_jid
                await self.send(acc_m)

                acc_s = Message(to=sala_proposta["sala_jid"])
                acc_s.set_metadata("performative", "accept-proposal")
                acc_s.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": patient_data.get("tipo", "Urgencia")
                })
                acc_s.thread = doente_jid
                await self.send(acc_s)

                for proposta in medico_propostas:
                    m_jid = proposta.get("medico_jid")
                    if not m_jid or m_jid == medico_proposta["medico_jid"]:
                        continue
                    rej = Message(to=m_jid)
                    rej.set_metadata("performative", "reject-proposal")
                    rej.body = json.dumps({"motivo": "Proposta não selecionada", "doente_jid": doente_jid})
                    rej.thread = doente_jid
                    await self.send(rej)

                for proposta in sala_propostas:
                    s_jid = proposta.get("sala_jid")
                    if not s_jid or s_jid == sala_proposta["sala_jid"]:
                        continue
                    rej = Message(to=s_jid)
                    rej.set_metadata("performative", "reject-proposal")
                    rej.body = json.dumps({"motivo": "Proposta não selecionada", "doente_jid": doente_jid})
                    rej.thread = doente_jid
                    await self.send(rej)

                log(agent._coord_name,
                    f"[ALOCAÇÃO] EMERGÊNCIA AGENDADA: {nome} → "
                    f"Médico={medico_proposta['nome_medico']}, "
                    f"Sala={sala_proposta['nome_sala']}", "BOLD")
                return True
            else:
                log(agent._coord_name,
                    f"[FALHA CRÍTICA] Impossível alocar recursos de emergência para {nome}! "
                    f"Recursos continuam indisponíveis.", "RED")
                return False

    async def setup(self):
        log(self._coord_name, "Coordenador de Urgências iniciado.", "RED")
        self.add_behaviour(self.EmergencyCoordinatorBehaviour())
