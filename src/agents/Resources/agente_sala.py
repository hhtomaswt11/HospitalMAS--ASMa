import json
import asyncio
import time

from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message

from src.agents.Resources.resource_agent import ResourceAgent

from src.config import *
from src.scheduling import sim_time_label

class AgenteSala(ResourceAgent):
    """
    Manages the temporal availability of a consultation room or clinical specific equipment.
    """
    def __init__(self, agent_jid, password, nome_sala="Sala", **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.nome_sala = nome_sala
        self.next_routine_slot_at = time.time()
        self.agenda = {}

    def get_resource_name(self):
        return self.nome_sala

    class HandleProposalsBehaviour(CyclicBehaviour):
        class ScheduledRoomOccupationBehaviour(OneShotBehaviour):
            def __init__(self, patient_data, start_at):
                super().__init__()
                self.patient_data = patient_data
                self.start_at = start_at
            
            async def run(self):
                delay = max(0.0, self.start_at - time.time())
                if delay > 0:
                    await asyncio.sleep(delay)

                expected_doente = self.patient_data.get("doente_jid")
                if expected_doente not in self.agent.agenda:
                    log(self.agent.nome_sala,
                        f"[AGENDA-IGNORED] Reserva não encontrada na agenda ou cancelada para {self.patient_data.get('nome','?')}; salto do início de ocupação.",
                        "YELLOW")
                    return

                # If the previous appointment is still releasing, wait instead of
                # overlapping two patients in the same room. The routine timetable
                # has operational buffer, so this should be rare.
                while not self.agent.disponivel and self.agent.paciente_atual != expected_doente:
                    await asyncio.sleep(0.2)

                # Activate the reservation and emit status so dashboards reflect
                # the real start time.
                agenda_entry = self.agent.agenda.pop(expected_doente, None) or self.patient_data
                agenda_entry["estado"] = "em curso"
                agenda_entry["actual_start_at"] = time.time()
                if "exam_start_at" in self.patient_data:
                    self.agent.current_assignment_type = "exam"
                elif "surgery_start_at" in self.patient_data:
                    self.agent.current_assignment_type = "surgery"
                else:
                    self.agent.current_assignment_type = "consultation"
                
                self.agent.disponivel = False
                self.agent.paciente_atual = expected_doente
                previsto = self.patient_data.get("hora_inicio_marcada") or sim_time_label(self.start_at, self.agent._sim_start_time)
                actual_start = time.time()
                inicio_real = sim_time_label(actual_start, self.agent._sim_start_time)
                desvio_min = max(0.0, (actual_start - self.start_at) / SIM_HOUR_SECONDS * 60.0)
                log(self.agent.nome_sala,
                    f"[AGENDA] Sala iniciou atendimento para {self.patient_data.get('nome', '?')} | "
                    f"previsto={previsto} | início_real={inicio_real} | desvio={desvio_min:.1f}min_sim.",
                    "BLUE")
                await self.agent.send_status(self)

        async def run(self):
            msg = await self.receive(timeout=RESOURCE_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            agent = self.agent

            if performative == "cfp":
                data = json.loads(msg.body)
                cfp_type = msg.get_metadata("type")
                log(agent.nome_sala, f"[CFP] Call for Proposal received for patient {data.get('nome', '?')}", "MAGENTA")

                reply = msg.make_reply()

                profile = AGENT_REGISTRY.get(str(agent.jid), {})
                category = profile.get("category")
                wing = profile.get("wing")
                room_can_handle = True
                if cfp_type == "consultation_cfp":
                    room_can_handle = category == "routine"
                elif cfp_type == "emergency_cfp":
                    room_can_handle = category == "emergency"
                elif cfp_type == "exam_cfp":
                    room_can_handle = wing == "specialized"
                elif cfp_type == "surgery_cfp":
                    room_can_handle = wing == "surgical"

                if not room_can_handle:
                    reply.set_metadata("performative", "refuse")
                    reply.body = json.dumps({
                        "sala_jid": str(agent.jid),
                        "motivo": f"Sala incompatível com {cfp_type}.",
                        "negotiation_id": data.get("_negotiation_id"),
                    })
                    log(agent.nome_sala, f"[PROPOSAL] CFP recusado: sala incompatível com {cfp_type}.", "YELLOW")
                    await self.send(reply)
                    return

                if cfp_type in ["consultation_cfp", "exam_cfp", "surgery_cfp"]:
                    slot_at = max(time.time(), agent.next_routine_slot_at)
                    
                    preempt_target = None
                    slot_at_urgency = slot_at
                    
                    is_urgent = data.get("tipo_original") != "Normal" and data.get("tipo") != "Normal"
                    if is_urgent and cfp_type in ["exam_cfp", "surgery_cfp"]:
                        my_priority = data.get("prioridade", 999)
                        preemptable_patients = []
                        for k, v in agent.agenda.items():
                            is_routine = v.get("tipo_original") == "Normal" or v.get("tipo") == "Normal"
                            if cfp_type == "exam_cfp":
                                v_priority = 999 if is_routine else v.get("prioridade", 0)
                                if v_priority > my_priority:
                                    preemptable_patients.append(v)
                            else:
                                if is_routine:
                                    preemptable_patients.append(v)
                                    
                        if preemptable_patients:
                            earliest = min(
                                preemptable_patients, 
                                key=lambda x: float(x.get("exam_start_at", x.get("surgery_start_at", float('inf'))))
                            )
                            start_key = "exam_start_at" if cfp_type == "exam_cfp" else "surgery_start_at"
                            if start_key in earliest:
                                preempt_target = earliest.get("doente_jid")
                                slot_at_urgency = float(earliest[start_key])

                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "sala_jid": str(agent.jid),
                        "nome_sala": agent.nome_sala,
                        "slot": "next_available",
                        "slot_at": slot_at,
                        "slot_at_urgency": slot_at_urgency,
                        "preempt_target": preempt_target,
                        "score": max(0.0, slot_at - time.time()),
                        "score_urgency": max(0.0, slot_at_urgency - time.time()),
                        "negotiation_id": data.get("_negotiation_id"),
                    })
                    log(agent.nome_sala, f"[PROPOSAL] Proposal emitted (slot {cfp_type}).", "MAGENTA")
                elif agent.disponivel:
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "sala_jid": str(agent.jid),
                        "nome_sala": agent.nome_sala,
                        "slot": "next_available",
                        "score": 0,
                        "negotiation_id": data.get("_negotiation_id"),
                    })
                    log(agent.nome_sala, "[PROPOSAL] Proposal emitted (Status: Available).", "MAGENTA")
                else:
                    reply.set_metadata("performative", "refuse")
                    reply.body = json.dumps({
                        "sala_jid": str(agent.jid),
                        "motivo": "Room occupied logically.",
                        "negotiation_id": data.get("_negotiation_id"),
                    })
                    log(agent.nome_sala, "[PROPOSAL] CFP rejected (Status: Occupied).", "MAGENTA")
                await self.send(reply)

            elif performative == "accept-proposal":
                data = json.loads(msg.body)
                if "consultation_start_at" in data or "exam_start_at" in data or "surgery_start_at" in data:
                    start_at_key = "consultation_start_at" if "consultation_start_at" in data else "exam_start_at" if "exam_start_at" in data else "surgery_start_at"
                    duration = CONSULTATION_SLOT_SECONDS if start_at_key == "consultation_start_at" else EXAM_DURATION_SECONDS if start_at_key == "exam_start_at" else data.get("surgery_duration_seconds", SURGERY_DURATION_SECONDS)
                    
                    start_at = float(data.get(start_at_key, time.time()))
                    end_at = float(data.get("consultation_end_at", start_at + duration))
                    agent.next_routine_slot_at = max(agent.next_routine_slot_at, end_at)
                    if start_at_key == "consultation_start_at":
                        data.setdefault("consultation_end_at", end_at)
                        data.setdefault("hora_inicio_marcada", sim_time_label(start_at, agent._sim_start_time))
                        data.setdefault("hora_fim_prevista", sim_time_label(end_at, agent._sim_start_time))
                    data["estado"] = "agendada"
                    log(agent.nome_sala,
                        f"[AGENDA] Slot marcado para {data.get('nome', '?')} | "
                        f"início={data.get('hora_inicio_marcada', sim_time_label(start_at, agent._sim_start_time))} | "
                        f"fim={data.get('hora_fim_prevista', sim_time_label(end_at, agent._sim_start_time))}.",
                        "BLUE")
                    
                    # Add to agenda instead of overwriting active state immediately
                    agent.agenda[data.get("doente_jid")] = data

                    # If available, show next patient on dashboard, preserving
                    # the reservation type for safe preemption rules.
                    if agent.disponivel:
                        if start_at_key == "consultation_start_at":
                            agent.current_assignment_type = "consultation_reserved"
                        elif start_at_key == "exam_start_at":
                            agent.current_assignment_type = "exam_reserved"
                        else:
                            agent.current_assignment_type = "surgery_reserved"
                        agent.paciente_atual = data.get("doente_jid")
                        await self.agent.send_status(self)
                    
                    self.agent.add_behaviour(self.ScheduledRoomOccupationBehaviour(data, start_at))

                    if start_at_key == "consultation_start_at":
                        reply = msg.make_reply()
                        reply.set_metadata("performative", "inform")
                        reply.set_metadata("type", "reservation_confirmed")
                        reply.body = json.dumps({
                            "doente_jid": data.get("doente_jid"),
                            "resource_jid": str(agent.jid),
                            "resource_role": "sala",
                            "status": "confirmed",
                            "hora_inicio_marcada": data.get("hora_inicio_marcada"),
                            "hora_fim_prevista": data.get("hora_fim_prevista"),
                        })
                        reply.thread = data.get("doente_jid")
                        await self.send(reply)
                    elif start_at_key in ("exam_start_at", "surgery_start_at"):
                        reply = msg.make_reply()
                        reply.set_metadata("performative", "inform")
                        reply.set_metadata("type", "reservation_confirmed")
                        reply.body = json.dumps({
                            "doente_jid": data.get("doente_jid"),
                            "resource_jid": str(agent.jid),
                            "resource_role": "sala",
                            "slot_type": "exam" if start_at_key == "exam_start_at" else "surgery",
                            "status": "confirmed",
                        })
                        reply.thread = data.get("doente_jid")
                        await self.send(reply)
                else:
                    agent.disponivel = False
                    agent.paciente_atual = data.get("doente_jid")
                    # When directly allocated (e.g., emergency), mark as emergency occupancy
                    agent.current_assignment_type = "emergency"
                    log(agent.nome_sala, f"[ALLOCATION] Allocation ACCEPTED for {data.get('nome', '?')}", "BLUE")
                    await self.agent.send_status(self)

            elif performative == "inform" and msg.get_metadata("type") == "release":
                prev = agent.paciente_atual
                agent.clear_assignment()
                log(agent.nome_sala, f"[LIBERTAÇÃO] Procedimento concluído com sucesso. Instalação livre (doente anterior: {prev}).", "GREEN")
                await self.agent.send_status(self)

            elif performative == "cancel":
                data = json.loads(msg.body)
                doente_jid = data.get("doente_jid")

                if msg.get_metadata("type") == "tentative_reservation_cancel":
                    removed = agent.agenda.pop(doente_jid, None) is not None
                    if agent.paciente_atual == doente_jid and agent.current_assignment_type == "consultation_reserved":
                        agent.clear_assignment()
                        agent.current_assignment_type = None
                    log(agent.nome_sala,
                        f"[RESERVA] Reserva tentativa de sala cancelada para {data.get('nome', doente_jid)}; removed={removed}.",
                        "YELLOW")
                    await self.agent.send_status(self)
                    reply = msg.make_reply()
                    reply.set_metadata("performative", "inform")
                    reply.set_metadata("type", "reservation_cancelled")
                    reply.body = json.dumps({"doente_jid": doente_jid, "resource_jid": str(agent.jid), "status": "cancelled"})
                    reply.thread = doente_jid
                    await self.send(reply)
                    return

                agenda_entry = agent.agenda.get(doente_jid)
                current = getattr(agent, "current_assignment_type", None)
                is_exam_or_surgery_reservation = bool(
                    isinstance(agenda_entry, dict) and (
                        "exam_start_at" in agenda_entry or "surgery_start_at" in agenda_entry
                    )
                )
                is_current_exam_or_surgery = (
                    agent.paciente_atual == doente_jid and current in {"exam", "surgery", "exam_reserved", "surgery_reserved"}
                )

                if is_exam_or_surgery_reservation or is_current_exam_or_surgery:
                    if agenda_entry is not None:
                        agent.agenda.pop(doente_jid, None)
                        log(agent.nome_sala, f"[AGENDA] Reserva de sala para exame/cirurgia {doente_jid} cancelada.", "RED")
                    if is_current_exam_or_surgery:
                        prev = agent.paciente_atual
                        agent.clear_assignment()
                        agent.current_assignment_type = None
                        log(agent.nome_sala, f"[PREEMPÇÃO] Sala libertada de exame/cirurgia (doente anterior: {prev}).", "RED")
                    await self.agent.send_status(self)

                    reply = msg.make_reply()
                    reply.set_metadata("performative", "inform")
                    reply.set_metadata("type", "cancel_confirmed")
                    reply.body = json.dumps({
                        "sala_jid": str(agent.jid),
                        "status": "freed",
                    })
                    await self.send(reply)
                else:
                    log(agent.nome_sala, f"[PREEMPÇÃO-RECUSADA] Cancel ignorado para assignment_type={current}; consultas não são preemptáveis.", "YELLOW")
                    reply = msg.make_reply()
                    reply.set_metadata("performative", "inform")
                    reply.set_metadata("type", "cancel_refused")
                    reply.body = json.dumps({"sala_jid": str(agent.jid), "status": "refused", "reason": "consultations are not preemptable"})
                    await self.send(reply)

            elif performative == "reject-proposal":
                log(agent.nome_sala, "[CONTRACT-NET] Proposta rejeitada pelo coordenador; sala mantém-se livre.", "MAGENTA")

            else:
                log(agent.nome_sala,
                    f"[IGNORADO] Mensagem sem handler explícito: performative={performative}, type={msg.get_metadata('type')}",
                    "YELLOW")

    async def setup(self):
        log(self.nome_sala, f"AgenteSala initialized (available={self.disponivel})", "MAGENTA")
        self.add_behaviour(self.StartupStatusBehaviour())
        self.add_behaviour(self.HandleProposalsBehaviour())
        
