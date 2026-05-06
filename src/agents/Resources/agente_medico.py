import asyncio
import json
import random
import time

from spade.behaviour import CyclicBehaviour, OneShotBehaviour, PeriodicBehaviour
from spade.message import Message

from src.agents.Resources.resource_agent import ResourceAgent
from src.config import *


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

        # ── Scheduling / carga horária ──
        self.role = "medic"
        self.max_weekly_hours = WEEKLY_MAX_HOURS
        self.weekly_hours_used = 0.0
        self._sim_start_time = time.time()
        # Turno inicial vem do AGENT_REGISTRY ("morning" começa em turno, "afternoon" começa fora)
        profile = AGENT_REGISTRY.get(str(agent_jid), {})
        self._shift_type = profile.get("shift", "morning")
        self.on_shift = (self._shift_type == "morning")
        self.emergency_callable = True
        self.current_assignment_type = None

    def get_resource_name(self):
        return self.nome_medico

    def add_hours(self, procedure_type: str):
        """Accumulate simulated weekly hours for a procedure."""
        hours = PROCEDURE_HOURS.get(procedure_type, 1)
        self.weekly_hours_used += hours
        log(self.nome_medico,
            f"[HORAS] {self.nome_medico} acumulou {self.weekly_hours_used:.0f}/{self.max_weekly_hours}h semanais "
            f"(+{hours}h por {procedure_type}).", "YELLOW")

    def is_available_for_cfp(self, cfp_type, patient_data) -> bool:
        """Return True if the doctor can accept this CFP considering schedule/hours."""
        if not self.disponivel:
            return False
        if not self.can_handle_cfp(cfp_type, patient_data):
            return False
        if self.weekly_hours_used >= self.max_weekly_hours:
            log(self.nome_medico,
                f"[HORAS] {self.nome_medico} atingiu limite semanal ({self.weekly_hours_used:.0f}h). CFP recusado.", "RED")
            return False
        is_emergency = cfp_type == "emergency_cfp"
        if not self.on_shift:
            if is_emergency and self.emergency_callable and ALLOW_EMERGENCY_CALL_OUTSIDE_SHIFT:
                log(self.nome_medico,
                    f"[ESCALA] {self.nome_medico} está fora do turno, mas foi chamado para urgência.", "YELLOW")
                return True
            return False
        return True

    def build_proposal_body(self) -> dict:
        return {
            "medico_jid": str(self.jid),
            "nome_medico": self.nome_medico,
            "slot": "next_available",
            "weekly_hours_used": self.weekly_hours_used,
            "max_weekly_hours": self.max_weekly_hours,
            "on_shift": self.on_shift,
            "emergency_callable": self.emergency_callable,
            "score": self._compute_score(),
        }

    def _compute_score(self) -> float:
        """Lower score = more available (coordinators prefer lower)."""
        shift_bonus = 0 if self.on_shift else 10
        return self.weekly_hours_used + shift_bonus

    def get_profile(self):
        return AGENT_REGISTRY.get(str(self.jid), {})

    def can_handle_cfp(self, cfp_type, patient_data):
        profile = self.get_profile()
        zone = profile.get("zone")
        specialty = profile.get("specialty")
        requested_specialty = patient_data.get("especialidade")

        if cfp_type == "consultation_cfp":
            if profile.get("shift") == "night" or profile.get("type") == "Urgencista":
                return False
            return zone == "normal" and specialty == requested_specialty
            
        if cfp_type == "emergency_cfp":
            return zone == "normal" and specialty == requested_specialty
        if cfp_type == "surgery_cfp":
            return zone == "surgical" and specialty == SPECIALTY_CIRURGIA
        if cfp_type == "exam_cfp":
            return zone == "exam" and specialty == requested_specialty
        return False

    def choose_exam_specialty(self):
        return random.choice([SPECIALTY_RX, SPECIALTY_TAC, SPECIALTY_ANALISES])

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
                    "especialidade": exam_specialty,
                    "solicitante": str(self.agent.jid)
                })
                await self.send(msg_exame)

                log(self.agent.nome_medico,
                    f"[TRANSITO] {nome} encaminhado para diagnóstico. A libertar Consultório para novo uso.",
                    "CYAN")

                msg_finish_cons = Message(to=finish_coord)
                msg_finish_cons.set_metadata("performative", "inform")
                msg_finish_cons.set_metadata("type", "routine_finished")
                msg_finish_cons.body = json.dumps({"doente_jid": doente_jid, "nome": nome})
                await self.send(msg_finish_cons)

                mcdt_snapshot = self.agent.mcdt_atual
                self.agent.mcdt_atual = None
                self.agent.disponivel = True
                self.agent.paciente_atual = None
                await self.agent.send_status(self)

                if self.agent.sala_atual:
                    msg_free = Message(to=self.agent.sala_atual)
                    msg_free.set_metadata("performative", "inform")
                    msg_free.set_metadata("type", "release")
                    await self.send(msg_free)
                    self.agent.sala_atual = None

                await asyncio.sleep(EXAM_RESULTS_WAIT_SECONDS)

                if random.random() < PROB_SURGERY_AFTER_EXAM:
                    log(self.agent.nome_medico,
                        f"[CLÍNICA] Resultados de diagnóstico recebidos para {nome}. A solicitar intervenção cirúrgica urgente.",
                        "MAGENTA")
                    if mcdt_snapshot:
                        msg_free_mcdt = Message(to=mcdt_snapshot)
                        msg_free_mcdt.set_metadata("performative", "inform")
                        msg_free_mcdt.set_metadata("type", "release")
                        await self.send(msg_free_mcdt)

                    msg_cirurgia = Message(to=self.agent._coord_cir)
                    msg_cirurgia.set_metadata("performative", "request")
                    msg_cirurgia.set_metadata("type", "surgery_request")
                    msg_cirurgia.body = json.dumps({
                        "doente_jid": doente_jid,
                        "nome": nome,
                        "tipo": "Surgery",
                        "solicitante": str(self.agent.jid)
                    })
                    await self.send(msg_cirurgia)
                else:
                    log(self.agent.nome_medico,
                        f"[CLÍNICA] Resultados de diagnóstico para {nome} normais. Alta médica concedida.",
                        "BLUE")
                    msg_discharge = Message(to=doente_jid)
                    msg_discharge.set_metadata("performative", "inform")
                    msg_discharge.set_metadata("type", "discharge")
                    msg_discharge.body = json.dumps({"estado": "Alta apos exame"})
                    await self.send(msg_discharge)
                    if mcdt_snapshot:
                        msg_free_mcdt = Message(to=mcdt_snapshot)
                        msg_free_mcdt.set_metadata("performative", "inform")
                        msg_free_mcdt.set_metadata("type", "release")
                        await self.send(msg_free_mcdt)
            else:
                if is_urgent:
                    log(self.agent.nome_medico,
                        f"[CLÍNICA] Avaliação urgente para {nome} concluída.", "BLUE")
                else:
                    log(self.agent.nome_medico,
                        f"[CLÍNICA] Consulta de rotina para {nome} concluída. Alta médica concedida.", "BLUE")

                needs_internment = is_urgent and random.random() < PROB_INTERNAMENTO_URGENT

                if needs_internment:
                    msg_int = Message(to=self.agent._coord_int)
                    msg_int.set_metadata("performative", "request")
                    msg_int.set_metadata("type", "internment_request")
                    msg_int.body = json.dumps({
                        "doente_jid": doente_jid,
                        "nome": nome,
                        "solicitante": str(self.agent.jid),
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

                self.agent.disponivel = True
                self.agent.paciente_atual = None
                await self.agent.send_status(self)

                msg_finish_cons = Message(to=finish_coord)
                msg_finish_cons.set_metadata("performative", "inform")
                msg_finish_cons.set_metadata("type", "routine_finished")
                msg_finish_cons.body = json.dumps({"doente_jid": doente_jid, "nome": nome})
                await self.send(msg_finish_cons)

                if self.agent.sala_atual:
                    msg_free_sala = Message(to=self.agent.sala_atual)
                    msg_free_sala.set_metadata("performative", "inform")
                    msg_free_sala.set_metadata("type", "release")
                    await self.send(msg_free_sala)
                    self.agent.sala_atual = None

    class ExecuteProcedureBehaviour(OneShotBehaviour):
        def __init__(self, patient_data):
            super().__init__()
            self.patient_data = patient_data

        async def run(self):
            nome = self.patient_data.get("nome", "?")
            await asyncio.sleep(SURGERY_DURATION_SECONDS)
            log(self.agent.nome_medico,
                f"[CIRURGIA] Procedimento cirúrgico a {nome} concluído. Doente transferido para o recobro.",
                "GREEN")

            self.agent.disponivel = True
            self.agent.paciente_atual = None
            await self.agent.send_status(self)

            if self.agent.bloco_atual:
                msg_free_bloco = Message(to=self.agent.bloco_atual)
                msg_free_bloco.set_metadata("performative", "inform")
                msg_free_bloco.set_metadata("type", "release")
                await self.send(msg_free_bloco)
                self.agent.bloco_atual = None

            msg_int = Message(to=self.agent._coord_int)
            msg_int.set_metadata("performative", "request")
            msg_int.set_metadata("type", "internment_request")
            msg_int.body = json.dumps({
                "doente_jid": self.patient_data.get("doente_jid"),
                "nome": nome,
                "solicitante": str(self.agent.jid),
            })
            await self.send(msg_int)
            log(self.agent.nome_medico, f"[CIRURGIA] Pedido de internamento emitido para {nome}.", "YELLOW")

    class ExecuteExamBehaviour(OneShotBehaviour):
        def __init__(self, patient_data):
            super().__init__()
            self.patient_data = patient_data

        async def run(self):
            nome = self.patient_data.get("nome", "?")
            sala_jid = self.patient_data.get("sala_jid")
            await asyncio.sleep(EXAM_DURATION_SECONDS)
            log(self.agent.nome_medico, f"[EXAME] Exame concluido para {nome}.", "CYAN")
            self.agent.disponivel = True
            self.agent.paciente_atual = None
            await self.agent.send_status(self)
            if sala_jid:
                msg_free = Message(to=sala_jid)
                msg_free.set_metadata("performative", "inform")
                msg_free.set_metadata("type", "release")
                await self.send(msg_free)

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
                await self.send(msg_release)

            done = Message(to=self.agent._coord_int)
            done.set_metadata("performative", "inform")
            done.set_metadata("type", "internment_finished")
            done.body = json.dumps({"doente_jid": self.data.get("doente_jid"), "nome": nome})
            await self.send(done)
            log(self.agent.nome_medico, f"[INTERNAMENTO] Alta automatica concluida para {nome}.", "GREEN")

            msg_discharge = Message(to=self.data.get("doente_jid"))
            msg_discharge.set_metadata("performative", "inform")
            msg_discharge.set_metadata("type", "discharge")
            msg_discharge.body = json.dumps({"estado": "Alta de internamento"})
            await self.send(msg_discharge)

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
                    reply.body = json.dumps(agent.build_proposal_body())
                    log(agent.nome_medico, "[PROPOSAL] Proposal emitted (Status: Available).", "CYAN")
                else:
                    reply.set_metadata("performative", "reject-proposal")
                    reply.body = json.dumps({
                        "medico_jid": str(agent.jid),
                        "motivo": "Resource unavailable for requested zone/specialty/schedule.",
                    })
                    log(agent.nome_medico, "[PROPOSAL] CFP rejected (Status: Occupied/Schedule).", "CYAN")
                await self.send(reply)

            elif performative == "accept-proposal":
                data = json.loads(msg.body)
                agent.disponivel = False
                agent.paciente_atual = data.get("doente_jid")
                agent.sala_atual = data.get("sala_jid")

                sender = str(msg.sender).split("@")[0]

                coord_cons_name = agent._coord_cons.split("@")[0]
                coord_urg_name = agent._coord_urg.split("@")[0]
                coord_cir_name = agent._coord_cir.split("@")[0]
                coord_exam_name = agent._coord_exam.split("@")[0]
                coord_int_name = agent._coord_int.split("@")[0] if hasattr(agent, '_coord_int') else ""

                if sender in [coord_cons_name, coord_urg_name]:
                    proc_type = "emergency" if sender == coord_urg_name else "consultation"
                    agent.current_assignment_type = proc_type
                    agent.add_hours(proc_type)
                    if sender == coord_urg_name and not agent.on_shift:
                        log(agent.nome_medico,
                            f"[URGÊNCIA] Médico selecionado por disponibilidade + especialidade + carga horária.", "RED")
                    log(agent.nome_medico,
                        f"[ALLOCATION] Allocation ACCEPTED for {data.get('nome', '?')}. Initiating consultation.",
                        "BLUE")
                    await self.agent.send_status(self)
                    agent.add_behaviour(agent.EvaluatePatientBehaviour(data))
                elif sender == coord_cir_name:
                    if data.get("sala_jid"):
                        agent.bloco_atual = data.get("sala_jid")
                    agent.current_assignment_type = "surgery"
                    agent.add_hours("surgery")
                    log(agent.nome_medico,
                        f"[ALLOCATION] Surgical Allocation ACCEPTED for {data.get('nome', '?')}. Initiating procedure.",
                        "MAGENTA")
                    await self.agent.send_status(self)
                    agent.add_behaviour(agent.ExecuteProcedureBehaviour(data))
                elif sender == coord_exam_name:
                    agent.current_assignment_type = "exam"
                    agent.add_hours("exam")
                    log(agent.nome_medico,
                        f"[ALLOCATION] Exam Allocation ACCEPTED for {data.get('nome', '?')}. Initiating exam.",
                        "CYAN")
                    await self.agent.send_status(self)
                    agent.add_behaviour(agent.ExecuteExamBehaviour(data))
                elif sender == coord_int_name:
                    agent.current_assignment_type = "internment"
                    agent.add_hours("internment")
                    log(agent.nome_medico,
                        f"[ALLOCATION] Internment Allocation ACCEPTED for {data.get('nome', '?')}. Initiating surveillance.",
                        "YELLOW")
                    await self.agent.send_status(self)
                    agent.add_behaviour(agent.ManageInternmentBehaviour(data))
                else:
                    log(agent.nome_medico, f"[ALLOCATION] Generic allocation accepted.", "BLUE")
                    await self.agent.send_status(self)

            elif performative == "inform" and msg.get_metadata("type") == "allocation_confirmed":
                data = json.loads(msg.body)
                if data["procedure"] == "exam":
                    agent.mcdt_atual = data["sala_jid"]
                    log(agent.nome_medico,
                        f"[SYNC] Confirmation: Equipment {data['sala_jid']} locked for exam.", "CYAN")
                elif data["procedure"] == "surgery":
                    agent.bloco_atual = data["sala_jid"]
                    log(agent.nome_medico,
                        f"[SYNC] Confirmation: Block {data['sala_jid']} locked for surgery.", "MAGENTA")
                elif data["procedure"] == "internment":
                    nome = data.get("nome", "?")
                    log(agent.nome_medico,
                        f"[INTERNAMENTO] Decisão clínica tomada: {nome} internado. "
                        f"Doente sob vigilância de enfermagem. Médico disponível.", "YELLOW")
                    # Doctor is freed — nurse manages the internment duration

            elif performative == "cancel":
                prev = agent.paciente_atual
                agent.disponivel = True
                agent.paciente_atual = None
                agent.sala_atual = None
                agent.current_assignment_type = None
                log(agent.nome_medico,
                    f"[PREEMPTION] Preemption triggered. Resource freed (previous patient ID: {prev}).", "RED")
                await self.agent.send_status(self)

                reply = msg.make_reply()
                reply.set_metadata("performative", "inform")
                reply.set_metadata("type", "cancel_confirmed")
                reply.body = json.dumps({"medico_jid": str(agent.jid), "status": "freed"})
                await self.send(reply)

    class ShiftRotationBehaviour(PeriodicBehaviour):
        """
        Verifica a cada período de tempo em que turno o dia simulado vai.
        """
        async def run(self):
            agent = self.agent
            elapsed = time.time() - agent._sim_start_time
            dia_simulado_s = elapsed % SIM_DAY_SECONDS
            
            if agent._shift_type == "morning":
                should_be_on_shift = (0 <= dia_simulado_s < SHIFT_DURATION_SECONDS)
            elif agent._shift_type == "afternoon":
                should_be_on_shift = (SHIFT_DURATION_SECONDS <= dia_simulado_s < 2 * SHIFT_DURATION_SECONDS)
            else: # night
                should_be_on_shift = (2 * SHIFT_DURATION_SECONDS <= dia_simulado_s)

            if should_be_on_shift != agent.on_shift:
                agent.on_shift = should_be_on_shift
                estado = "ENTROU em turno" if should_be_on_shift else "SAIU do turno"
                log(agent.nome_medico,
                    f"[ESCALA] {agent.nome_medico} {estado} "
                    f"(turno={agent._shift_type}).", "YELLOW")
                await agent.send_status(self)

    class WeeklyResetBehaviour(PeriodicBehaviour):
        """
        Reseta a carga horária semanal.
        """
        async def run(self):
            agent = self.agent
            elapsed = time.time() - agent._sim_start_time
            current_week = int(elapsed // SIM_WEEK_SECONDS)
            if current_week > getattr(agent, 'last_week_reset', 0):
                agent.last_week_reset = current_week
                agent.weekly_hours_used = 0
                log(agent.nome_medico, f"[RESET SEMANAL] {agent.nome_medico} reiniciou as suas {agent.max_weekly_hours}h semanais.", "MAGENTA")
                await agent.send_status(self)

    async def setup(self):
        turno_inicial = "em turno" if self.on_shift else "fora de turno"
        log(self.nome_medico,
            f"AgenteMedico initialized (available={self.disponivel}, "
            f"turno={self._shift_type}, {turno_inicial})", "CYAN")
        self.add_behaviour(self.StartupStatusBehaviour())
        self.add_behaviour(self.HandleProposalsBehaviour())
        self.add_behaviour(self.ShiftRotationBehaviour(period=10))  # verifica a cada 10s
        self.add_behaviour(self.WeeklyResetBehaviour(period=10))
