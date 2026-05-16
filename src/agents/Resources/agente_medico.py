import asyncio
import json
import random
import time

from spade.behaviour import CyclicBehaviour, OneShotBehaviour, PeriodicBehaviour
from spade.message import Message

from src.agents.Resources.resource_agent import ResourceAgent
from src.config import *
from src.scheduling import sim_time_label


class AgenteMedico(ResourceAgent):
    """
    Manages schedule availability and specialty.
    Responds to CFPs and handles preemption protocols.
    """
    def __init__(self, agent_jid, password, nome_medico="Médico", hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, hospital_config=hospital_config, **kwargs)
        self.nome_medico = nome_medico
        self.sala_atual = None
        self.mcdt_atual = None
        self.bloco_atual = None
        cfg = hospital_config or H1_CONFIG
        self._coord_cons = cfg["coord_cons"]
        self._coord_urg = cfg["coord_urg"]
        self._coord_exam = cfg["coord_exam"]
        self._coord_cir = cfg["coord_cir"]
        self._coord_int = cfg["coord_int"]

        # ── Atributos específicos do médico ──
        # (max_weekly_hours, weekly_hours_used, _sim_start_time, _shift_type,
        #  on_shift, current_assignment_type já são herdados de ResourceAgent)
        self.role = "medic"
        profile = AGENT_REGISTRY.get(str(agent_jid), {})
        self._profile_cache = profile
        self._consult_mode = profile.get("consult_mode")
        self.consult_mode = self._consult_mode  # Public attribute for status reporting
        self.zone = profile.get("zone")
        self.specialty = profile.get("specialty")
        self.emergency_callable = True
        self.next_routine_slot_at = time.time()
        # Resultados assíncronos recebidos de MCDT/cirurgia, indexados por doente_jid.
        self.pending_exam_results = {}
        self.pending_surgery_results = {}
        # Agenda de consultas marcadas para o futuro (doente_jid -> dados)
        self.agenda = {}

    def get_resource_name(self):
        return self.nome_medico

    def is_available_for_cfp(self, cfp_type, patient_data) -> bool:
        """Return True if the doctor can accept this CFP considering schedule/hours."""
        if not self.can_handle_cfp(cfp_type, patient_data):
            return False
        if self.weekly_hours_used >= self.max_weekly_hours:
            log(self.nome_medico,
                f"[HORAS] {self.nome_medico} atingiu limite semanal ({self.weekly_hours_used:.0f}h). CFP recusado.", "RED")
            return False

        is_emergency = cfp_type == "emergency_cfp"
        is_routine_consultation = cfp_type == "consultation_cfp"
        is_clinical_continuous = cfp_type in {"emergency_cfp", "exam_cfp", "surgery_cfp", "internment_cfp"}

        # A janela 08h-20h só bloqueia consultas de rotina.
        # Exames, cirurgias e internamento fazem parte da continuidade clínica
        # e devem depender da escala/turno/especialidade, não do horário administrativo
        # das consultas externas.
        if is_routine_consultation:
            # Consultas de rotina são agendadas por slot. Um médico pode ter
            # várias marcações futuras; por isso uma reserva pendente não deve
            # bloquear novas propostas de agenda.
            elapsed = time.time() - self._sim_start_time
            current_hour = (elapsed % SIM_DAY_SECONDS) / SIM_HOUR_SECONDS
            if not (ROUTINE_START_H <= current_hour < ROUTINE_END_H):
                log(
                    self.nome_medico,
                    f"[HORAS] {self.nome_medico} recusou consulta de rotina: fora da janela {ROUTINE_START_H}h-{ROUTINE_END_H}h.",
                    "RED",
                )
                return False
            # Rotina também requer estar em turno (não pode ser agendada fora de turno)
            if not self.on_shift:
                log(self.nome_medico,
                    f"[ESCALA] {self.nome_medico} recusou consulta de rotina: fora do turno.",
                    "YELLOW")
                return False
            # If in turno and within hours, routine consultation can be proposed even if ocupado now
            return True

        if cfp_type not in ["exam_cfp", "surgery_cfp", "consultation_cfp"] and not self.disponivel:
            return False

        if not self.on_shift:
            if is_emergency and self.emergency_callable and ALLOW_EMERGENCY_CALL_OUTSIDE_SHIFT:
                log(self.nome_medico,
                    f"[ESCALA] {self.nome_medico} está fora do turno, mas foi chamado para urgência.", "YELLOW")
                return True
            if is_clinical_continuous:
                log(
                    self.nome_medico,
                    f"[ESCALA] {self.nome_medico} recusou {cfp_type}: fora do turno e sem chamada extraordinária aplicável.",
                    "YELLOW",
                )
            return False
        return True

    def build_proposal_body(self, cfp_type=None, patient_data=None) -> dict:
        slot_at = time.time()
        if cfp_type in ["consultation_cfp", "exam_cfp", "surgery_cfp"]:
            slot_at = max(slot_at, self.next_routine_slot_at)

        preempt_target = None
        slot_at_urgency = slot_at
        
        if patient_data:
            is_urgent = patient_data.get("tipo_original") != "Normal" and patient_data.get("tipo") != "Normal"
            if is_urgent and cfp_type in ["exam_cfp", "surgery_cfp"]:
                my_priority = patient_data.get("prioridade", 999)
                preemptable_patients = []
                for k, v in self.agenda.items():
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

        profile = self.get_profile()
        is_nurse = profile.get("role") == "nurse"
        
        return {
            "medico_jid": str(self.jid),
            "nome_medico": self.nome_medico,
            "enfermeiro_jid": str(self.jid) if is_nurse else None,
            "nome_enfermeiro": self.nome_medico if is_nurse else None,
            "slot": "next_available",
            "slot_at": slot_at,
            "slot_at_urgency": slot_at_urgency,
            "preempt_target": preempt_target,
            "weekly_hours_used": self.weekly_hours_used,
            "max_weekly_hours": self.max_weekly_hours,
            "on_shift": self.on_shift,
            "emergency_callable": self.emergency_callable,
            "score": self._compute_score() + (max(0.0, slot_at - time.time()) if cfp_type in ["consultation_cfp", "exam_cfp", "surgery_cfp"] else 0.0),
            "score_urgency": self._compute_score() + (max(0.0, slot_at_urgency - time.time()) if cfp_type in ["consultation_cfp", "exam_cfp", "surgery_cfp"] else 0.0),
            "negotiation_id": patient_data.get("_negotiation_id") if patient_data else None,
        }

    def _compute_score(self) -> float:
        """Lower score = more available (coordinators prefer lower)."""
        shift_bonus = 0 if self.on_shift else 10
        return self.weekly_hours_used + shift_bonus

    def get_profile(self):
        return self._profile_cache

    def can_handle_cfp(self, cfp_type, patient_data):
        profile = self.get_profile()
        zone = profile.get("zone")
        specialty = profile.get("specialty")
        requested_specialty = patient_data.get("especialidade")

        if cfp_type == "consultation_cfp":
            if self._shift_type == "night" or self.get_profile().get("type") == "Urgencista":
                return False
            return self.zone == "normal" and self.specialty == requested_specialty and self._consult_mode == "routine"
            
        if cfp_type == "emergency_cfp":
            # Separação rígida: médicos de rotina nunca fazem urgência e
            # médicos de urgência nunca fazem rotina.
            return self.zone == "normal" and self.specialty == requested_specialty and self._consult_mode == "emergency"
        if cfp_type == "surgery_cfp":
            return self.zone == "surgery" and self.specialty == SPECIALTY_CIRURGIA
        if cfp_type == "exam_cfp":
            return self.zone == "exam" and self.specialty == requested_specialty
        if cfp_type == "internment_cfp":
            return self.get_profile().get("role") == "nurse"
        return False

    def choose_exam_specialty(self):
        return random.choice([SPECIALTY_RX, SPECIALTY_TAC, SPECIALTY_ANALISES])

    async def wait_for_result(self, store: dict, doente_jid: str, timeout: float):
        """Espera por um resultado clínico real colocado pelo comportamento recetor."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if doente_jid in store:
                return store.pop(doente_jid)
            await asyncio.sleep(0.1)
        return None

    class EvaluatePatientBehaviour(OneShotBehaviour):
        def __init__(self, patient_data):
            super().__init__()
            self.patient_data = patient_data

        async def run(self):
            nome = self.patient_data.get("nome", "?")
            doente_jid = self.patient_data.get("doente_jid")
            is_urgent = self.patient_data.get("tipo") == "Urgencia"
            finish_coord = self.agent._coord_urg if is_urgent else self.agent._coord_cons

            log(self.agent.nome_medico, f"[CLÍNICA] A iniciar avaliação clínica a {nome}...", "CYAN")

            if self.patient_data.get("tipo") == "Normal":
                await asyncio.sleep(CONSULTATION_DURATION_NORMAL_SECONDS)
            else:
                await asyncio.sleep(CONSULTATION_DURATION_URGENT_SECONDS)

            if self.agent.paciente_atual != doente_jid:
                return

            eval_is_urgent = self.patient_data.get("tipo") != "Normal"
            prob_exam = PROB_EXAM_URGENT if eval_is_urgent else PROB_EXAM_NORMAL

            if random.random() < prob_exam:
                exam_specialty = self.agent.choose_exam_specialty()
                log(self.agent.nome_medico,
                    f"[CLÍNICA] Gravidade clínica detetada para {nome}. A solicitar MCDT ({exam_specialty}).",
                    "CYAN")

                msg_exame = Message(to=self.agent._coord_exam)
                msg_exame.set_metadata("performative", "request")
                msg_exame.set_metadata("type", "exam_request")
                msg_exame.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": "Exam",
                    "tipo_original": self.patient_data.get("tipo", "Normal"),
                    "especialidade": exam_specialty,
                    "prioridade": self.patient_data.get("prioridade", ROUTINE_SURGERY_PRIORITY),
                    "solicitante": str(self.agent.jid),
                })
                msg_exame.thread = doente_jid
                await self.send(msg_exame)

                log(self.agent.nome_medico,
                    f"[TRANSITO] {nome} encaminhado para diagnóstico. A libertar consultório enquanto aguarda resultado real do MCDT.",
                    "CYAN")

                msg_finish_cons = Message(to=finish_coord)
                msg_finish_cons.set_metadata("performative", "inform")
                msg_finish_cons.set_metadata("type", "routine_finished")
                msg_finish_cons.body = json.dumps({"doente_jid": doente_jid, "nome": nome})
                msg_finish_cons.thread = doente_jid
                await self.send(msg_finish_cons)

                # Prefer the room from the patient payload; fallback to agent state.
                # In some edge cases the scheduled payload may lose sala_jid and the
                # doctor would otherwise fail to release the room.
                sala_consulta = self.patient_data.get("sala_jid") or self.agent.sala_atual
                self.agent.clear_assignment()
                await self.agent.send_status(self)

                if sala_consulta:
                    msg_free = Message(to=sala_consulta)
                    msg_free.set_metadata("performative", "inform")
                    msg_free.set_metadata("type", "release")
                    msg_free.thread = doente_jid
                    await self.send(msg_free)

                exam_result = await self.agent.wait_for_result(
                    self.agent.pending_exam_results,
                    doente_jid,
                    EXAM_RESULT_TIMEOUT_SECONDS,
                )

                if exam_result is None:
                    log(self.agent.nome_medico,
                        f"[SYNC-TIMEOUT] Resultado de MCDT não chegou para {nome}; alta administrativa para evitar bloqueio do fluxo.",
                        "RED")
                    msg_discharge = Message(to=doente_jid)
                    msg_discharge.set_metadata("performative", "inform")
                    msg_discharge.set_metadata("type", "discharge")
                    msg_discharge.body = json.dumps({"estado": "Alta apos timeout de exame"})
                    msg_discharge.thread = doente_jid
                    await self.send(msg_discharge)
                    return

                if exam_result.get("estado") == "exame_falhado":
                    log(self.agent.nome_medico,
                        f"[CLÍNICA] MCDT não realizado para {nome} por indisponibilidade persistente. Alta/observação administrativa.",
                        "RED")
                    msg_discharge = Message(to=doente_jid)
                    msg_discharge.set_metadata("performative", "inform")
                    msg_discharge.set_metadata("type", "discharge")
                    msg_discharge.body = json.dumps({"estado": "Alta/observacao por exame indisponivel"})
                    msg_discharge.thread = doente_jid
                    await self.send(msg_discharge)
                    return

                if exam_result.get("recomenda_cirurgia"):
                    log(self.agent.nome_medico,
                        f"[CLÍNICA] Resultado real de diagnóstico recebido para {nome}. A solicitar intervenção cirúrgica.",
                        "MAGENTA")
                    msg_cirurgia = Message(to=self.agent._coord_cir)
                    msg_cirurgia.set_metadata("performative", "request")
                    msg_cirurgia.set_metadata("type", "surgery_request")
                    msg_cirurgia.body = json.dumps({
                        "doente_jid": doente_jid,
                        "nome": nome,
                        "tipo": "Surgery",
                        "tipo_original": self.patient_data.get("tipo", "Normal"),
                        "prioridade": self.patient_data.get("prioridade", ROUTINE_SURGERY_PRIORITY),
                        "solicitante": str(self.agent.jid),
                        "exam_result": exam_result,
                    })
                    msg_cirurgia.thread = doente_jid
                    await self.send(msg_cirurgia)

                    surgery_result = await self.agent.wait_for_result(
                        self.agent.pending_surgery_results,
                        doente_jid,
                        SURGERY_RESULT_TIMEOUT_SECONDS,
                    )

                    if surgery_result is None:
                        log(self.agent.nome_medico,
                            f"[SYNC-TIMEOUT] Resultado de cirurgia não chegou para {nome}; alta/observação administrativa para evitar bloqueio.",
                            "RED")
                        msg_discharge = Message(to=doente_jid)
                        msg_discharge.set_metadata("performative", "inform")
                        msg_discharge.set_metadata("type", "discharge")
                        msg_discharge.body = json.dumps({"estado": "Alta/observacao por timeout de cirurgia"})
                        msg_discharge.thread = doente_jid
                        await self.send(msg_discharge)
                        return

                    if surgery_result.get("estado") == "cirurgia_concluida":
                        log(self.agent.nome_medico,
                            f"[CLÍNICA] Resultado real de cirurgia recebido para {nome}. Seguimento transferido para recobro/internamento.",
                            "MAGENTA")
                    else:
                        log(self.agent.nome_medico,
                            f"[CLÍNICA] Cirurgia não realizada para {nome} por indisponibilidade persistente. Alta/observação administrativa.",
                            "RED")
                        msg_discharge = Message(to=doente_jid)
                        msg_discharge.set_metadata("performative", "inform")
                        msg_discharge.set_metadata("type", "discharge")
                        msg_discharge.body = json.dumps({"estado": "Alta/observacao por cirurgia indisponivel"})
                        msg_discharge.thread = doente_jid
                        await self.send(msg_discharge)
                else:
                    log(self.agent.nome_medico,
                        f"[CLÍNICA] Resultado real de diagnóstico para {nome} sem indicação cirúrgica. Alta médica concedida.",
                        "BLUE")
                    msg_discharge = Message(to=doente_jid)
                    msg_discharge.set_metadata("performative", "inform")
                    msg_discharge.set_metadata("type", "discharge")
                    msg_discharge.body = json.dumps({"estado": "Alta apos exame"})
                    msg_discharge.thread = doente_jid
                    await self.send(msg_discharge)
            else:
                if is_urgent:
                    log(self.agent.nome_medico,
                        f"[CLÍNICA] Avaliação urgente para {nome} concluída.", "BLUE")
                else:
                    log(self.agent.nome_medico,
                        f"[CLÍNICA] Consulta de rotina para {nome} concluída. Alta médica concedida. Estado=concluída.", "BLUE")

                needs_internment = is_urgent and random.random() < PROB_INTERNAMENTO_URGENT

                if needs_internment:
                    msg_int = Message(to=self.agent._coord_int)
                    msg_int.set_metadata("performative", "request")
                    msg_int.set_metadata("type", "internment_request")
                    msg_int.body = json.dumps({
                        "doente_jid": doente_jid,
                        "nome": nome,
                        "solicitante": str(self.agent.jid),
                        "prioridade": self.patient_data.get("prioridade", 999),
                    })
                    await self.send(msg_int)
                    log(self.agent.nome_medico, f"[CLINICA] {nome} encaminhado para internamento.", "YELLOW")
                else:
                    if is_urgent:
                        log(self.agent.nome_medico,
                            f"[CLÍNICA] {nome} estabilizado(a). Alta médica concedida.", "BLUE")
                    msg_discharge = Message(to=doente_jid)
                    msg_discharge.set_metadata("performative", "inform")
                    msg_discharge.set_metadata("type", "discharge")
                    msg_discharge.body = json.dumps({"estado": "Alta clinica concedida"})
                    await self.send(msg_discharge)

                # Prefer the room from the patient payload; fallback to agent state.
                sala_consulta = self.patient_data.get("sala_jid") or self.agent.sala_atual
                self.agent.clear_assignment()
                await self.agent.send_status(self)

                if not is_urgent:
                    msg_finish_cons = Message(to=finish_coord)
                    msg_finish_cons.set_metadata("performative", "inform")
                    msg_finish_cons.set_metadata("type", "routine_finished")
                    msg_finish_cons.body = json.dumps({"doente_jid": doente_jid, "nome": nome})
                    await self.send(msg_finish_cons)

                if sala_consulta:
                    msg_free_sala = Message(to=sala_consulta)
                    msg_free_sala.set_metadata("performative", "inform")
                    msg_free_sala.set_metadata("type", "release")
                    msg_free_sala.thread = doente_jid
                    await self.send(msg_free_sala)

    class ExecuteProcedureBehaviour(OneShotBehaviour):
        def __init__(self, patient_data):
            super().__init__()
            self.patient_data = patient_data

        async def run(self):
            nome = self.patient_data.get("nome", "?")
            doente_jid = self.patient_data.get("doente_jid")
            bloco = self.agent.bloco_atual or self.patient_data.get("sala_jid")
            duration_sec = self.patient_data.get("surgery_duration_seconds", SURGERY_DURATION_SECONDS)
            await asyncio.sleep(duration_sec)
            log(self.agent.nome_medico,
                f"[CIRURGIA] Procedimento cirúrgico a {nome} concluído. Doente transferido para o recobro.",
                "GREEN")

            if bloco:
                msg_free_bloco = Message(to=bloco)
                msg_free_bloco.set_metadata("performative", "inform")
                msg_free_bloco.set_metadata("type", "release")
                msg_free_bloco.thread = doente_jid
                await self.send(msg_free_bloco)

            self.agent.clear_assignment()
            await self.agent.send_status(self)

            solicitante = self.patient_data.get("solicitante")
            if solicitante:
                result = Message(to=solicitante)
                result.set_metadata("performative", "inform")
                result.set_metadata("type", "surgery_result")
                result.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "estado": "cirurgia_concluida",
                    "sala_jid": bloco,
                })
                result.thread = doente_jid
                await self.send(result)

            msg_int = Message(to=self.agent._coord_int)
            msg_int.set_metadata("performative", "request")
            msg_int.set_metadata("type", "internment_request")
            msg_int.body = json.dumps({
                "doente_jid": doente_jid,
                "nome": nome,
                "solicitante": str(self.agent.jid),
                "prioridade": self.patient_data.get("prioridade", 999),
            })
            msg_int.thread = doente_jid
            await self.send(msg_int)
            log(self.agent.nome_medico, f"[CIRURGIA] Pedido de internamento emitido para {nome}.", "YELLOW")

    class ExecuteExamBehaviour(OneShotBehaviour):
        def __init__(self, patient_data):
            super().__init__()
            self.patient_data = patient_data

        async def run(self):
            nome = self.patient_data.get("nome", "?")
            doente_jid = self.patient_data.get("doente_jid")
            sala_jid = self.patient_data.get("sala_jid")
            await asyncio.sleep(EXAM_DURATION_SECONDS)
            recomenda_cirurgia = random.random() < PROB_SURGERY_AFTER_EXAM
            log(self.agent.nome_medico,
                f"[EXAME] Exame concluído para {nome}. Recomenda cirurgia={recomenda_cirurgia}.",
                "CYAN")

            solicitante = self.patient_data.get("solicitante")
            if solicitante:
                result = Message(to=solicitante)
                result.set_metadata("performative", "inform")
                result.set_metadata("type", "exam_result")
                result.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "especialidade": self.patient_data.get("especialidade"),
                    "estado": "exame_concluido",
                    "sala_jid": sala_jid,
                    "medico_exame": str(self.agent.jid),
                    "recomenda_cirurgia": recomenda_cirurgia,
                })
                result.thread = doente_jid
                await self.send(result)

            if sala_jid:
                msg_free = Message(to=sala_jid)
                msg_free.set_metadata("performative", "inform")
                msg_free.set_metadata("type", "release")
                msg_free.thread = doente_jid
                await self.send(msg_free)

            self.agent.clear_assignment()
            await self.agent.send_status(self)

    class ManageInternmentBehaviour(OneShotBehaviour):
        def __init__(self, data):
            super().__init__()
            self.data = data

        async def run(self):
            sala_jid = self.data.get("sala_jid")
            nome = self.data.get("nome", "?")
            duration = int(self.data.get("duration", INTERNAMENTO_MIN_SECONDS))

            log(self.agent.nome_medico,
                f"[INTERNAMENTO] {nome} internado por {duration}s em {sala_jid}.", "YELLOW")
            await asyncio.sleep(duration)

            if sala_jid:
                msg_release = Message(to=sala_jid)
                msg_release.set_metadata("performative", "inform")
                msg_release.set_metadata("type", "release")
                msg_release.thread = self.data.get("doente_jid")
                await self.send(msg_release)

            self.agent.clear_assignment()
            await self.agent.send_status(self)

            done = Message(to=self.agent._coord_int)
            done.set_metadata("performative", "inform")
            done.set_metadata("type", "internment_finished")
            done.body = json.dumps({"doente_jid": self.data.get("doente_jid"), "nome": nome})
            done.thread = self.data.get("doente_jid")
            await self.send(done)
            log(self.agent.nome_medico, f"[INTERNAMENTO] Alta automatica concluida para {nome}.", "GREEN")

            msg_discharge = Message(to=self.data.get("doente_jid"))
            msg_discharge.set_metadata("performative", "inform")
            msg_discharge.set_metadata("type", "discharge")
            msg_discharge.body = json.dumps({"estado": "Alta de internamento"})
            msg_discharge.thread = self.data.get("doente_jid")
            await self.send(msg_discharge)

    class ScheduledConsultationBehaviour(OneShotBehaviour):
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
                log(self.agent.nome_medico,
                    f"[AGENDA-IGNORED] Reserva não encontrada na agenda ou cancelada para {self.patient_data.get('nome','?')}; salto do início de consulta.",
                    "YELLOW")
                return

            # Se o médico ainda estiver ocupado no instante marcado, aguarda
            # libertação. A folga entre slots reduz este caso, mas a espera evita
            # sobreposição real de consultas quando há atrasos assíncronos.
            while not self.agent.disponivel:
                await asyncio.sleep(0.2)

            # Activate the reservation: mark as active consultation and start.
            agenda_entry = self.agent.agenda.pop(expected_doente, None) or self.patient_data
            agenda_entry["estado"] = "em curso"
            agenda_entry["actual_start_at"] = time.time()
            self.agent.disponivel = False
            self.agent.paciente_atual = expected_doente
            self.agent.sala_atual = self.patient_data.get("sala_jid")
            self.agent.current_assignment_type = "consultation"
            self.agent.add_hours("consultation")
            await self.agent.send_status(self)

            nome = self.patient_data.get("nome", "?")
            previsto = self.patient_data.get("hora_inicio_marcada") or sim_time_label(self.start_at, self.agent._sim_start_time)
            fim_previsto = self.patient_data.get("hora_fim_prevista")
            actual_start = time.time()
            inicio_real = sim_time_label(actual_start, self.agent._sim_start_time)
            desvio_min = max(0.0, (actual_start - self.start_at) / SIM_HOUR_SECONDS * 60.0)
            log(self.agent.nome_medico,
                f"[AGENDA] Início real da consulta de rotina: {nome} | "
                f"previsto={previsto} | início_real={inicio_real} | "
                f"desvio={desvio_min:.1f}min_sim | fim_previsto={fim_previsto} | Estado=em curso.",
                "GREEN")

            # Atualiza também o coordenador para que a alocação central passe
            # de "agendada" para "em curso". Assim o estado completo existe
            # no coordenador, não apenas no agente médico/sala.
            started = Message(to=self.agent._coord_cons)
            started.set_metadata("performative", "inform")
            started.set_metadata("type", "routine_started")
            started.body = json.dumps({
                "doente_jid": expected_doente,
                "nome": nome,
                "actual_start_at": actual_start,
                "estado": "em curso",
            })
            started.thread = expected_doente
            await self.send(started)

            self.agent.add_behaviour(self.agent.EvaluatePatientBehaviour(self.patient_data))

    class ScheduledExamBehaviour(OneShotBehaviour):
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
                log(self.agent.nome_medico,
                    f"[AGENDA-IGNORED] Reserva não encontrada na agenda ou cancelada para {self.patient_data.get('nome','?')}; salto do início de exame.",
                    "YELLOW")
                return

            while not self.agent.disponivel:
                await asyncio.sleep(0.2)

            self.agent.agenda.pop(expected_doente, None)
            self.agent.disponivel = False
            self.agent.paciente_atual = expected_doente
            self.agent.sala_atual = self.patient_data.get("sala_jid")
            self.agent.current_assignment_type = "exam"
            self.agent.add_hours("exam")
            await self.agent.send_status(self)

            nome = self.patient_data.get("nome", "?")
            log(self.agent.nome_medico,
                f"[AGENDA] Início do exame agendado para {nome}.",
                "CYAN")
            self.agent.add_behaviour(self.agent.ExecuteExamBehaviour(self.patient_data))

    class ScheduledSurgeryBehaviour(OneShotBehaviour):
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
                log(self.agent.nome_medico,
                    f"[AGENDA-IGNORED] Reserva não encontrada na agenda ou cancelada para {self.patient_data.get('nome','?')}; salto do início de cirurgia.",
                    "YELLOW")
                return

            while not self.agent.disponivel:
                await asyncio.sleep(0.2)

            self.agent.agenda.pop(expected_doente, None)
            self.agent.disponivel = False
            self.agent.paciente_atual = expected_doente
            self.agent.sala_atual = self.patient_data.get("sala_jid")
            if self.patient_data.get("sala_jid"):
                self.agent.bloco_atual = self.patient_data.get("sala_jid")
            self.agent.current_assignment_type = "surgery"
            duration_hr = self.patient_data.get("surgery_duration_hours")
            self.agent.add_hours("surgery", duration_hr)
            await self.agent.send_status(self)

            nome = self.patient_data.get("nome", "?")
            log(self.agent.nome_medico,
                f"[AGENDA] Início da cirurgia agendada para {nome}.",
                "MAGENTA")
            self.agent.add_behaviour(self.agent.ExecuteProcedureBehaviour(self.patient_data))

    class HandleProposalsBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=RESOURCE_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            agent = self.agent

            if performative == "cfp":
                data = json.loads(msg.body)
                cfp_type = msg.get_metadata("type")
                log(agent.nome_medico,
                    f"[CFP] Call for Proposal received for patient {data.get('nome', '?')}", "CYAN")

                reply = msg.make_reply()
                if agent.is_available_for_cfp(cfp_type, data):
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps(agent.build_proposal_body(cfp_type, data))
                    log(agent.nome_medico, "[PROPOSAL] Proposal emitted (Status: Available).", "CYAN")
                else:
                    reply.set_metadata("performative", "refuse")
                    reply.body = json.dumps({
                        "medico_jid": str(agent.jid),
                        "motivo": "Resource unavailable for requested zone/specialty/schedule.",
                        "negotiation_id": data.get("_negotiation_id"),
                    })
                    log(agent.nome_medico, "[PROPOSAL] CFP refused (Status: Occupied/Schedule).", "CYAN")
                await self.send(reply)

            elif performative == "accept-proposal":
                data = json.loads(msg.body)
                msg_type = msg.get_metadata("type")

                sender = str(msg.sender).split("@")[0]

                coord_cons_name = agent._coord_cons.split("@")[0]
                coord_urg_name = agent._coord_urg.split("@")[0]
                coord_cir_name = agent._coord_cir.split("@")[0]
                coord_exam_name = agent._coord_exam.split("@")[0]
                coord_int_name = agent._coord_int.split("@")[0] if hasattr(agent, '_coord_int') else ""

                if sender in [coord_cons_name, coord_urg_name]:
                    if sender == coord_cons_name or msg_type == "consultation_schedule":
                        start_at = float(data.get("consultation_start_at", time.time()))
                        end_at = float(data.get("consultation_end_at", start_at + CONSULTATION_SLOT_SECONDS))
                        agent.next_routine_slot_at = max(agent.next_routine_slot_at, end_at)
                        data.setdefault("consultation_end_at", end_at)
                        data.setdefault("hora_inicio_marcada", sim_time_label(start_at, agent._sim_start_time))
                        data.setdefault("hora_fim_prevista", sim_time_label(end_at, agent._sim_start_time))
                        data["estado"] = "agendada"
                        log(agent.nome_medico,
                            f"[AGENDA] Consulta de rotina agendada para {data.get('nome', '?')} | "
                            f"início={data.get('hora_inicio_marcada')} | fim={data.get('hora_fim_prevista')}.",
                            "GREEN")
                        
                        # Add to agenda instead of overwriting active state
                        agent.agenda[data.get("doente_jid")] = data
                        
                        # If not busy, update status fields so dashboard shows the next patient
                        # but don't set disponivel=False yet.
                        if agent.disponivel:
                            agent.current_assignment_type = "consultation_reserved"
                            agent.paciente_atual = data.get("doente_jid")
                            agent.sala_atual = data.get("sala_jid")
                            await self.agent.send_status(self)
                        
                        agent.add_behaviour(agent.ScheduledConsultationBehaviour(data, start_at))

                        reply = msg.make_reply()
                        reply.set_metadata("performative", "inform")
                        reply.set_metadata("type", "reservation_confirmed")
                        reply.body = json.dumps({
                            "doente_jid": data.get("doente_jid"),
                            "resource_jid": str(agent.jid),
                            "resource_role": "medico",
                            "status": "confirmed",
                            "hora_inicio_marcada": data.get("hora_inicio_marcada"),
                            "hora_fim_prevista": data.get("hora_fim_prevista"),
                        })
                        reply.thread = data.get("doente_jid")
                        await self.send(reply)
                    else:
                        agent.disponivel = False
                        agent.paciente_atual = data.get("doente_jid")
                        agent.sala_atual = data.get("sala_jid")
                        proc_type = "emergency"
                        agent.current_assignment_type = proc_type
                        agent.add_hours(proc_type)
                        if not agent.on_shift:
                            log(agent.nome_medico,
                                "[URGÊNCIA] Médico selecionado por disponibilidade + especialidade + carga horária.", "RED")
                        log(agent.nome_medico,
                            f"[ALLOCATION] Allocation ACCEPTED for {data.get('nome', '?')}. Initiating consultation.",
                            "BLUE")
                        await self.agent.send_status(self)
                        agent.add_behaviour(agent.EvaluatePatientBehaviour(data))
                elif sender == coord_cir_name:
                    start_at = float(data.get("surgery_start_at", time.time()))
                    duration_sec = float(data.get("surgery_duration_seconds", SURGERY_DURATION_SECONDS))
                    slot_ref = max(start_at, agent.next_routine_slot_at)
                    agent.next_routine_slot_at = slot_ref + duration_sec
                    log(agent.nome_medico,
                        f"[AGENDA] Cirurgia agendada para {data.get('nome', '?')} em {max(0.0, start_at - time.time()):.1f}s.",
                        "MAGENTA")
                    agent.agenda[data.get("doente_jid")] = data
                    if agent.disponivel:
                        agent.current_assignment_type = "surgery_reserved"
                        agent.paciente_atual = data.get("doente_jid")
                        agent.sala_atual = data.get("sala_jid")
                        await self.agent.send_status(self)
                    agent.add_behaviour(agent.ScheduledSurgeryBehaviour(data, start_at))
                    reply = msg.make_reply()
                    reply.set_metadata("performative", "inform")
                    reply.set_metadata("type", "reservation_confirmed")
                    reply.body = json.dumps({
                        "doente_jid": data.get("doente_jid"),
                        "resource_jid": str(agent.jid),
                        "resource_role": "medico",
                        "slot_type": "surgery",
                        "status": "confirmed",
                    })
                    reply.thread = data.get("doente_jid")
                    await self.send(reply)

                elif sender == coord_exam_name:
                    start_at = float(data.get("exam_start_at", time.time()))
                    slot_ref = max(start_at, agent.next_routine_slot_at)
                    agent.next_routine_slot_at = slot_ref + EXAM_DURATION_SECONDS
                    log(agent.nome_medico,
                        f"[AGENDA] Exame agendado para {data.get('nome', '?')} em {max(0.0, start_at - time.time()):.1f}s.",
                        "CYAN")
                    agent.agenda[data.get("doente_jid")] = data
                    if agent.disponivel:
                        agent.current_assignment_type = "exam_reserved"
                        agent.paciente_atual = data.get("doente_jid")
                        agent.sala_atual = data.get("sala_jid")
                        await self.agent.send_status(self)
                    agent.add_behaviour(agent.ScheduledExamBehaviour(data, start_at))
                    reply = msg.make_reply()
                    reply.set_metadata("performative", "inform")
                    reply.set_metadata("type", "reservation_confirmed")
                    reply.body = json.dumps({
                        "doente_jid": data.get("doente_jid"),
                        "resource_jid": str(agent.jid),
                        "resource_role": "medico",
                        "slot_type": "exam",
                        "status": "confirmed",
                    })
                    reply.thread = data.get("doente_jid")
                    await self.send(reply)

                elif sender == coord_int_name:
                    agent.disponivel = False
                    agent.paciente_atual = data.get("doente_jid")
                    agent.sala_atual = data.get("sala_jid")
                    agent.current_assignment_type = "internment"
                    agent.add_hours("internment")
                    log(agent.nome_medico,
                        f"[ALLOCATION] Internment Allocation ACCEPTED for {data.get('nome', '?')}. Initiating surveillance.",
                        "YELLOW")
                    await self.agent.send_status(self)
                    agent.add_behaviour(agent.ManageInternmentBehaviour(data))
                else:
                    log(agent.nome_medico, f"[ALLOCATION] Generic allocation accepted from {sender}.", "BLUE")
                    await self.agent.send_status(self)

            elif performative == "cancel":
                data = json.loads(msg.body)
                doente_jid = data.get("doente_jid")

                if msg.get_metadata("type") == "tentative_reservation_cancel":
                    removed = agent.agenda.pop(doente_jid, None) is not None
                    if agent.paciente_atual == doente_jid and agent.current_assignment_type == "consultation_reserved":
                        agent.clear_assignment()
                        agent.current_assignment_type = None
                    log(agent.nome_medico,
                        f"[RESERVA] Reserva tentativa de rotina cancelada para {data.get('nome', doente_jid)}; removed={removed}.",
                        "YELLOW")
                    await agent.send_status(self)
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

                # O professor pediu preempção apenas em exames/cirurgias.
                # Cancels sobre consultas de rotina são recusados para não quebrar a agenda.
                if is_exam_or_surgery_reservation or is_current_exam_or_surgery:
                    if agenda_entry is not None:
                        agent.agenda.pop(doente_jid, None)
                        log(agent.nome_medico, f"[AGENDA] Exame/cirurgia para {doente_jid} cancelado por preempção.", "RED")
                    if is_current_exam_or_surgery:
                        prev = agent.paciente_atual
                        agent.clear_assignment()
                        agent.current_assignment_type = None
                        log(agent.nome_medico,
                            f"[PREEMPÇÃO] Recurso médico libertado de exame/cirurgia (doente anterior: {prev}).", "RED")
                    await agent.send_status(self)
                    reply = msg.make_reply()
                    reply.set_metadata("performative", "inform")
                    reply.set_metadata("type", "cancel_confirmed")
                    reply.body = json.dumps({"medico_jid": str(agent.jid), "status": "freed"})
                    await self.send(reply)
                else:
                    log(agent.nome_medico,
                        f"[PREEMPÇÃO-RECUSADA] Cancel ignorado para assignment_type={current}; consultas não são preemptáveis.",
                        "YELLOW")
                    reply = msg.make_reply()
                    reply.set_metadata("performative", "inform")
                    reply.set_metadata("type", "cancel_refused")
                    reply.body = json.dumps({"medico_jid": str(agent.jid), "status": "refused", "reason": "consultations are not preemptable"})
                    await self.send(reply)

            elif performative == "inform" and msg.get_metadata("type") == "allocation_confirmed":
                data = json.loads(msg.body)
                if data["procedure"] == "exam":
                    log(agent.nome_medico,
                        f"[SYNC] MCDT alocado para {data.get('doente_jid', '?')}: equipamento={data.get('sala_jid', '?')}. A aguardar exam_result real.",
                        "CYAN")
                elif data["procedure"] == "surgery":
                    log(agent.nome_medico,
                        f"[SYNC] Cirurgia alocada para {data.get('doente_jid', '?')}: bloco={data.get('sala_jid', '?')}. A execução termina via surgery_result.",
                        "MAGENTA")
                elif data["procedure"] == "internment":
                    nome = data.get("nome", "?")
                    log(agent.nome_medico,
                        f"[INTERNAMENTO] Decisão clínica tomada: {nome} internado. "
                        f"Doente sob vigilância de enfermagem. Médico disponível.", "YELLOW")

            elif performative == "inform" and msg.get_metadata("type") == "exam_result":
                data = json.loads(msg.body)
                key = data.get("doente_jid") or msg.thread
                if key:
                    agent.pending_exam_results[key] = data
                    log(agent.nome_medico,
                        f"[SYNC] Resultado real de MCDT recebido para {data.get('nome', key)}.",
                        "CYAN")

            elif performative == "inform" and msg.get_metadata("type") == "surgery_result":
                data = json.loads(msg.body)
                key = data.get("doente_jid") or msg.thread
                if key:
                    agent.pending_surgery_results[key] = data
                log(agent.nome_medico,
                    f"[SYNC] Resultado de cirurgia recebido para {data.get('nome', key)}.",
                    "MAGENTA")

            elif performative == "inform" and msg.get_metadata("type") == "internment_failed":
                data = json.loads(msg.body)
                log(agent.nome_medico,
                    f"[INTERNAMENTO] Internamento indisponível para {data.get('nome', data.get('doente_jid', '?'))}; doente já foi notificado para alta/observação.",
                    "RED")

            elif performative == "reject-proposal":
                log(agent.nome_medico,
                    "[CONTRACT-NET] Proposta rejeitada pelo coordenador; médico mantém-se livre.",
                    "CYAN")

            else:
                log(agent.nome_medico,
                    f"[IGNORADO] Mensagem sem handler explícito: performative={performative}, type={msg.get_metadata('type')}",
                    "YELLOW")

    async def setup(self):
        turno_inicial = "em turno" if self.on_shift else "fora de turno"
        log(self.nome_medico,
            f"AgenteMedico initialized (available={self.disponivel}, "
            f"turno={self._shift_type}, {turno_inicial})", "CYAN")
        self.add_behaviour(self.StartupStatusBehaviour())
        self.add_behaviour(self.HandleProposalsBehaviour())
        self.add_behaviour(self.ShiftRotationBehaviour(period=10))  # verifica a cada 10s
        self.add_behaviour(self.WeeklyResetBehaviour(period=10))
