import asyncio
import json
import time

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *


class CoordenadorConsultas(Agent):

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        cfg = hospital_config or H1_CONFIG
        self.hospital_config = cfg
        self._supervisor = cfg["supervisor"]
        self._medicos = cfg["medicos_consultas_routine"]
        self._salas = cfg["salas_consultas_routine"]
        self._agent_registry = AGENT_REGISTRY
        self._coord_name = str(agent_jid).split("@")[0]
        import time
        self._sim_start_time = time.time()

        self.alocacoes = {}
        self.pending_requests = {s: [] for s in ROUTINE_SPECIALTIES}
        self.pending_routine_patient_ids = set()

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

    def total_pending(self):
        return sum(len(q) for q in self.pending_requests.values())

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
            msg = Message(to=self.agent._supervisor)
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
                log(self.agent._coord_name,
                    f"[FILA] Doente {data.get('nome', '?')} adicionado à fila de rotina "
                    f"(especialidade={specialty}, posição={queue_len}).",
                    "YELLOW")
                if dispatch_after:
                    await self.dispatch_routine_batch()
            else:
                log(self.agent._coord_name,
                    f"[FILA] Pedido duplicado ignorado para {data.get('nome', '?')}.",
                    "YELLOW")

        async def process_routine_finished(self, data, dispatch_after=False):
            doente_jid = data.get("doente_jid")
            nome = data.get("nome", "?")
            if self.clear_routine_allocation(doente_jid):
                log(self.agent._coord_name,
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

            if performative == "request" and msg_type == "patient_request":
                data = json.loads(msg.body)
                log(self.agent._coord_name,
                    f"[PEDIDO] Pedido de consulta de rotina recebido: {data['nome']}",
                    "GREEN")
                await self.process_patient_request(data, dispatch_after=True)

            elif performative == "inform" and msg_type == "routine_finished":
                data = json.loads(msg.body)
                await self.process_routine_finished(data, dispatch_after=True)

            # ── Load-query from the Central Triage Agent ──
            elif performative == "cfp" and msg_type == "load_query":
                req_data = json.loads(msg.body)
                requested_specialty = req_data.get("especialidade")
                
                # Load for the specific specialty requested
                if requested_specialty:
                    spec_load = len(self.agent.pending_requests.get(requested_specialty, []))
                else:
                    spec_load = 0
                
                # Total load for the entire hospital routine queue
                total_load = self.agent.total_pending()

                reply = msg.make_reply()
                reply.set_metadata("performative", "propose")
                reply.set_metadata("type", "load_response")
                reply.body = json.dumps({
                    "specialty_load": spec_load,
                    "total_load": total_load,
                    "coord_jid": str(self.agent.jid),
                    "coord_cons": str(self.agent.jid),
                    "coord_urg": self.agent.hospital_config["coord_urg"],
                    "coord_tri": self.agent.hospital_config["coord_tri"],
                })
                await self.send(reply)

        async def handle_out_of_band_message(self, msg):
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "patient_request":
                data = json.loads(msg.body)
                await self.process_patient_request(data, dispatch_after=False)
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
            # Verificação rigorosa de horário
            import time
            elapsed = time.time() - self.agent._sim_start_time
            current_hour = (elapsed % SIM_DAY_SECONDS) / SIM_HOUR_SECONDS
            
            if not (ROUTINE_START_H <= current_hour < ROUTINE_END_H):
                # Se houver pedidos, apenas avisar que está fora de horas (uma vez por ciclo)
                if self.agent.has_pending_requests():
                     pass # Silencioso para não inundar o log, os médicos já rejeitam no CFP
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

                patient = queue[0]
                log(self.agent._coord_name,
                    f"[FCFS] A tentar alocar cabeça da fila de {specialty}: {patient.get('nome', '?')}",
                    "YELLOW")
                allocated = await self.run_contract_net(patient)
                if allocated:
                    self.agent.pop_pending_request(specialty)
                    await self.publish_waitlist()
                    return True

                log(self.agent._coord_name,
                    f"[FCFS] Doente mantém-se em espera ({specialty}): {patient.get('nome', '?')}",
                    "YELLOW")

            return False

        async def run_contract_net(self, patient_data):
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
                f"[CONTRACT-NET] A iniciar negociação para {nome}...", "GREEN")

            for m_jid in medicos_candidatos:
                cfp = Message(to=m_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "consultation_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)

            for s_jid in agent._salas:
                cfp = Message(to=s_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "consultation_cfp")
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
                elif perf == "reject-proposal":
                    pass
                # Removido o break para garantir leitura de todas as respostas

            now = time.time()
            medico_proposta = None
            sala_proposta = None
            consultation_start_at = now

            if medico_propostas and sala_propostas:
                def _slot_at(proposta):
                    slot = proposta.get("slot_at")
                    try:
                        return float(slot)
                    except Exception:
                        return now

                best = None
                for m_prop in medico_propostas:
                    for s_prop in sala_propostas:
                        start_at = max(_slot_at(m_prop), _slot_at(s_prop))
                        combined_score = m_prop.get("score", 999) + s_prop.get("score", 999)
                        key = (start_at, combined_score)
                        if best is None or key < best[0]:
                            best = (key, m_prop, s_prop, start_at)

                if best:
                    _, medico_proposta, sala_proposta, consultation_start_at = best

            if medico_proposta and sala_proposta:
                acc_m = Message(to=medico_proposta["medico_jid"])
                acc_m.set_metadata("performative", "accept-proposal")
                acc_m.set_metadata("type", "consultation_schedule")
                acc_m.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": patient_data.get("tipo", "Normal"),
                    "sala_jid": sala_proposta["sala_jid"],
                    "consultation_start_at": consultation_start_at,
                })
                acc_m.thread = doente_jid
                await self.send(acc_m)

                acc_s = Message(to=sala_proposta["sala_jid"])
                acc_s.set_metadata("performative", "accept-proposal")
                acc_s.set_metadata("type", "consultation_schedule")
                acc_s.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": patient_data.get("tipo", "Normal"),
                    "consultation_start_at": consultation_start_at,
                })
                acc_s.thread = doente_jid
                await self.send(acc_s)

                schedule_msg = Message(to=doente_jid)
                schedule_msg.set_metadata("performative", "inform")
                schedule_msg.set_metadata("type", "consultation_scheduled")
                schedule_msg.body = json.dumps({
                    "nome": nome,
                    "medico_jid": medico_proposta["medico_jid"],
                    "sala_jid": sala_proposta["sala_jid"],
                    "consultation_start_at": consultation_start_at,
                })
                schedule_msg.thread = doente_jid
                await self.send(schedule_msg)

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

                agent.alocacoes[doente_jid] = {
                    "nome": nome,
                    "especialidade": patient_data.get("especialidade"),
                    "medico_jid": medico_proposta["medico_jid"],
                    "sala_jid": sala_proposta["sala_jid"],
                }

                # Log allocation including scheduled slot for observability
                log(agent._coord_name,
                    f"[ALOCAÇÃO] Consulta de Rotina AGENDADA: {nome} → "
                    f"Médico={medico_proposta['nome_medico']}, "
                    f"Sala={sala_proposta['nome_sala']}, "
                    f"slot_at={consultation_start_at:.3f}s", "BOLD")
                return True
            else:
                log(agent._coord_name,
                    f"[ALOCAÇÃO-FALHOU] Impossível agendar consulta de rotina a {nome} "
                    f"(recursos indisponíveis). Pedido pendente.", "RED")
                return False

    async def setup(self):
        log(self._coord_name, "Coordenador de Consultas iniciado.", "GREEN")
        self.add_behaviour(self.CoordinatorBehaviour())
