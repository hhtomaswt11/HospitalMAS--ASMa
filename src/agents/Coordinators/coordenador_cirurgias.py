import asyncio
import json
import random
import time

from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.agents.Coordinators.coordenador_base import CoordenadorBase
from src.config import *


class CoordenadorCirurgias(CoordenadorBase):
    """Coordena cirurgias com fila, backoff e resultado explícito para o médico solicitante."""

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, hospital_config=hospital_config, **kwargs)
        cfg = self.hospital_config
        self._medicos = cfg["medicos"]
        self._blocos = cfg["blocos"]

    class SurgeryCoordinatorBehaviour(CyclicBehaviour):

        async def handle_out_of_band_message(self, msg):
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")
            if performative == "request" and msg_type == "surgery_request":
                data = json.loads(msg.body)
                if self.agent.enqueue(data):
                    log(self.agent._coord_name,
                        f"[FILA-CIR] Pedido enfileirado fora de banda: {data.get('nome', '?')}", "YELLOW")
                else:
                    log(self.agent._coord_name,
                        f"[FILA-CIR] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")
            else:
                return

        async def notify_surgery_failure(self, patient_data, reason):
            doente_jid = patient_data.get("doente_jid")
            nome = patient_data.get("nome", "?")
            solicitante = patient_data.get("solicitante")
            payload = {
                "doente_jid": doente_jid,
                "nome": nome,
                "estado": "cirurgia_falhada",
                "motivo": reason,
            }
            if solicitante:
                result = Message(to=solicitante)
                result.set_metadata("performative", "inform")
                result.set_metadata("type", "surgery_result")
                result.body = json.dumps(payload)
                result.thread = doente_jid
                await self.send(result)
            elif doente_jid:
                discharge = Message(to=doente_jid)
                discharge.set_metadata("performative", "inform")
                discharge.set_metadata("type", "discharge")
                discharge.body = json.dumps({"estado": "Alta/observacao por cirurgia indisponivel"})
                discharge.thread = doente_jid
                await self.send(discharge)
            await self.agent.emit_metric_event(
                self,
                "patient_failed_after_retries",
                patient_data,
                procedure="surgery",
                reason=reason,
                retry_count=patient_data.get("_retry_count"),
            )

            log(self.agent._coord_name,
                f"[CIRURGIA-FALHADA] {nome}: {reason}. Solicitante notificado.",
                "RED")

        async def dispatch_next_surgery(self):
            idx = self.agent.get_ready_index()
            if idx is None:
                return False

            patient = self.agent.pending_requests[idx]
            allocated = await self.run_surgery_contract_net(patient)
            if allocated:
                removed = self.agent.pending_requests.pop(idx)
                self.agent.pending_patient_ids.discard(removed.get("doente_jid"))
                return True

            delay, retries, failed = self.agent.schedule_retry(
                patient, SURGERY_MAX_RETRIES, SURGERY_RETRY_BASE_SECONDS, SURGERY_RETRY_MAX_SECONDS)
            if failed:
                removed = self.agent.pending_requests.pop(idx)
                self.agent.pending_patient_ids.discard(removed.get("doente_jid"))
                await self.notify_surgery_failure(
                    removed,
                    f"sem bloco/cirurgião disponível após {SURGERY_MAX_RETRIES} tentativas",
                )
                return True

            log(self.agent._coord_name,
                f"[FILA-CIR] Re-tentativa para {patient.get('nome', '?')} adiada {delay:.0f}s "
                f"(tentativa={retries}/{SURGERY_MAX_RETRIES}).",
                "YELLOW")
            return False

        async def dispatch_surgery_batch(self, max_dispatches=DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.pending_requests:
                progressed = await self.dispatch_next_surgery()
                if not progressed:
                    break
                dispatched += 1

        async def run(self):
            msg = await self.receive(timeout=COORDINATOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                if self.agent.pending_requests:
                    await self.dispatch_surgery_batch()
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "surgery_request":
                data = json.loads(msg.body)
                log(self.agent._coord_name,
                    f"[PEDIDO] Pedido de cirurgia recebido para: {data.get('nome', '?')}", "MAGENTA")
                if self.agent.enqueue(data):
                    await self.dispatch_surgery_batch()
                else:
                    log(self.agent._coord_name,
                        f"[FILA-CIR] Pedido duplicado ignorado: {data.get('nome', '?')}", "YELLOW")
            else:
                await self.handle_out_of_band_message(msg)

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
                try:
                    body = json.loads(reply.body) if reply.body else {}
                except Exception:
                    body = {}
                if perf == "propose":
                    if "sala_jid" in body:
                        bloco_propostas.append(body)
                    elif "medico_jid" in body:
                        medico_propostas.append(body)

            now = time.time()
            medico_proposta, bloco_proposta, surgery_start_at, preempt_m, preempt_eq = (
                self.agent.select_best_resource_pair(medico_propostas, bloco_propostas, patient_data)
            )
            if surgery_start_at is None:
                surgery_start_at = now

            if bloco_proposta and medico_proposta:
                preempted_set = set()
                if preempt_m:
                    cancel_m = Message(to=medico_proposta["medico_jid"])
                    cancel_m.set_metadata("performative", "cancel")
                    cancel_m.body = json.dumps({"doente_jid": preempt_m})
                    cancel_m.thread = preempt_m
                    await self.send(cancel_m)
                    if preempt_m not in preempted_set:
                        # Since only routine surgeries are preemptable in the medical agent,
                        # we can safely re-enqueue with routine priority.
                        agent.enqueue({
                            "doente_jid": preempt_m,
                            "nome": f"Doente {preempt_m.split('@')[0]} (Re-agendado)",
                            "tipo": "Surgery",
                            "tipo_original": "Normal",
                            "prioridade": ROUTINE_SURGERY_PRIORITY,
                            "solicitante": patient_data.get("solicitante"),
                        })
                        preempted_set.add(preempt_m)
                        
                if preempt_eq:
                    cancel_eq = Message(to=bloco_proposta["sala_jid"])
                    cancel_eq.set_metadata("performative", "cancel")
                    cancel_eq.body = json.dumps({"doente_jid": preempt_eq})
                    cancel_eq.thread = preempt_eq
                    await self.send(cancel_eq)
                    if preempt_eq not in preempted_set:
                        agent.enqueue({
                            "doente_jid": preempt_eq,
                            "nome": f"Doente {preempt_eq.split('@')[0]} (Re-agendado)",
                            "tipo": "Surgery",
                            "tipo_original": "Normal",
                            "prioridade": ROUTINE_SURGERY_PRIORITY,
                            "solicitante": patient_data.get("solicitante"),
                        })
                        preempted_set.add(preempt_eq)

                duration_hr = float(random.choice([1, 2, 3]))
                duration_sec = duration_hr * SIM_HOUR_SECONDS

                acc_b = Message(to=bloco_proposta["sala_jid"])
                acc_b.set_metadata("performative", "accept-proposal")
                acc_b.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "surgery_start_at": surgery_start_at,
                    "surgery_duration_hours": duration_hr,
                    "surgery_duration_seconds": duration_sec,
                    "spawned_at": patient_data.get("spawned_at")
                })
                acc_b.thread = doente_jid
                await self.send(acc_b)

                acc_m = Message(to=medico_proposta["medico_jid"])
                acc_m.set_metadata("performative", "accept-proposal")
                acc_m.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "sala_jid": bloco_proposta["sala_jid"],
                    "solicitante": patient_data.get("solicitante"),
                    "tipo_original": patient_data.get("tipo_original", patient_data.get("tipo")),
                    "surgery_start_at": surgery_start_at,
                    "surgery_duration_hours": duration_hr,
                    "surgery_duration_seconds": duration_sec,
                    "spawned_at": patient_data.get("spawned_at")
                })
                acc_m.thread = doente_jid

                await self.send(acc_m)

                await agent.reject_unselected(self, bloco_propostas, bloco_proposta["sala_jid"], "sala_jid", doente_jid, "Proposta não selecionada")
                await agent.reject_unselected(self, medico_propostas, medico_proposta["medico_jid"], "medico_jid", doente_jid, "Proposta não selecionada")

                # Aguardar confirmação de ambos os recursos
                expected = {bloco_proposta["sala_jid"], medico_proposta["medico_jid"]}
                all_confirmed, confirmed = await agent.wait_for_confirmations(
                    self, doente_jid, expected,
                    CONTRACT_NET_RESPONSE_WAIT_SECONDS,
                    oob_handler=self.handle_out_of_band_message,
                )
                if not all_confirmed:
                    missing = expected - confirmed
                    log(agent._coord_name,
                        f"[CONFIRMAÇÃO-FALHOU] Cirurgia para {nome}: {len(missing)} recurso(s) "
                        f"não confirmaram reserva. Re-tentativa.",
                        "RED")
                    return False

                log(agent._coord_name,
                    f"[ALOCAÇÃO] CIRURGIA AGENDADA: {nome} → "
                    f"Bloco={bloco_proposta.get('nome_sala', '?')}, "
                    f"Cirurgião={medico_proposta.get('nome_medico', '?')}, "
                    f"slot_at={surgery_start_at:.3f}s", "BOLD")

                solicitante = patient_data.get("solicitante")
                if solicitante:
                    notif = Message(to=solicitante)
                    notif.set_metadata("performative", "inform")
                    notif.set_metadata("type", "allocation_confirmed")
                    notif.body = json.dumps({
                        "doente_jid": doente_jid,
                        "sala_jid": bloco_proposta["sala_jid"],
                        "procedure": "surgery",
                        "surgery_start_at": surgery_start_at
                    })
                    notif.thread = doente_jid
                    await self.send(notif)

                if doente_jid:
                    notif_doente = Message(to=doente_jid)
                    notif_doente.set_metadata("performative", "inform")
                    notif_doente.set_metadata("type", "allocation_confirmed")
                    notif_doente.body = json.dumps({
                        "procedure": "surgery",
                        "sala_jid": bloco_proposta["sala_jid"],
                        "medico_jid": medico_proposta["medico_jid"],
                        "surgery_start_at": surgery_start_at
                    })
                    notif_doente.thread = doente_jid
                    await self.send(notif_doente)
                return True

            await agent.reject_all(self, bloco_propostas, "sala_jid", doente_jid, "Sem par bloco/cirurgião completo")
            await agent.reject_all(self, medico_propostas, "medico_jid", doente_jid, "Sem par bloco/cirurgião completo")
            log(agent._coord_name,
                f"[ALLOCATION-FAILED] No valid surgical resources available for {nome}.", "RED")
            return False

    async def setup(self):
        log(self._coord_name, "Coordenador de Cirurgias iniciado.", "MAGENTA")
        self.add_behaviour(self.SurgeryCoordinatorBehaviour())
