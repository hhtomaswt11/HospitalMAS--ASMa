import asyncio
import json
import random

from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message

from src.agents.Resources.resource_agent import ResourceAgent
from src.config import *

class AgenteMedico(ResourceAgent):
    """
    Manages schedule availability and specialty.
    Responds to CFPs and handles preemption protocols.
    """
    def __init__(self, agent_jid, password, nome_medico="Médico", **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.nome_medico = nome_medico
        self.sala_atual = None
        self.mcdt_atual = None
        self.bloco_atual = None

    def get_resource_name(self):
        return self.nome_medico

    def get_profile(self):
        return AGENT_REGISTRY.get(str(self.jid), {})

    def can_handle_cfp(self, cfp_type, patient_data):
        profile = self.get_profile()
        zone = profile.get("zone")
        specialty = profile.get("specialty")
        requested_specialty = patient_data.get("especialidade")

        if cfp_type in {"consultation_cfp", "emergency_cfp"}:
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
            finish_coord = COORD_URG if is_urgent else COORD_CONS
            
            log(self.agent.nome_medico, f"[CLÍNICA] A iniciar avaliação clínica a {nome}...", "CYAN")
            
            # Arquitetura temporal baseada no Tipo de Entrada: 
            # Consultas normais demoram 15s, Urgências são avaliadas rapidamente em 4s.
            if self.patient_data.get("tipo") == "Normal":
                await asyncio.sleep(CONSULTATION_DURATION_NORMAL_SECONDS)
            else:
                await asyncio.sleep(CONSULTATION_DURATION_URGENT_SECONDS)
            
            # GUARDA DE SEGURANÇA: Se entretanto o médico sofreu preempção e mudou de paciente (emergência entrou), matamos a thread antiga em silêncio!
            if self.agent.paciente_atual != doente_jid:
                return
            
            # Lógica probabilística para exames e cirurgia baseada na configuração
            eval_is_urgent = self.patient_data.get("tipo") != "Normal"
            prob_exam = PROB_EXAM_URGENT if eval_is_urgent else PROB_EXAM_NORMAL
            
            if random.random() < prob_exam:
                exam_specialty = self.agent.choose_exam_specialty()
                log(
                    self.agent.nome_medico,
                    f"[CLÍNICA] Gravidade clínica detetada para {nome}. A solicitar MCDT ({exam_specialty}).",
                    "CYAN",
                )
                
                msg_exame = Message(to=jid(COORD_EXAM))
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
                
                log(self.agent.nome_medico, f"[TRANSITO] {nome} encaminhado para diagnóstico. A libertar Consultório para novo uso.", "CYAN")

                msg_finish_cons = Message(to=jid(finish_coord))
                msg_finish_cons.set_metadata("performative", "inform")
                msg_finish_cons.set_metadata("type", "routine_finished")
                msg_finish_cons.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                })
                await self.send(msg_finish_cons)

                # Capturar referência ao equipamento ANTES de libertar o médico,
                # para evitar race-condition se um novo paciente chegar durante o sleep.
                mcdt_snapshot = self.agent.mcdt_atual
                self.agent.mcdt_atual = None

                # O médico de consulta fica livre enquanto o exame decorre noutro recurso.
                self.agent.disponivel = True
                self.agent.paciente_atual = None
                await self.agent.send_status(self)
                
                # 1. Libertar sala de consulta IMEDIATAMENTE (o doente já saiu para o exame)
                if self.agent.sala_atual:
                    msg_free_sala_urg = Message(to=self.agent.sala_atual)
                    msg_free_sala_urg.set_metadata("performative", "inform")
                    msg_free_sala_urg.set_metadata("type", "release")
                    await self.send(msg_free_sala_urg)
                    self.agent.sala_atual = None

                # 2. Aguardar resultados do exame (o Coordenador deve ter alocado o equipamento)
                await asyncio.sleep(EXAM_RESULTS_WAIT_SECONDS)
                
                if random.random() < PROB_SURGERY_AFTER_EXAM:
                    log(self.agent.nome_medico, f"[CLÍNICA] Resultados de diagnóstico recebidos para {nome}. A solicitar intervenção cirúrgica urgente.", "MAGENTA")
                    
                    # 3. Libertar equipamento de diagnóstico (MCDT concluído)
                    if mcdt_snapshot:
                        msg_free_mcdt = Message(to=mcdt_snapshot)
                        msg_free_mcdt.set_metadata("performative", "inform")
                        msg_free_mcdt.set_metadata("type", "release")
                        await self.send(msg_free_mcdt)
                        log(self.agent.nome_medico, f"[SYNC] Equipamento {mcdt_snapshot} libertado.", "CYAN")
                    
                    # 4. Solicitar Bloco Operatório
                    msg_cirurgia = Message(to=jid(COORD_CIR))
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
                    log(self.agent.nome_medico, f"[CLÍNICA] Resultados de diagnóstico para {nome} normais. Alta médica concedida.", "BLUE")
                    
                    # Libertar equipamento de diagnóstico (MCDT concluído)
                    if mcdt_snapshot:
                        msg_free_mcdt = Message(to=mcdt_snapshot)
                        msg_free_mcdt.set_metadata("performative", "inform")
                        msg_free_mcdt.set_metadata("type", "release")
                        await self.send(msg_free_mcdt)
            else:
                if is_urgent:
                    log(self.agent.nome_medico, f"[CLÍNICA] Avaliação urgente para {nome} concluída.", "BLUE")
                else:
                    log(self.agent.nome_medico, f"[CLÍNICA] Consulta de rotina para {nome} concluída. Alta médica concedida.", "BLUE")

                # Decidir internamento ANTES de libertar o médico,
                # para que o médico não receba novo CFP enquanto ainda está a encaminhar o doente.
                needs_internment = is_urgent and random.random() < PROB_INTERNAMENTO_URGENT

                if needs_internment:
                    msg_int = Message(to=jid(COORD_INT))
                    msg_int.set_metadata("performative", "request")
                    msg_int.set_metadata("type", "internment_request")
                    msg_int.body = json.dumps({
                        "doente_jid": doente_jid,
                        "nome": nome,
                        "solicitante": str(self.agent.jid),
                    })
                    await self.send(msg_int)
                    log(self.agent.nome_medico, f"[CLINICA] {nome} encaminhado para internamento.", "YELLOW")
                elif is_urgent:
                    log(self.agent.nome_medico, f"[CLÍNICA] {nome} estabilizado(a). Alta médica concedida.", "BLUE")

                # Agora sim, libertar o médico e notificar o coordenador.
                self.agent.disponivel = True
                self.agent.paciente_atual = None
                await self.agent.send_status(self)

                msg_finish_cons = Message(to=jid(finish_coord))
                msg_finish_cons.set_metadata("performative", "inform")
                msg_finish_cons.set_metadata("type", "routine_finished")
                msg_finish_cons.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                })
                await self.send(msg_finish_cons)

                # Libertar sala de consulta normal
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
            log(self.agent.nome_medico, f"[CIRURGIA] Procedimento cirúrgico a {nome} concluído. Doente transferido para o recobro.", "GREEN")
            
            self.agent.disponivel = True
            self.agent.paciente_atual = None
            
            await self.agent.send_status(self)
            
            if self.agent.bloco_atual:
                msg_free_bloco = Message(to=self.agent.bloco_atual)
                msg_free_bloco.set_metadata("performative", "inform")
                msg_free_bloco.set_metadata("type", "release")
                await self.send(msg_free_bloco)
                log(self.agent.nome_medico, f"[SYNC] Bloco Operatório {self.agent.bloco_atual} libertado.", "GREEN")
                self.agent.bloco_atual = None

            msg_int = Message(to=jid(COORD_INT))
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

            log(self.agent.nome_medico, f"[INTERNAMENTO] {nome} internado por {duration}s em {sala_jid}.", "YELLOW")
            await asyncio.sleep(duration)

            if sala_jid:
                msg_release = Message(to=sala_jid)
                msg_release.set_metadata("performative", "inform")
                msg_release.set_metadata("type", "release")
                await self.send(msg_release)

            done = Message(to=jid(COORD_INT))
            done.set_metadata("performative", "inform")
            done.set_metadata("type", "internment_finished")
            done.body = json.dumps({
                "doente_jid": self.data.get("doente_jid"),
                "nome": nome,
            })
            await self.send(done)
            log(self.agent.nome_medico, f"[INTERNAMENTO] Alta automatica concluida para {nome}.", "GREEN")

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
                log(agent.nome_medico, f"[CFP] Call for Proposal received for patient {data.get('nome', '?')}", "CYAN")

                reply = msg.make_reply()
                if agent.disponivel and agent.can_handle_cfp(cfp_type, data):
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "medico_jid": str(agent.jid),
                        "nome_medico": agent.nome_medico,
                        "slot": "next_available",
                    })
                    log(agent.nome_medico, "[PROPOSAL] Proposal emitted (Status: Available).", "CYAN")
                else:
                    reply.set_metadata("performative", "reject-proposal")
                    reply.body = json.dumps({
                        "medico_jid": str(agent.jid),
                        "motivo": "Resource unavailable for requested zone/specialty.",
                    })
                    log(agent.nome_medico, "[PROPOSAL] CFP rejected (Status: Occupied).", "CYAN")
                await self.send(reply)

            elif performative == "accept-proposal":
                data = json.loads(msg.body)
                agent.disponivel = False
                agent.paciente_atual = data.get("doente_jid")
                agent.sala_atual = data.get("sala_jid")
                
                sender = str(msg.sender).split("@")[0]
                
                if sender in [COORD_CONS, COORD_URG]:
                    log(agent.nome_medico, f"[ALLOCATION] Allocation ACCEPTED for {data.get('nome', '?')}. Initiating consultation.", "BLUE")
                    await self.agent.send_status(self)
                    agent.add_behaviour(agent.EvaluatePatientBehaviour(data))
                elif sender == COORD_CIR:
                    if data.get("sala_jid"):
                        agent.bloco_atual = data.get("sala_jid")
                    log(agent.nome_medico, f"[ALLOCATION] Surgical Allocation ACCEPTED for {data.get('nome', '?')}. Initiating procedure.", "MAGENTA")
                    await self.agent.send_status(self)
                    agent.add_behaviour(agent.ExecuteProcedureBehaviour(data))
                elif sender == COORD_EXAM:
                    log(agent.nome_medico, f"[ALLOCATION] Exam Allocation ACCEPTED for {data.get('nome', '?')}. Initiating exam.", "CYAN")
                    await self.agent.send_status(self)
                    agent.add_behaviour(agent.ExecuteExamBehaviour(data))
                else:
                    log(agent.nome_medico, f"[ALLOCATION] Generic allocation accepted.", "BLUE")
                    await self.agent.send_status(self)

            elif performative == "inform" and msg.get_metadata("type") == "allocation_confirmed":
                data = json.loads(msg.body)
                if data["procedure"] == "exam":
                    agent.mcdt_atual = data["sala_jid"]
                    log(agent.nome_medico, f"[SYNC] Confirmation: Equipment {data['sala_jid']} locked for exam.", "CYAN")
                elif data["procedure"] == "surgery":
                    agent.bloco_atual = data["sala_jid"]
                    log(agent.nome_medico, f"[SYNC] Confirmation: Block {data['sala_jid']} locked for surgery.", "MAGENTA")
                elif data["procedure"] == "internment":
                    agent.add_behaviour(agent.ManageInternmentBehaviour(data))

            elif performative == "cancel":
                prev = agent.paciente_atual
                agent.disponivel = True
                agent.paciente_atual = None
                agent.sala_atual = None
                log(agent.nome_medico, f"[PREEMPTION] Preemption triggered. Resource freed (previous patient ID: {prev}).", "RED")
                await self.agent.send_status(self)

                reply = msg.make_reply()
                reply.set_metadata("performative", "inform")
                reply.set_metadata("type", "cancel_confirmed")
                reply.body = json.dumps({
                    "medico_jid": str(agent.jid),
                    "status": "freed",
                })
                await self.send(reply)

    async def setup(self):
        log(self.nome_medico, f"AgenteMedico initialized (available={self.disponivel})", "CYAN")
        self.add_behaviour(self.StartupStatusBehaviour())
        self.add_behaviour(self.HandleProposalsBehaviour())


