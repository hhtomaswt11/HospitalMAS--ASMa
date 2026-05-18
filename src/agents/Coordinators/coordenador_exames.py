import asyncio
import json
import time

from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.agents.Coordinators.coordenador_base import CoordenadorBase
from src.config import *


class CoordenadorExames(CoordenadorBase):
    """Coordena MCDTs com fila, backoff e notificação explícita de falha."""

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, hospital_config=hospital_config, **kwargs)
        cfg = self.hospital_config
        self._medicos = cfg["medicos"]
        self._equipamentos = cfg["equipamentos"]
        self._equipamentos_specialty = cfg["equipamentos_specialty"]

    class ExamCoordinatorBehaviour(CyclicBehaviour):

        async def handle_out_of_band_message(self, msg):
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")
            if performative == "request" and msg_type == "exam_request":
                data = json.loads(msg.body)
                if self.agent.enqueue(data):
                    log(self.agent._coord_name,
                        f"[FILA-EXAME] Pedido enfileirado fora de banda: {data.get('nome', '?')}", "YELLOW")
                else:
                    log(self.agent._coord_name,
                        f"[FILA-EXAME] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")
            else:
                # Mensagens tardias/rejeições fora da thread atual não devem poluir o fluxo.
                return

        async def notify_exam_failure(self, patient_data, reason):
            doente_jid = patient_data.get("doente_jid")
            nome = patient_data.get("nome", "?")
            solicitante = patient_data.get("solicitante")
            payload = {
                "doente_jid": doente_jid,
                "nome": nome,
                "especialidade": patient_data.get("especialidade"),
                "estado": "exame_falhado",
                "motivo": reason,
                "recomenda_cirurgia": False,
            }

            if solicitante:
                result = Message(to=solicitante)
                result.set_metadata("performative", "inform")
                result.set_metadata("type", "exam_result")
                result.body = json.dumps(payload)
                result.thread = doente_jid
                await self.send(result)
            elif doente_jid:
                discharge = Message(to=doente_jid)
                discharge.set_metadata("performative", "inform")
                discharge.set_metadata("type", "discharge")
                discharge.body = json.dumps({"estado": "Alta/observacao por exame indisponivel"})
                discharge.thread = doente_jid
                await self.send(discharge)

            log(self.agent._coord_name,
                f"[EXAME-FALHADO] {nome}: {reason}. Solicitante notificado.",
                "RED")

        async def dispatch_next_exam(self):
            idx = self.agent.get_ready_index()
            if idx is None:
                return False

            patient = self.agent.pending_requests[idx]
            allocated = await self.run_exam_contract_net(patient)
            if allocated:
                removed = self.agent.pending_requests.pop(idx)
                self.agent.pending_patient_ids.discard(removed.get("doente_jid"))
                return True

            delay, retries, failed = self.agent.schedule_retry(
                patient, EXAM_MAX_RETRIES, EXAM_RETRY_BASE_SECONDS, EXAM_RETRY_MAX_SECONDS)
            if failed:
                removed = self.agent.pending_requests.pop(idx)
                self.agent.pending_patient_ids.discard(removed.get("doente_jid"))
                await self.notify_exam_failure(
                    removed,
                    f"sem alocação completa após {EXAM_MAX_RETRIES} tentativas",
                )
                return True

            log(self.agent._coord_name,
                f"[FILA-EXAME] Re-tentativa para {patient.get('nome', '?')} adiada {delay:.0f}s "
                f"(tentativa={retries}/{EXAM_MAX_RETRIES}).",
                "YELLOW")
            return False

        async def dispatch_exam_batch(self, max_dispatches=DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.pending_requests:
                progressed = await self.dispatch_next_exam()
                if not progressed:
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
                if self.agent.pending_requests:
                    await self.dispatch_exam_batch()
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "exam_request":
                data = json.loads(msg.body)
                log(self.agent._coord_name,
                    f"[PEDIDO] Pedido de diagnóstico MCDT recebido para: {data.get('nome', '?')}", "CYAN")
                if self.agent.enqueue(data):
                    await self.dispatch_exam_batch()
                else:
                    log(self.agent._coord_name,
                        f"[FILA-EXAME] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")
            else:
                await self.handle_out_of_band_message(msg)

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
                try:
                    body = json.loads(reply.body) if reply.body else {}
                except Exception:
                    body = {}
                if perf == "propose":
                    if "sala_jid" in body:
                        equipamento_propostas.append(body)
                    elif "medico_jid" in body:
                        medico_propostas.append(body)

            now = time.time()
            equipamento_proposta = None
            medico_proposta = None
            exam_start_at = now

            if equipamento_propostas and medico_propostas:
                def _slot_at(proposta, use_urgency=False):
                    slot = proposta.get("slot_at_urgency" if use_urgency else "slot_at", proposta.get("slot_at"))
                    try:
                        return float(slot)
                    except Exception:
                        return now

                def _score(proposta, use_urgency=False):
                    return proposta.get("score_urgency" if use_urgency else "score", proposta.get("score", 999))

                best = None
                is_urgent = patient_data.get("tipo_original") != "Normal" and patient_data.get("tipo") != "Normal"

                for m_prop in medico_propostas:
                    for eq_prop in equipamento_propostas:
                        start_at = max(_slot_at(m_prop), _slot_at(eq_prop))
                        combined_score = _score(m_prop) + _score(eq_prop)
                        key = (start_at, combined_score)
                        if best is None or key < best[0]:
                            best = (key, m_prop, eq_prop, start_at, None, None)
                            
                        if is_urgent:
                            u_start_at = max(_slot_at(m_prop, True), _slot_at(eq_prop, True))
                            u_combined_score = _score(m_prop, True) + _score(eq_prop, True)
                            if u_start_at < start_at:
                                u_key = (u_start_at, u_combined_score)
                                preempt_m = m_prop.get("preempt_target")
                                preempt_eq = eq_prop.get("preempt_target")
                                if best is None or u_key < best[0]:
                                    best = (u_key, m_prop, eq_prop, u_start_at, preempt_m, preempt_eq)

                if best:
                    _, medico_proposta, equipamento_proposta, exam_start_at, preempt_m, preempt_eq = best

            if equipamento_proposta and medico_proposta:
                preempted_set = set()
                if preempt_m:
                    cancel_m = Message(to=medico_proposta["medico_jid"])
                    cancel_m.set_metadata("performative", "cancel")
                    cancel_m.body = json.dumps({"doente_jid": preempt_m})
                    cancel_m.thread = preempt_m
                    await self.send(cancel_m)
                    if preempt_m not in preempted_set:
                        agent.enqueue({
                            "doente_jid": preempt_m,
                            "nome": f"Doente {preempt_m.split('@')[0]} (Re-agendado)",
                            "tipo": "Exam",
                            "tipo_original": "Normal",
                            "especialidade": exam_specialty,
                            "prioridade": ROUTINE_SURGERY_PRIORITY,
                            "solicitante": patient_data.get("solicitante"),
                        })
                        preempted_set.add(preempt_m)
                        
                if preempt_eq:
                    cancel_eq = Message(to=equipamento_proposta["sala_jid"])
                    cancel_eq.set_metadata("performative", "cancel")
                    cancel_eq.body = json.dumps({"doente_jid": preempt_eq})
                    cancel_eq.thread = preempt_eq
                    await self.send(cancel_eq)
                    if preempt_eq not in preempted_set:
                        agent.enqueue({
                            "doente_jid": preempt_eq,
                            "nome": f"Doente {preempt_eq.split('@')[0]} (Re-agendado)",
                            "tipo": "Exam",
                            "tipo_original": "Normal",
                            "especialidade": exam_specialty,
                            "prioridade": ROUTINE_SURGERY_PRIORITY,
                            "solicitante": patient_data.get("solicitante"),
                        })
                        preempted_set.add(preempt_eq)

                acc_eq = Message(to=equipamento_proposta["sala_jid"])
                acc_eq.set_metadata("performative", "accept-proposal")
                acc_eq.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "exam_start_at": exam_start_at
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
                    "solicitante": patient_data.get("solicitante"),
                    "tipo_original": patient_data.get("tipo_original", patient_data.get("tipo")),
                    "exam_start_at": exam_start_at
                })
                acc_med.thread = doente_jid
                await self.send(acc_med)

                await agent.reject_unselected(self, equipamento_propostas, equipamento_proposta["sala_jid"], "sala_jid", doente_jid, "Proposta não selecionada")
                await agent.reject_unselected(self, medico_propostas, medico_proposta["medico_jid"], "medico_jid", doente_jid, "Proposta não selecionada")

                # Aguardar confirmação de ambos os recursos
                expected = {equipamento_proposta["sala_jid"], medico_proposta["medico_jid"]}
                all_confirmed, confirmed = await agent.wait_for_confirmations(
                    self, doente_jid, expected,
                    CONTRACT_NET_RESPONSE_WAIT_SECONDS,
                    oob_handler=self.handle_out_of_band_message,
                )
                if not all_confirmed:
                    missing = expected - confirmed
                    log(agent._coord_name,
                        f"[CONFIRMAÇÃO-FALHOU] Exame para {nome}: {len(missing)} recurso(s) "
                        f"não confirmaram reserva. Re-tentativa.",
                        "RED")
                    return False

                log(agent._coord_name,
                    f"[ALOCAÇÃO] DIAGNÓSTICO AGENDADO: {nome} → "
                    f"Equipamento={equipamento_proposta.get('nome_sala', '?')}, "
                    f"Médico={medico_proposta.get('nome_medico', '?')}, "
                    f"slot_at={exam_start_at:.3f}s", "BOLD")

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
                        "procedure": "exam",
                        "exam_start_at": exam_start_at
                    })
                    notif.thread = doente_jid
                    await self.send(notif)

                if doente_jid:
                    notif_doente = Message(to=doente_jid)
                    notif_doente.set_metadata("performative", "inform")
                    notif_doente.set_metadata("type", "allocation_confirmed")
                    notif_doente.body = json.dumps({
                        "procedure": "exam",
                        "sala_jid": equipamento_proposta["sala_jid"],
                        "medico_jid": medico_proposta["medico_jid"],
                        "especialidade": exam_specialty,
                        "exam_start_at": exam_start_at
                    })
                    notif_doente.thread = doente_jid
                    await self.send(notif_doente)
                return True

            await agent.reject_all(self, equipamento_propostas, "sala_jid", doente_jid, "Sem par médico/equipamento completo")
            await agent.reject_all(self, medico_propostas, "medico_jid", doente_jid, "Sem par médico/equipamento completo")
            log(agent._coord_name,
                f"[ALLOCATION-FAILED] Sem alocação completa de exame para {nome} (esp={exam_specialty}).",
                "RED")
            return False

    async def setup(self):
        log(self._coord_name, "Coordenador de Exames iniciado.", "CYAN")
        self.add_behaviour(self.ExamCoordinatorBehaviour())
