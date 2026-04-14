import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *

class CoordenadorConsultas(Agent):
    """
    Receives routine consultation requests and negotiates.
    """

    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.alocacoes = {}         # doente_jid → {medico, sala, nome}
        self.pending_requests = []  # fila de pedidos pendentes
        self.routine_hold = False   # bloqueia rotina quando há urgências em espera

    def get_routine_waitlist(self):
        return [
            {
                "doente_jid": p.get("doente_jid"),
                "nome": p.get("nome", "?"),
                "tipo": p.get("tipo", "Normal"),
                "prioridade": p.get("prioridade", 0),
            }
            for p in self.pending_requests
        ]

    class CoordinatorBehaviour(CyclicBehaviour):

        async def publish_waitlist(self):
            msg = Message(to=jid(SUPERVISOR))
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "waitlist_update")
            msg.body = json.dumps({
                "queue": "routine",
                "patients": self.agent.get_routine_waitlist(),
            })
            await self.send(msg)


        async def run(self):
            msg = await self.receive(timeout=5)
            if msg is None:
                if self.agent.pending_requests:
                    await self.dispatch_next_routine()
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            # ---- Pedido de consulta normal ----
            if performative == "request" and msg_type == "patient_request":
                data = json.loads(msg.body)
                log(COORD_CONS,
                    f"[PEDIDO] Pedido de consulta de rotina recebido: {data['nome']}",
                    "GREEN")
                self.agent.pending_requests.append(data)
                await self.publish_waitlist()
                log(COORD_CONS,
                    f"[FILA] Doente {data['nome']} adicionado à fila de rotina "
                    f"(posição={len(self.agent.pending_requests)}).",
                    "YELLOW")
                await self.dispatch_next_routine()

            # ---- Ordem de preemption do Supervisor ----
            elif performative == "request" and msg_type == "preemption_order":
                data = json.loads(msg.body)
                await self.handle_preemption(data)
                await self.dispatch_next_routine()

            elif performative == "inform" and msg_type == "routine_gate":
                data = json.loads(msg.body)
                self.agent.routine_hold = bool(data.get("hold", False))
                estado = "BLOQUEADA" if self.agent.routine_hold else "ATIVA"
                log(COORD_CONS, f"[PRIORIDADE] Via de rotina agora: {estado}", "YELLOW")
                if not self.agent.routine_hold:
                    await self.dispatch_next_routine()

        async def handle_out_of_band_message(self, msg):
            """Processa mensagens que chegam durante a negociação e não pertencem ao thread atual."""
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "patient_request":
                data = json.loads(msg.body)
                self.agent.pending_requests.append(data)
                await self.publish_waitlist()
                log(COORD_CONS,
                    f"[FILA] Doente {data.get('nome', '?')} adicionado à fila de rotina "
                    f"(posição={len(self.agent.pending_requests)}).",
                    "YELLOW")
                return

            if performative == "request" and msg_type == "preemption_order":
                data = json.loads(msg.body)
                # Bloquear rotina imediatamente para impedir adjudicações indevidas.
                self.agent.routine_hold = True
                await self.handle_preemption(data)
                return

            if performative == "inform" and msg_type == "routine_gate":
                data = json.loads(msg.body)
                self.agent.routine_hold = bool(data.get("hold", False))
                estado = "BLOQUEADA" if self.agent.routine_hold else "ATIVA"
                log(COORD_CONS, f"[PRIORIDADE] Via de rotina agora: {estado}", "YELLOW")
                return

        async def dispatch_next_routine(self):
            """Despacha apenas o primeiro doente da fila de rotina (FCFS estrito)."""
            if self.agent.routine_hold:
                log(COORD_CONS,
                    "[PRIORIDADE] Rotina temporariamente bloqueada: urgências em espera.",
                    "RED")
                return

            if not self.agent.pending_requests:
                return

            patient = self.agent.pending_requests[0]
            log(COORD_CONS,
                f"[FCFS] A tentar alocar cabeça da fila: {patient.get('nome', '?')}",
                "YELLOW")
            allocated = await self.run_contract_net(patient)

            if allocated:
                self.agent.pending_requests.pop(0)
                await self.publish_waitlist()
            else:
                log(COORD_CONS,
                    f"[FCFS] Cabeça da fila mantém-se em espera: {patient.get('nome', '?')}",
                    "YELLOW")

        # -----------------------------------------------------------------
        # CONTRACT-NET: CFP → Recolher propostas → Adjudicar
        # -----------------------------------------------------------------
        async def run_contract_net(self, patient_data):
            """Executa o protocolo Contract-Net para alocar médico + sala."""
            agent = self.agent
            nome = patient_data["nome"]
            doente_jid = patient_data["doente_jid"]

            if self.agent.routine_hold:
                log(COORD_CONS,
                    f"[PRIORIDADE] Alocação de rotina suspensa para {nome} (urgência em espera).",
                    "RED")
                return False

            log(COORD_CONS,
                f"[CONTRACT-NET] A iniciar negociação para {nome}...", "GREEN")

            # 1) Enviar CFP a todos os Médicos
            for m_jid in MEDICOS:
                cfp = Message(to=m_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "consultation_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_CONS, f"[CFP] Call for Proposal enviado ao médico {m_jid}", "GREEN")

            # 2) Enviar CFP a todas as Salas
            for s_jid in SALAS:
                cfp = Message(to=s_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "consultation_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_CONS, f"[CFP] Call for Proposal enviado à sala {s_jid}", "GREEN")

            # 3) Aguardar e recolher propostas
            await asyncio.sleep(2)  # tempo para respostas chegarem

            medico_proposta = None
            sala_proposta = None
            expected_replies = len(MEDICOS) + len(SALAS)

            for _ in range(expected_replies):
                reply = await self.receive(timeout=3)
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
                        log(COORD_CONS,
                            f"Proposta de médico recebida: "
                            f"{body['nome_medico']}", "GREEN")
                    elif "sala_jid" in body:
                        sala_proposta = body
                        log(COORD_CONS,
                            f"Proposta de sala recebida: "
                            f"{body['nome_sala']}", "GREEN")
                elif perf == "reject-proposal":
                    log(COORD_CONS,
                        f"[PROPOSTA] Proposta rejeitada: {body.get('motivo', '?')}",
                        "YELLOW")

            if self.agent.routine_hold:
                log(COORD_CONS,
                    f"[PRIORIDADE] Adjudicação de rotina cancelada para {nome} (urgência ativa).",
                    "RED")
                return False

            # 4) Adjudicar ou recusar
            if medico_proposta and sala_proposta:
                # Aceitar médico
                acc_m = Message(to=medico_proposta["medico_jid"])
                acc_m.set_metadata("performative", "accept-proposal")
                acc_m.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": patient_data.get("tipo", "Normal"),
                    "sala_jid": sala_proposta["sala_jid"]
                })
                acc_m.thread = doente_jid
                await self.send(acc_m)

                # Aceitar sala
                acc_s = Message(to=sala_proposta["sala_jid"])
                acc_s.set_metadata("performative", "accept-proposal")
                acc_s.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": patient_data.get("tipo", "Normal")
                })
                acc_s.thread = doente_jid
                await self.send(acc_s)

                # Registar alocação
                agent.alocacoes[doente_jid] = {
                    "nome": nome,
                    "medico_jid": medico_proposta["medico_jid"],
                    "sala_jid": sala_proposta["sala_jid"],
                }

                log(COORD_CONS,
                    f"[ALOCAÇÃO] Consulta de Rotina AGENDADA: {nome} → "
                    f"Médico={medico_proposta['nome_medico']}, "
                    f"Sala={sala_proposta['nome_sala']}", "BOLD")
                return True
            else:
                log(COORD_CONS,
                    f"[ALOCAÇÃO-FALHOU] Impossível agendar consulta de rotina a {nome} "
                    f"(recursos indisponíveis). Pedido pendente.", "RED")
                return False

        # -----------------------------------------------------------------
        # PREEMPTION: Cancelar alocação normal para libertar recursos
        # -----------------------------------------------------------------
        async def handle_preemption(self, data):
            """Processa ordem de preemption do Supervisor."""
            log(COORD_CONS,
                f"⚠️  ORDEM DE PREEMPTION recebida do Supervisor! "
                f"Motivo: urgência de {data.get('urgente_nome', '?')}",
                "RED")

            agent = self.agent

            if agent.alocacoes:
                # Cancelar a primeira alocação encontrada
                doente_cancelar = list(agent.alocacoes.keys())[0]
                aloc = agent.alocacoes.pop(doente_cancelar)

                log(COORD_CONS,
                    f"[PREEMPÇÃO] A cancelar alocação de rotina de {aloc['nome']} para "
                    f"libertar recursos...", "RED")

                # Enviar cancel ao médico
                cancel_m = Message(to=aloc["medico_jid"])
                cancel_m.set_metadata("performative", "cancel")
                cancel_m.set_metadata("type", "preemption_cancel")
                cancel_m.body = json.dumps({
                    "motivo": "Preemption por urgência",
                    "doente_original": aloc["nome"],
                })
                cancel_m.thread = doente_cancelar
                await self.send(cancel_m)

                # Enviar cancel à sala
                cancel_s = Message(to=aloc["sala_jid"])
                cancel_s.set_metadata("performative", "cancel")
                cancel_s.set_metadata("type", "preemption_cancel")
                cancel_s.body = json.dumps({
                    "motivo": "Preemption por urgência",
                    "doente_original": aloc["nome"],
                })
                cancel_s.thread = doente_cancelar
                await self.send(cancel_s)

                log(COORD_CONS,
                    f"[PREEMPTION] Cancellation dispatched. Doente {aloc['nome']} "
                    f"será reagendado.", "YELLOW")

                # Colocar o doente cancelado na fila de pendentes
                agent.pending_requests.insert(0, {
                    "doente_jid": doente_cancelar,
                    "nome": aloc["nome"],
                    "tipo": "Normal",
                    "prioridade": 0,
                })
                await self.publish_waitlist()

                # Aguardar confirmações de cancelamento
                await asyncio.sleep(2)

                # Informar o Supervisor que os recursos foram libertados
                confirm = Message(to=jid(SUPERVISOR))
                confirm.set_metadata("performative", "inform")
                confirm.set_metadata("type", "preemption_done")
                confirm.body = json.dumps({
                    "status": "resources_freed",
                    "medico_jid": aloc["medico_jid"],
                    "sala_jid": aloc["sala_jid"],
                })
                await self.send(confirm)
                log(COORD_CONS,
                    "[PREEMPÇÃO] Recursos libertados com sucesso e supervisor notificado.", "YELLOW")
            else:
                log(COORD_CONS,
                    "[PREEMPÇÃO-FALHOU] Não existem alocações de rotina ativas para libertar.", "RED")
                confirm = Message(to=jid(SUPERVISOR))
                confirm.set_metadata("performative", "inform")
                confirm.set_metadata("type", "preemption_done")
                confirm.body = json.dumps({"status": "no_allocations"})
                await self.send(confirm)

    async def setup(self):
        log(COORD_CONS, "Coordenador de Consultas iniciado.", "GREEN")
        # SEM TEMPLATE — o behaviour único aceita TODAS as mensagens
        # (request, propose, reject-proposal, etc.)
        # A filtragem é feita manualmente no run() com if/elif.
        self.add_behaviour(self.CoordinatorBehaviour())
