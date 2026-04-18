import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *

class CoordenadorUrgencias(Agent):


    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.pending_urgencies = []

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

        async def handle_out_of_band_message(self, msg):
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "triaged_patient":
                data = json.loads(msg.body)
                self.agent.pending_urgencies.append(data)
                self.agent.pending_urgencies.sort(key=lambda p: p.get("prioridade", URGENT_PRIORITY_MAX))
                await self.publish_waitlist()
                log(COORD_URG,
                    f"[FILA-URG] Pedido triado enfileirado fora de banda: {data.get('nome', '?')} "
                    f"(prioridade={data.get('prioridade', '?')})",
                    "YELLOW")
                return

        async def publish_waitlist(self):
            msg = Message(to=jid(SUPERVISOR))
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "waitlist_update")
            msg.body = json.dumps({
                "queue": "emergency",
                "patients": self.agent.get_emergency_waitlist(),
                "by_specialty": self.agent.get_emergency_waitlist_by_specialty(),
            })
            await self.send(msg)

            gate = Message(to=jid(COORD_CONS))
            gate.set_metadata("performative", "inform")
            gate.set_metadata("type", "routine_gate")
            gate.body = json.dumps({
                "hold": len(self.agent.pending_urgencies) > 0
            })
            await self.send(gate)

        async def dispatch_next_emergency(self):
            if not self.agent.pending_urgencies:
                return

            patient = self.agent.pending_urgencies[0]
            allocated = await self.run_emergency_contract_net(patient)
            if allocated:
                self.agent.pending_urgencies.pop(0)
                await self.publish_waitlist()


        async def run(self):
            msg = await self.receive(timeout=COORDINATOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                if self.agent.pending_urgencies:
                    log(
                        COORD_URG,
                        "[RETRY] Sem eventos novos; a re-tentar despacho da urgência pendente.",
                        "YELLOW",
                    )
                    await self.dispatch_next_emergency()
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            # ---- Pedido triado (da Triagem) ----
            if performative == "request" and msg_type == "triaged_patient":
                data = json.loads(msg.body)
                log(COORD_URG,
                    f"[PEDIDO] Pedido triado de emergência recebido: {data['nome']} "
                    f"(prioridade={data['prioridade']})", "RED")
                self.agent.pending_urgencies.append(data)
                self.agent.pending_urgencies.sort(key=lambda p: p.get("prioridade", URGENT_PRIORITY_MAX))
                await self.publish_waitlist()
                log(COORD_URG,
                    "[A AGUARDAR] A aguardar confirmação de libertação de recursos do Supervisor...",
                    "YELLOW")

            # ---- Recursos libertados (do Supervisor) ----
            elif performative == "inform" and msg_type == "resources_freed":
                log(COORD_URG,
                    "[NOTIFICAÇÃO] Confirmação de preempção recebida do Supervisor.",
                    "GREEN")
                if self.agent.pending_urgencies:
                    await self.dispatch_next_emergency()

        # -----------------------------------------------------------------
        # CONTRACT-NET DE EMERGÊNCIA
        # -----------------------------------------------------------------
        async def run_emergency_contract_net(self, patient_data):
            """Contract-Net de emergência para alocação imediata."""
            nome = patient_data["nome"]
            doente_jid = patient_data["doente_jid"]
            requested_specialty = patient_data.get("especialidade")

            medicos_candidatos = [
                m_jid
                for m_jid in MEDICOS
                if AGENT_REGISTRY.get(m_jid, {}).get("zone") == "normal"
                and AGENT_REGISTRY.get(m_jid, {}).get("specialty") == requested_specialty
            ]

            if not medicos_candidatos:
                log(
                    COORD_URG,
                    f"[CFP-FILTER] Sem médicos compatíveis (esp={requested_specialty}) para {nome}.",
                    "YELLOW",
                )
                return False

            log(COORD_URG,
                f"[CONTRACT-NET] A iniciar negociação de EMERGÊNCIA para {nome}...",
                "RED")

            # 1) CFP apenas a médicos compatíveis
            for m_jid in medicos_candidatos:
                cfp = Message(to=m_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "emergency_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_URG,
                    f"[CFP] CFP de Emergência enviado para {m_jid}", "RED")

            # 2) CFP a Salas
            for s_jid in SALAS:
                cfp = Message(to=s_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "emergency_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_URG,
                    f"[CFP] CFP de Emergência enviado para {s_jid}", "RED")

            # 3) Recolher propostas
            await asyncio.sleep(CONTRACT_NET_RESPONSE_WAIT_SECONDS)

            medico_proposta = None
            sala_proposta = None
            expected_replies = len(medicos_candidatos) + len(SALAS)

            for _ in range(expected_replies):
                reply = await self.receive(timeout=COORDINATOR_PROPOSAL_TIMEOUT_SECONDS)
                if reply is None:
                    continue

                if reply.thread != doente_jid:
                    await self.handle_out_of_band_message(reply)
                    continue

                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)

                if perf == "propose":
                    if "medico_jid" in body:
                        medico_proposta = body
                        log(COORD_URG,
                            f"[PROPOSTA] Proposta recebida de: {body['nome_medico']}",
                            "GREEN")
                    elif "sala_jid" in body:
                        sala_proposta = body
                        log(COORD_URG,
                            f"[PROPOSTA] Proposta recebida de: {body['nome_sala']}",
                            "GREEN")
                elif perf == "reject-proposal":
                    log(COORD_URG,
                        f"[PROPOSTA] Proposta rejeitada: {body.get('motivo', '?')}",
                        "YELLOW")

            # 4) Adjudicar
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

                log(COORD_URG,
                    f"[ALOCAÇÃO] EMERGÊNCIA AGENDADA: {nome} → "
                    f"Médico={medico_proposta['nome_medico']}, "
                    f"Sala={sala_proposta['nome_sala']}", "BOLD")
                return True
            else:
                log(COORD_URG,
                    f"[FALHA CRÍTICA] Impossível alocar recursos de emergência para {nome}! "
                    f"Recursos continuam indisponíveis.", "RED")
                return False

    async def setup(self):
        log(COORD_URG, "Coordenador de Urgências iniciado.", "RED")
        # SEM TEMPLATE — aceita todas as mensagens, filtragem manual no run()
        self.add_behaviour(self.EmergencyCoordinatorBehaviour())
