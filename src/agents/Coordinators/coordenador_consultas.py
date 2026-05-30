import asyncio
import json
import time

from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.agents.Coordinators.coordenador_base import CoordenadorBase
from src.config import *
from src.scheduling import (
    find_next_routine_slot_for_pair,
    is_interval_free,
    sim_time_label,
    validate_routine_slot,
)


class CoordenadorConsultas(CoordenadorBase):

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, hospital_config=hospital_config, **kwargs)
        cfg = self.hospital_config
        self._medicos = cfg["medicos_consultas_routine"]
        self._salas = cfg["salas_consultas_routine"]
        self._sim_start_time = time.time() - (8 * SIM_HOUR_SECONDS)

        # Alocações por doente, mantendo estado explícito da consulta.
        self.alocacoes = {}
        self.historico_alocacoes = []

        # Agenda centralizada de rotina: cada recurso tem uma lista de intervalos
        # reservados. Isto evita depender apenas do estado "disponível agora" dos
        # agentes e permite marcar slots futuros realistas.
        self.resource_schedules = {
            r_jid: []
            for r_jid in (self._medicos + self._salas)
        }

        # Override da fila genérica do CoordenadorBase: consultas usam
        # um dicionário por especialidade em vez de uma lista simples.
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

    def get_scheduled_routine_allocations(self, now=None):
        """Return active/future routine allocations used as real load.

        Patients already assigned to a future slot must still count for central
        triage load-balancing; otherwise a hospital with a full future agenda
        would look empty just because its waiting queue was already dispatched.
        """
        now = now or time.time()
        scheduled = []
        for allocation in self.alocacoes.values():
            if not isinstance(allocation, dict):
                continue
            estado = allocation.get("estado")
            if estado not in {"reservada", "agendada", "em curso"}:
                continue
            try:
                end_at = float(allocation.get("consultation_end_at", 0))
            except Exception:
                end_at = 0
            if estado in {"reservada", "agendada"} or end_at >= now:
                scheduled.append(allocation)
        return scheduled

    def get_scheduled_routine_by_specialty(self):
        by_specialty = {}
        for allocation in self.get_scheduled_routine_allocations():
            specialty = allocation.get("especialidade") or "sem_especialidade"
            by_specialty.setdefault(specialty, []).append({
                "doente_jid": allocation.get("doente_jid"),
                "nome": allocation.get("nome", "?"),
                "tipo": allocation.get("tipo", "Normal"),
                "especialidade": specialty,
                "medico_jid": allocation.get("medico_jid"),
                "sala_jid": allocation.get("sala_jid"),
                "hora_inicio_marcada": allocation.get("hora_inicio_marcada"),
                "hora_fim_prevista": allocation.get("hora_fim_prevista"),
                "estado": allocation.get("estado"),
            })
        return by_specialty

    def get_routine_load_metrics(self, requested_specialty=None):
        pending_by_spec = {s: len(q) for s, q in self.pending_requests.items()}
        scheduled_by_spec = self.get_scheduled_routine_by_specialty()
        scheduled_count_by_spec = {s: len(q) for s, q in scheduled_by_spec.items()}

        pending_total = self.total_pending()
        scheduled_total = sum(scheduled_count_by_spec.values())

        if requested_specialty:
            pending_spec = pending_by_spec.get(requested_specialty, 0)
            scheduled_spec = scheduled_count_by_spec.get(requested_specialty, 0)
        else:
            pending_spec = 0
            scheduled_spec = 0

        return {
            "pending_specialty_load": pending_spec,
            "scheduled_specialty_load": scheduled_spec,
            "specialty_load": pending_spec + scheduled_spec,
            "pending_total_load": pending_total,
            "scheduled_total_load": scheduled_total,
            "total_load": pending_total + scheduled_total,
        }

    def get_resource_schedule(self, resource_jid):
        return self.resource_schedules.setdefault(resource_jid, [])

    def _active_schedule_count(self, resource_jid):
        return sum(
            1 for entry in self.get_resource_schedule(resource_jid)
            if isinstance(entry, dict) and entry.get("estado") in {"agendada", "em curso", "reservada", None}
        )

    def _cleanup_old_schedule_entries(self, now=None):
        """Keep the schedule compact without losing recent audit data."""
        now = now or time.time()
        retention = SIM_DAY_SECONDS
        for resource_jid, entries in list(self.resource_schedules.items()):
            kept = []
            for entry in entries:
                try:
                    end_at = float(entry.get("end_at", entry.get("consultation_end_at", 0)))
                except Exception:
                    end_at = 0
                estado = entry.get("estado")
                if estado in {"agendada", "em curso", "reservada", None} or end_at >= now - retention:
                    kept.append(entry)
            self.resource_schedules[resource_jid] = kept

    def _mark_resource_schedule_state(self, doente_jid, estado):
        changed = False
        for entries in self.resource_schedules.values():
            for entry in entries:
                if entry.get("doente_jid") == doente_jid:
                    entry["estado"] = estado
                    if estado == "concluida":
                        entry["completed_at"] = time.time()
                    changed = True
        allocation = self.alocacoes.get(doente_jid)
        if isinstance(allocation, dict):
            allocation["estado"] = estado
            if estado == "concluida":
                allocation["completed_at"] = time.time()
            changed = True
        return changed

    def _remove_resource_schedule_entries(self, doente_jid):
        removed = False
        for resource_jid, entries in list(self.resource_schedules.items()):
            new_entries = [e for e in entries if not (isinstance(e, dict) and e.get("doente_jid") == doente_jid)]
            if len(new_entries) != len(entries):
                removed = True
            self.resource_schedules[resource_jid] = new_entries
        if doente_jid in self.alocacoes:
            self.alocacoes.pop(doente_jid, None)
            removed = True
        self.pending_routine_patient_ids.discard(doente_jid)
        return removed

    def find_best_routine_slot(self, patient_data):
        """Choose the earliest valid doctor+room slot for a routine consultation."""
        self._cleanup_old_schedule_entries()
        requested_specialty = patient_data.get("especialidade")
        duration = float(CONSULTATION_DURATION_NORMAL_SECONDS)
        now = time.time()

        medicos_candidatos = [
            m_jid
            for m_jid in self._medicos
            if AGENT_REGISTRY.get(m_jid, {}).get("zone") == "normal"
            and AGENT_REGISTRY.get(m_jid, {}).get("specialty") == requested_specialty
            and AGENT_REGISTRY.get(m_jid, {}).get("consult_mode") == "routine"
        ]
        salas_candidatas = [
            s_jid for s_jid in self._salas
            if AGENT_REGISTRY.get(s_jid, {}).get("category") == "routine"
        ]

        best = None
        for medico_jid in medicos_candidatos:
            medico_profile = AGENT_REGISTRY.get(medico_jid, {})
            medico_schedule = self.get_resource_schedule(medico_jid)
            for sala_jid in salas_candidatas:
                sala_schedule = self.get_resource_schedule(sala_jid)
                slot = find_next_routine_slot_for_pair(
                    medico_profile=medico_profile,
                    medico_schedule=medico_schedule,
                    sala_schedule=sala_schedule,
                    earliest_start=now,
                    duration=duration,
                    sim_start_time=self._sim_start_time,
                    lookahead_days=7,
                )
                if not slot:
                    continue
                start_at, end_at = slot
                if not validate_routine_slot(medico_profile, start_at, end_at, self._sim_start_time):
                    continue
                if not is_interval_free(medico_schedule, start_at, end_at, duration):
                    continue
                if not is_interval_free(sala_schedule, start_at, end_at, duration):
                    continue

                # Tie-break: earliest slot first, then distribute load across doctors/rooms.
                key = (
                    start_at,
                    self._active_schedule_count(medico_jid),
                    self._active_schedule_count(sala_jid),
                    medico_jid,
                    sala_jid,
                )
                if best is None or key < best[0]:
                    best = (key, medico_jid, sala_jid, start_at, end_at)

        if best is None:
            return None

        _, medico_jid, sala_jid, start_at, end_at = best
        return {
            "medico_jid": medico_jid,
            "sala_jid": sala_jid,
            "start_at": start_at,
            "end_at": end_at,
            "start_label": sim_time_label(start_at, self._sim_start_time),
            "end_label": sim_time_label(end_at, self._sim_start_time),
            "duration_seconds": duration,
        }

    def reserve_routine_slot(self, doente_jid, allocation, estado="reservada"):
        entry = {
            "doente_jid": doente_jid,
            "nome": allocation["nome"],
            "especialidade": allocation["especialidade"],
            "medico_jid": allocation["medico_jid"],
            "sala_jid": allocation["sala_jid"],
            "start_at": allocation["consultation_start_at"],
            "end_at": allocation["consultation_end_at"],
            "consultation_start_at": allocation["consultation_start_at"],
            "consultation_end_at": allocation["consultation_end_at"],
            "start_label": allocation["hora_inicio_marcada"],
            "end_label": allocation["hora_fim_prevista"],
            "estado": estado,
        }
        self.get_resource_schedule(allocation["medico_jid"]).append(dict(entry))
        self.get_resource_schedule(allocation["sala_jid"]).append(dict(entry))

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
            allocation = self.agent.alocacoes.get(doente_jid)
            if allocation:
                allocation["estado"] = "concluida"
                allocation["completed_at"] = time.time()
                self.agent.historico_alocacoes.append(dict(allocation))
                self.agent._mark_resource_schedule_state(doente_jid, "concluida")
                return True
            return False

        async def publish_waitlist(self):
            scheduled_by_specialty = self.agent.get_scheduled_routine_by_specialty()
            scheduled_patients = [p for plist in scheduled_by_specialty.values() for p in plist]
            msg = Message(to=self.agent._supervisor)
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "waitlist_update")
            msg.body = json.dumps({
                "queue": "routine",
                "patients": self.agent.get_routine_waitlist(),
                "by_specialty": self.agent.get_routine_waitlist_by_specialty(),
                "scheduled": scheduled_patients,
                "scheduled_by_specialty": scheduled_by_specialty,
                "load_metrics": self.agent.get_routine_load_metrics(),
            })
            await self.send(msg)



        async def collect_routine_reservation_confirmations(self, doente_jid, expected_resources):
            """Wait for explicit doctor+room reservation confirmations.

            This keeps the routine scheduler realistic: the coordinator only tells
            the patient that the appointment is fully scheduled after both
            resources acknowledged the future reservation.
            """
            expected = set(expected_resources)
            confirmed = {}
            refused = []
            loop = asyncio.get_running_loop()
            deadline = loop.time() + ROUTINE_RESERVATION_CONFIRM_TIMEOUT_SECONDS

            while expected and loop.time() < deadline:
                remaining = max(0.0, deadline - loop.time())
                msg = await self.receive(timeout=remaining)
                if msg is None:
                    break

                performative = msg.get_metadata("performative")
                msg_type = msg.get_metadata("type")
                try:
                    data = json.loads(msg.body) if msg.body else {}
                except Exception:
                    data = {}

                msg_doente = data.get("doente_jid") or msg.thread
                if msg_doente == doente_jid and msg_type == "reservation_confirmed":
                    resource_jid = data.get("resource_jid") or str(msg.sender)
                    if performative == "inform" and resource_jid in expected:
                        confirmed[resource_jid] = data
                        expected.discard(resource_jid)
                        continue

                if msg_doente == doente_jid and msg_type == "reservation_refused":
                    refused.append(data)
                    continue

                # Do not drop unrelated coordinator messages while waiting for
                # confirmations; process them without dispatching nested batches.
                await self.handle_out_of_band_message(msg)

            return not expected and not refused, {
                "confirmed": confirmed,
                "missing": sorted(expected),
                "refused": refused,
            }

        async def cancel_tentative_routine_reservation(self, allocation, reason="confirmation_failed"):
            doente_jid = allocation.get("doente_jid")
            for resource_jid in [allocation.get("medico_jid"), allocation.get("sala_jid")]:
                if not resource_jid:
                    continue
                msg = Message(to=resource_jid)
                msg.set_metadata("performative", "cancel")
                msg.set_metadata("type", "tentative_reservation_cancel")
                msg.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": allocation.get("nome", "?"),
                    "reason": reason,
                })
                msg.thread = doente_jid
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

        async def process_routine_started(self, data):
            doente_jid = data.get("doente_jid")
            nome = data.get("nome", "?")
            if self.agent._mark_resource_schedule_state(doente_jid, "em curso"):
                allocation = self.agent.alocacoes.get(doente_jid)
                if isinstance(allocation, dict):
                    allocation["actual_start_at"] = data.get("actual_start_at", time.time())
                log(self.agent._coord_name,
                    f"[AGENDA] Consulta de rotina em curso registada no coordenador: {nome}.",
                    "GREEN")

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

            elif performative == "inform" and msg_type == "routine_started":
                data = json.loads(msg.body)
                await self.process_routine_started(data)

            elif performative == "inform" and msg_type == "routine_finished":
                data = json.loads(msg.body)
                await self.process_routine_finished(data, dispatch_after=True)



        async def handle_out_of_band_message(self, msg):
            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "patient_request":
                data = json.loads(msg.body)
                await self.process_patient_request(data, dispatch_after=False)
                return

            if performative == "inform" and msg_type == "routine_started":
                data = json.loads(msg.body)
                await self.process_routine_started(data)
                return

            if performative == "inform" and msg_type == "routine_finished":
                data = json.loads(msg.body)
                await self.process_routine_finished(data, dispatch_after=False)
                return



            if msg_type in {"reservation_confirmed", "reservation_refused"}:
                # Confirmation for another patient or already handled reservation;
                # leave a clear audit trail and continue.
                log(self.agent._coord_name,
                    f"[RESERVA] Confirmação fora de contexto ignorada: type={msg_type}, thread={msg.thread}",
                    "YELLOW")
                return

        async def dispatch_routine_batch(self, max_dispatches=ROUTINE_DISPATCH_BATCH_LIMIT):
            dispatched = 0
            while dispatched < max_dispatches and self.agent.has_pending_requests():
                allocated = await self.dispatch_next_routine()
                if not allocated:
                    break
                dispatched += 1

        async def dispatch_next_routine(self):
            elapsed = time.time() - self.agent._sim_start_time
            current_hour = (elapsed % SIM_DAY_SECONDS) / SIM_HOUR_SECONDS
            
            if not (ROUTINE_START_H <= current_hour < ROUTINE_END_H):
                # Fora do período administrativo das consultas de rotina, os pedidos aguardam
                # pelo próximo intervalo válido de funcionamento.
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
            """Marca uma consulta de rotina usando a agenda centralizada.

            Mantém o nome histórico do método, mas deixa de escolher recursos só
            pela disponibilidade no instante atual. A decisão passa a procurar o
            par médico+sala que tenha o primeiro slot futuro válido, dentro do
            turno real do médico e da janela de consultas externas.
            """
            agent = self.agent
            nome = patient_data["nome"]
            doente_jid = patient_data["doente_jid"]
            requested_specialty = patient_data.get("especialidade")

            slot = agent.find_best_routine_slot(patient_data)
            if slot is None:
                log(agent._coord_name,
                    f"[AGENDA] Sem slot válido de rotina para {nome} "
                    f"(especialidade={requested_specialty}). Pedido mantém-se pendente.",
                    "YELLOW")
                return False

            medico_jid = slot["medico_jid"]
            sala_jid = slot["sala_jid"]
            medico_info = AGENT_REGISTRY.get(medico_jid, {})
            sala_info = AGENT_REGISTRY.get(sala_jid, {})

            allocation = {
                "doente_jid": doente_jid,
                "nome": nome,
                "tipo": "Normal",
                "tipo_original": patient_data.get("tipo_original", patient_data.get("tipo", "Normal")),
                "especialidade": requested_specialty,
                "medico_jid": medico_jid,
                "medico_nome": medico_info.get("name", medico_jid),
                "medico_turno": medico_info.get("shift"),
                "sala_jid": sala_jid,
                "sala_nome": sala_info.get("name", sala_jid),
                "sala_categoria": sala_info.get("category"),
                "consultation_start_at": slot["start_at"],
                "consultation_end_at": slot["end_at"],
                "hora_inicio_marcada": slot["start_label"],
                "hora_fim_prevista": slot["end_label"],
                "estado": "reservada",
                "created_at": time.time(),
            }

            # Reserva local tentativa antes de avisar recursos, para impedir
            # sobreposições no mesmo ciclo. Só passa a "agendada" depois de
            # médico e sala confirmarem explicitamente a reserva.
            agent.alocacoes[doente_jid] = allocation
            agent.reserve_routine_slot(doente_jid, allocation, estado="reservada")

            payload_base = {
                "doente_jid": doente_jid,
                "nome": nome,
                "tipo": "Normal",
                "tipo_original": allocation["tipo_original"],
                "especialidade": requested_specialty,
                "consultation_start_at": allocation["consultation_start_at"],
                "consultation_end_at": allocation["consultation_end_at"],
                "hora_inicio_marcada": allocation["hora_inicio_marcada"],
                "hora_fim_prevista": allocation["hora_fim_prevista"],
                "estado": "reservada",
            }

            acc_m = Message(to=medico_jid)
            acc_m.set_metadata("performative", "accept-proposal")
            acc_m.set_metadata("type", "consultation_schedule")
            acc_m.body = json.dumps({**payload_base, "sala_jid": sala_jid})
            acc_m.thread = doente_jid
            await self.send(acc_m)

            acc_s = Message(to=sala_jid)
            acc_s.set_metadata("performative", "accept-proposal")
            acc_s.set_metadata("type", "consultation_schedule")
            acc_s.body = json.dumps({**payload_base, "medico_jid": medico_jid})
            acc_s.thread = doente_jid
            await self.send(acc_s)

            ok, confirmation_details = await self.collect_routine_reservation_confirmations(
                doente_jid,
                expected_resources={medico_jid, sala_jid},
            )
            if not ok:
                agent._remove_resource_schedule_entries(doente_jid)
                await self.cancel_tentative_routine_reservation(allocation)
                log(agent._coord_name,
                    f"[RESERVA] Falha na confirmação da consulta de rotina para {nome}; "
                    f"missing={confirmation_details.get('missing')} refused={confirmation_details.get('refused')}. "
                    "Pedido mantém-se pendente para nova tentativa.",
                    "YELLOW")
                return False

            agent._mark_resource_schedule_state(doente_jid, "agendada")
            allocation["estado"] = "agendada"

            schedule_msg = Message(to=doente_jid)
            schedule_msg.set_metadata("performative", "inform")
            schedule_msg.set_metadata("type", "consultation_scheduled")
            schedule_msg.body = json.dumps({
                "nome": nome,
                "medico_jid": medico_jid,
                "medico_nome": allocation["medico_nome"],
                "sala_jid": sala_jid,
                "sala_nome": allocation["sala_nome"],
                "especialidade": requested_specialty,
                "consultation_start_at": allocation["consultation_start_at"],
                "consultation_end_at": allocation["consultation_end_at"],
                "hora_inicio_marcada": allocation["hora_inicio_marcada"],
                "hora_fim_prevista": allocation["hora_fim_prevista"],
                "estado": "agendada",
            })
            schedule_msg.thread = doente_jid
            await self.send(schedule_msg)

            log(agent._coord_name,
                f"[AGENDA] Consulta de rotina marcada: {nome} | "
                f"Especialidade={requested_specialty} | "
                f"Médico={allocation['medico_nome']} ({allocation['medico_turno']}) | "
                f"Sala={allocation['sala_nome']} | "
                f"Início={allocation['hora_inicio_marcada']} | "
                f"Fim previsto={allocation['hora_fim_prevista']} | Estado=agendada",
                "BOLD")

            # Regista o atendimento nas métricas usando o slot de início como
            # tempo de início de consulta (não o momento da marcação).
            await agent.notify_metric_attended(
                self,
                doente_jid=doente_jid,
                nome=nome,
                tipo="Normal",
                attended_at=allocation["consultation_start_at"],
            )
            return True

    async def setup(self):
        log(self._coord_name, "Coordenador de Consultas iniciado.", "GREEN")
        self.add_behaviour(self.CoordinatorBehaviour())
