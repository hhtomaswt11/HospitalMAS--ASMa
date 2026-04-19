import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *

class CoordenadorConsultas(Agent):

    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.alocacoes = {}         # doente_jid → {medico, sala, nome}
        self.pending_requests = {s: [] for s in ROUTINE_SPECIALTIES}
        self.pending_routine_patient_ids = set()
        self.routine_hold = False   # bloqueia rotina quando há urgências em espera
        self.blocked_specialties = set()

    def add_pending_request(self, data, prepend=False):
        doente_jid = data.get("doente_jid")
        if not doente_jid:
            return False
        if doente_jid in self.pending_routine_patient_ids:
            return False

        specialty = data.get("especialidade")
        if not specialty:
            specialty = ROUTINE_SPECIALTIES[0]
            data["especialidade"] = specialty
        if specialty not in self.pending_requests:
            self.pending_requests[specialty] = []
        if prepend:
            self.pending_requests[specialty].insert(0, data)
        else:
            self.pending_requests[specialty].append(data)
        self.pending_routine_patient_ids.add(doente_jid)
        return True

    def flatten_pending_requests(self):
        all_requests = []
        ordered_specialties = list(ROUTINE_SPECIALTIES)
        ordered_specialties.extend(
            [s for s in self.pending_requests.keys() if s not in ordered_specialties]
        )
        for specialty in ordered_specialties:
            all_requests.extend(self.pending_requests.get(specialty, []))
        return all_requests

    def has_pending_requests(self):
        return any(self.pending_requests.get(s, []) for s in self.pending_requests)

    def pop_pending_request(self, specialty):
        queue = self.pending_requests.get(specialty, [])
        if queue:
            removed = queue.pop(0)
            self.pending_routine_patient_ids.discard(removed.get("doente_jid"))
            return removed
        return None

    def get_routine_waitlist_by_specialty(self):
        by_specialty = {}
        for specialty, queue in self.pending_requests.items():
            by_specialty[specialty] = [
                {
                    "doente_jid": p.get("doente_jid"),
                    "nome": p.get("nome", "?"),
                    "tipo": p.get("tipo", "Normal"),
                    "prioridade": p.get("prioridade", 0),
                    "especialidade": p.get("especialidade"),
                }
                for p in queue
            ]
        return by_specialty

    def get_routine_waitlist(self):
        return [
            {
                "doente_jid": p.get("doente_jid"),
                "nome": p.get("nome", "?"),
                "tipo": p.get("tipo", "Normal"),
                "prioridade": p.get("prioridade", 0),
                "especialidade": p.get("especialidade"),
            }
            for p in self.flatten_pending_requests()
        ]

    class CoordinatorBehaviour(CyclicBehaviour):

        def clear_routine_allocation(self, doente_jid):
            if not doente_jid:
                return False
            if doente_jid in self.agent.alocacoes:
                self.agent.alocacoes.pop(doente_jid, None)
                return True
            return False

        async def publish_waitlist(self):
            msg = Message(to=jid(SUPERVISOR))
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "waitlist_update")
            msg.body = json.dumps({
                "queue": "routine",
                "patients": self.agent.get_routine_waitlist(),
                "by_specialty": self.agent.get_routine_waitlist_by_specialty(),
            })
            await self.send(msg)

        async def process_patient_request(self, data, dispatch_after=False):
            if self.agent.add_pending_request(data):
                await self.publish_waitlist()
                specialty = data.get("especialidade", "?")
                queue_len = len(self.agent.pending_requests.get(specialty, []))
                log(COORD_CONS,
                    f"[FILA] Doente {data.get('nome', '?')} adicionado à fila de rotina "
                    f"(especialidade={specialty}, posição={queue_len}).",
                    "YELLOW")
                if dispatch_after:
                    await self.dispatch_routine_batch()
            else:
                log(COORD_CONS,
                    f"[FILA] Pedido duplicado ignorado para {data.get('nome', '?')}.",
                    "YELLOW")

        async def process_preemption_order(self, data, dispatch_after=False, force_hold=False):
            if force_hold:
                self.agent.routine_hold = True
            await self.handle_preemption(data)
            if dispatch_after:
                await self.dispatch_routine_batch()

        async def process_routine_gate(self, data, dispatch_after=False):
            blocked = data.get("blocked_specialties")
            if isinstance(blocked, list):
                self.agent.blocked_specialties = {s for s in blocked if s}
                self.agent.routine_hold = len(self.agent.blocked_specialties) > 0
            else:
                self.agent.routine_hold = bool(data.get("hold", False))
                self.agent.blocked_specialties = set()
            estado = "BLOQUEADA" if self.agent.routine_hold else "ATIVA"
            log(COORD_CONS, f"[PRIORIDADE] Via de rotina agora: {estado}", "YELLOW")
            if dispatch_after and not self.agent.routine_hold:
                await self.dispatch_routine_batch()

        async def process_routine_finished(self, data, dispatch_after=False):
            doente_jid = data.get("doente_jid")
            nome = data.get("nome", "?")
            if self.clear_routine_allocation(doente_jid):
                log(COORD_CONS,
                    f"[ALOCACAO-LIMPA] Consulta de rotina finalizada/removida para {nome}.",
                    "YELLOW")
                if dispatch_after and self.agent.has_pending_requests():
                    await self.dispatch_routine_batch()


        async def run(self):
            msg = await self.receive(timeout=COORDINATOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                if self.agent.has_pending_requests():
                    await self.dispatch_routine_batch()
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            # ---- Pedido de consulta normal ----
            if performative == "request" and msg_type == "patient_request":
                data = json.loads(msg.body)
                log(COORD_CONS,
                    f"[PEDIDO] Pedido de consulta de rotina recebido: {data['nome']}",
                    "GREEN")
                await self.process_patient_request(data, dispatch_after=True)

            # ---- Ordem de preemption do Supervisor ----
            elif performative == "request" and msg_type == "preemption_order":
                data = json.loads(msg.body)
                await self.process_preemption_order(data, dispatch_after=True)

            elif performative == "inform" and msg_type == "routine_gate":
                data = json.loads(msg.body)
                await self.process_routine_gate(data, dispatch_after=True)

            elif performative == "inform" and msg_type == "routine_finished":
                data = json.loads(msg.body)
                await self.process_routine_finished(data, dispatch_after=True)

        async def handle_out_of_band_message(self, msg):
            """Processa mensagens que chegam durante a negociação e não pertencem ao thread atual."""
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "patient_request":
                data = json.loads(msg.body)
                await self.process_patient_request(data, dispatch_after=False)
                return

            if performative == "request" and msg_type == "preemption_order":
                data = json.loads(msg.body)
                await self.process_preemption_order(data, dispatch_after=False, force_hold=True)
                return

            if performative == "inform" and msg_type == "routine_gate":
                data = json.loads(msg.body)
                await self.process_routine_gate(data, dispatch_after=False)
                return

            if performative == "inform" and msg_type == "routine_finished":
                data = json.loads(msg.body)
                await self.process_routine_finished(data, dispatch_after=False)
                return

        async def dispatch_routine_batch(self, max_dispatches=DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.has_pending_requests():
                allocated = await self.dispatch_next_routine()
                if not allocated:
                    break
                dispatched += 1

        async def dispatch_next_routine(self):
            """Despacha apenas o primeiro doente da fila de rotina (FCFS estrito)."""
            if self.agent.routine_hold and not self.agent.blocked_specialties:
                log(COORD_CONS,
                    "[PRIORIDADE] Rotina temporariamente bloqueada: urgências em espera.",
                    "RED")
                return False

            if not self.agent.has_pending_requests():
                return False

            ordered_specialties = list(ROUTINE_SPECIALTIES)
            ordered_specialties.extend(
                [s for s in self.agent.pending_requests.keys() if s not in ordered_specialties]
            )

            for specialty in ordered_specialties:
                queue = self.agent.pending_requests.get(specialty, [])
                if not queue:
                    continue

                if specialty in self.agent.blocked_specialties:
                    log(
                        COORD_CONS,
                        f"[PRIORIDADE] Especialidade de rotina bloqueada por urgência: {specialty}.",
                        "RED",
                    )
                    continue

                patient = queue[0]
                log(
                    COORD_CONS,
                    f"[FCFS] A tentar alocar cabeça da fila de {specialty}: {patient.get('nome', '?')}",
                    "YELLOW",
                )
                allocated = await self.run_contract_net(patient)
                if allocated:
                    self.agent.pop_pending_request(specialty)
                    await self.publish_waitlist()
                    return True

                log(
                    COORD_CONS,
                    f"[FCFS] Doente mantém-se em espera ({specialty}): {patient.get('nome', '?')}",
                    "YELLOW",
                )

            return False

        # -----------------------------------------------------------------
        # CONTRACT-NET: CFP → Recolher propostas → Adjudicar
        # -----------------------------------------------------------------
        async def run_contract_net(self, patient_data):
            """Executa o protocolo Contract-Net para alocar médico + sala."""
            agent = self.agent
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
                    COORD_CONS,
                    f"[CFP-FILTER] Sem médicos compatíveis (esp={requested_specialty}) para {nome}.",
                    "YELLOW",
                )
                return False

            if requested_specialty in self.agent.blocked_specialties:
                log(COORD_CONS,
                    f"[PRIORIDADE] Alocação de rotina suspensa para {nome} (urgência em espera na especialidade {requested_specialty}).",
                    "RED")
                return False

            if self.agent.routine_hold and not self.agent.blocked_specialties:
                log(COORD_CONS,
                    f"[PRIORIDADE] Alocação de rotina suspensa para {nome} (urgência em espera).",
                    "RED")
                return False

            log(COORD_CONS,
                f"[CONTRACT-NET] A iniciar negociação para {nome}...", "GREEN")

            # 1) Enviar CFP apenas a médicos compatíveis
            for m_jid in medicos_candidatos:
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

            # 3) Recolher propostas com early-stopping: parar assim que existir par médico+sala.
            medico_propostas = []
            sala_propostas = []
            expected_replies = len(medicos_candidatos) + len(SALAS)

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

                received_replies += 1

                if reply.thread != doente_jid:
                    await self.handle_out_of_band_message(reply)
                    continue

                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)

                if perf == "propose":
                    if "medico_jid" in body:
                        medico_propostas.append(body)
                        log(COORD_CONS,
                            f"Proposta de médico recebida: "
                            f"{body['nome_medico']}", "GREEN")
                    elif "sala_jid" in body:
                        sala_propostas.append(body)
                        log(COORD_CONS,
                            f"Proposta de sala recebida: "
                            f"{body['nome_sala']}", "GREEN")
                elif perf == "reject-proposal":
                    log(COORD_CONS,
                        f"[PROPOSTA] Proposta rejeitada: {body.get('motivo', '?')}",
                        "YELLOW")

                if medico_propostas and sala_propostas:
                    log(
                        COORD_CONS,
                        f"[CONTRACT-NET] Early-stop ativado para {nome}: par médico+sala encontrado.",
                        "GREEN",
                    )
                    break

            if requested_specialty in self.agent.blocked_specialties:
                log(COORD_CONS,
                    f"[PRIORIDADE] Adjudicação de rotina cancelada para {nome} (urgência ativa na especialidade {requested_specialty}).",
                    "RED")
                return False

            if self.agent.routine_hold and not self.agent.blocked_specialties:
                log(COORD_CONS,
                    f"[PRIORIDADE] Adjudicação de rotina cancelada para {nome} (urgência ativa).",
                    "RED")
                return False

            # 4) Adjudicar ou recusar
            medico_proposta = medico_propostas[0] if medico_propostas else None
            sala_proposta = sala_propostas[0] if sala_propostas else None

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

                # Rejeitar os proponentes não selecionados.
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

                for proposta in sala_propostas:
                    sala_jid = proposta.get("sala_jid")
                    if not sala_jid or sala_jid == sala_proposta["sala_jid"]:
                        continue
                    rej = Message(to=sala_jid)
                    rej.set_metadata("performative", "reject-proposal")
                    rej.body = json.dumps({
                        "motivo": "Proposta não selecionada",
                        "doente_jid": doente_jid,
                    })
                    rej.thread = doente_jid
                    await self.send(rej)

                # Registar alocação
                agent.alocacoes[doente_jid] = {
                    "nome": nome,
                    "especialidade": patient_data.get("especialidade"),
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
        async def await_preemption_confirmations(self, doente_jid, medico_jid, sala_jid):
            """Aguarda ACKs de cancelamento de médico e sala para uma preempção."""
            confirmed_medico = False
            confirmed_sala = False

            deadline = asyncio.get_running_loop().time() + PREEMPTION_CONFIRM_WAIT_SECONDS

            while not (confirmed_medico and confirmed_sala):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break

                reply = await self.receive(timeout=remaining)
                if reply is None:
                    break

                if reply.thread != doente_jid:
                    await self.handle_out_of_band_message(reply)
                    continue

                if (
                    reply.get_metadata("performative") != "inform"
                    or reply.get_metadata("type") != "cancel_confirmed"
                ):
                    continue

                try:
                    body = json.loads(reply.body)
                except Exception:
                    continue

                sender_bare = str(reply.sender).split("/")[0]
                medico_bare = str(medico_jid).split("/")[0]
                sala_bare = str(sala_jid).split("/")[0]

                if sender_bare == medico_bare and body.get("status") == "freed":
                    confirmed_medico = True
                elif sender_bare == sala_bare and body.get("status") == "freed":
                    confirmed_sala = True

            return confirmed_medico, confirmed_sala

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
                agent.add_pending_request({
                    "doente_jid": doente_cancelar,
                    "nome": aloc["nome"],
                    "tipo": "Normal",
                    "prioridade": 0,
                    "especialidade": aloc.get("especialidade"),
                }, prepend=True)
                await self.publish_waitlist()

                # Aguardar confirmações explícitas de cancelamento
                confirmed_medico, confirmed_sala = await self.await_preemption_confirmations(
                    doente_cancelar,
                    aloc["medico_jid"],
                    aloc["sala_jid"],
                )

                status = "resources_freed" if (confirmed_medico and confirmed_sala) else "cancel_timeout"

                # Informar o Supervisor do resultado real da preempção
                confirm = Message(to=jid(SUPERVISOR))
                confirm.set_metadata("performative", "inform")
                confirm.set_metadata("type", "preemption_done")
                confirm.body = json.dumps({
                    "status": status,
                    "medico_jid": aloc["medico_jid"],
                    "sala_jid": aloc["sala_jid"],
                    "confirmed_medico": confirmed_medico,
                    "confirmed_sala": confirmed_sala,
                })
                await self.send(confirm)
                if status == "resources_freed":
                    log(COORD_CONS,
                        "[PREEMPÇÃO] Recursos libertados com sucesso e supervisor notificado.", "YELLOW")
                else:
                    log(COORD_CONS,
                        "[PREEMPÇÃO-AVISO] Timeout na confirmação de cancelamento; supervisor notificado com estado parcial.",
                        "RED")
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
