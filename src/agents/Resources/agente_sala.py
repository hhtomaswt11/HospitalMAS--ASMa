import json
import asyncio
import time

from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message

from src.agents.Resources.resource_agent import ResourceAgent

from src.config import *

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

                # At this point the room should already be reserved (disponivel=False
                # and paciente_atual set). Update the assignment type to active and
                # emit status so dashboards reflect the start time.
                self.agent.agenda.pop(expected_doente, None)
                if "exam_start_at" in self.patient_data:
                    self.agent.current_assignment_type = "exam"
                elif "surgery_start_at" in self.patient_data:
                    self.agent.current_assignment_type = "surgery"
                else:
                    self.agent.current_assignment_type = "consultation"
                
                self.agent.disponivel = False
                self.agent.paciente_atual = expected_doente
                log(self.agent.nome_sala,
                    f"[AGENDA] Sala reservada iniciou atendimento para {self.patient_data.get('nome', '?')}.",
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
                    })
                    log(agent.nome_sala, f"[PROPOSAL] Proposal emitted (slot {cfp_type}).", "MAGENTA")
                elif agent.disponivel:
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "sala_jid": str(agent.jid),
                        "nome_sala": agent.nome_sala,
                        "slot": "next_available",
                        "score": 0,
                    })
                    log(agent.nome_sala, "[PROPOSAL] Proposal emitted (Status: Available).", "MAGENTA")
                else:
                    reply.set_metadata("performative", "reject-proposal")
                    reply.body = json.dumps({
                        "sala_jid": str(agent.jid),
                        "motivo": "Room occupied logically.",
                    })
                    log(agent.nome_sala, "[PROPOSAL] CFP rejected (Status: Occupied).", "MAGENTA")
                await self.send(reply)

            elif performative == "accept-proposal":
                data = json.loads(msg.body)
                if "consultation_start_at" in data or "exam_start_at" in data or "surgery_start_at" in data:
                    start_at_key = "consultation_start_at" if "consultation_start_at" in data else "exam_start_at" if "exam_start_at" in data else "surgery_start_at"
                    duration = CONSULTATION_SLOT_SECONDS if start_at_key == "consultation_start_at" else EXAM_DURATION_SECONDS if start_at_key == "exam_start_at" else data.get("surgery_duration_seconds", SURGERY_DURATION_SECONDS)
                    
                    start_at = float(data.get(start_at_key, time.time()))
                    slot_ref = max(start_at, agent.next_routine_slot_at)
                    agent.next_routine_slot_at = slot_ref + duration
                    log(agent.nome_sala,
                        f"[AGENDA] Slot marcado para {data.get('nome', '?')} em {max(0.0, start_at - time.time()):.1f}s.",
                        "BLUE")
                    
                    # Add to agenda instead of overwriting active state immediately
                    agent.agenda[data.get("doente_jid")] = data

                    # If available, show next patient on dashboard
                    if agent.disponivel:
                        agent.current_assignment_type = "reserved"
                        agent.paciente_atual = data.get("doente_jid")
                        await self.agent.send_status(self)
                    
                    self.agent.add_behaviour(self.ScheduledRoomOccupationBehaviour(data, start_at))
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
                
                # Remove from agenda if present
                if doente_jid in agent.agenda:
                    agent.agenda.pop(doente_jid)
                    log(agent.nome_sala, f"[AGENDA] Reserva de sala para {doente_jid} cancelada.", "RED")

                # Only allow preemption for specific procedure types (exams/surgeries)
                allowed_preempt_types = {"exam", "surgery"}
                current = getattr(agent, "current_assignment_type", None)
                if current in allowed_preempt_types:
                    prev = agent.paciente_atual
                    agent.clear_assignment()
                    log(agent.nome_sala, f"[PREEMPTION] Preemption triggered. Resource freed (previous patient ID: {prev}).", "RED")
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
                    log(agent.nome_sala, f"[PREEMPTION-REFUSED] Cancel ignored for assignment_type={current}.", "YELLOW")
                    reply = msg.make_reply()
                    reply.set_metadata("performative", "inform")
                    reply.set_metadata("type", "cancel_refused")
                    reply.body = json.dumps({"sala_jid": str(agent.jid), "status": "refused", "reason": "assignment not preemptable"})
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
        
