"""
Layer 1 — Entry & Resource Agents
Classes: AgenteDoente, AgenteTriagem, AgenteMedico, AgenteSala
"""

import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message
from spade.template import Template

from src.config import *


class AgenteDoente(Agent):
    """
    Represents a patient emitting a clinical request.
    """
    def __init__(self, agent_jid, password, nome_doente, tipo_entrada="Normal",
                 sintomas="", prioridade=0, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.nome_doente = nome_doente
        self.tipo_entrada = tipo_entrada
        self.sintomas = sintomas
        self.prioridade = prioridade

    class SendRequestBehaviour(OneShotBehaviour):
        async def run(self):
            agent = self.agent
            body = json.dumps({
                "doente_jid": str(agent.jid),
                "nome": agent.nome_doente,
                "tipo": agent.tipo_entrada,
                "sintomas": agent.sintomas,
                "prioridade": agent.prioridade,
            })

            if agent.tipo_entrada == "Normal":
                dest = jid(COORD_CONS)
                log(agent.nome_doente, f"[PEDIDO] A emitir pedido de consulta de ROTINA para {COORD_CONS}", "GREEN")
            else:
                dest = jid(TRIAGEM)
                log(agent.nome_doente, f"[PEDIDO] A emitir pedido de EMERGÊNCIA para {TRIAGEM} (sintomas: {agent.sintomas})", "RED")

            msg = Message(to=dest)
            msg.body = body
            msg.set_metadata("performative", "request")
            msg.set_metadata("type", "patient_request")
            msg.thread = str(agent.jid)
            await self.send(msg)
            log(agent.nome_doente, "[SUCESSO] Pedido enviado com sucesso.", "GREEN")

    async def setup(self):
        log(self.nome_doente, f"AgenteDoente initialized (type={self.tipo_entrada})", "GREEN")
        self.add_behaviour(self.SendRequestBehaviour())


class AgenteTriagem(Agent):
    """
    Receives emergency patients, evaluates symptoms, and assigns clinical priority.
    """
    class TriageReceiveBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            if performative != "request":
                return

            data = json.loads(msg.body)
            log(TRIAGEM, f"[TRIAGEM] Doente rececionado: {data['nome']} (Sintomas: {data['sintomas']})", "YELLOW")

            data["prioridade"] = 9
            data["triagem_resultado"] = "URGENTE - Elevada Prioridade"
            log(TRIAGEM, f"[TRIAGEM] Avaliação clínica concluída. Prioridade={data['prioridade']} ({data['triagem_resultado']})", "YELLOW")

            msg_urg = Message(to=jid(COORD_URG))
            msg_urg.body = json.dumps(data)
            msg_urg.set_metadata("performative", "request")
            msg_urg.set_metadata("type", "triaged_patient")
            msg_urg.thread = data["doente_jid"]
            await self.send(msg_urg)
            log(TRIAGEM, f"[TRIAGEM] Dados clínicos reencaminhados para {COORD_URG}", "YELLOW")

            alert = Message(to=jid(SUPERVISOR))
            alert.body = json.dumps({
                "alert": "EMERGENCY",
                "doente_jid": data["doente_jid"],
                "nome": data["nome"],
                "prioridade": data["prioridade"],
            })
            alert.set_metadata("performative", "inform")
            alert.set_metadata("type", "emergency_alert")
            alert.thread = data["doente_jid"]
            await self.send(alert)
            log(TRIAGEM, f"[TRIAGEM] Alerta de emergência emitido para a Supervisão {SUPERVISOR}", "RED")

    async def setup(self):
        log(TRIAGEM, "AgenteTriagem initialized.", "YELLOW")
        template = Template()
        template.set_metadata("performative", "request")
        self.add_behaviour(self.TriageReceiveBehaviour(), template)


class AgenteMedico(Agent):
    """
    Manages schedule availability and specialty.
    Responds to CFPs and handles preemption protocols.
    """
    def __init__(self, agent_jid, password, nome_medico="Médico", **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.nome_medico = nome_medico
        self.disponivel = True
        self.paciente_atual = None

    class StartupStatusBehaviour(OneShotBehaviour):
        async def run(self):
            msg = Message(to=jid(SUPERVISOR))
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "resource_status")
            msg.body = json.dumps({
                "recurso_jid": str(self.agent.jid),
                "nome": self.agent.nome_medico,
                "disponivel": self.agent.disponivel,
                "paciente_atual": self.agent.paciente_atual
            })
            await self.send(msg)

    class EvaluatePatientBehaviour(OneShotBehaviour):
        def __init__(self, patient_data):
            super().__init__()
            self.patient_data = patient_data

        async def run(self):
            nome = self.patient_data.get("nome", "?")
            doente_jid = self.patient_data.get("doente_jid")
            
            log(self.agent.nome_medico, f"[CLÍNICA] A iniciar avaliação clínica a {nome}...", "CYAN")
            
            # Arquitetura temporal baseada no Tipo de Entrada: 
            # Consultas normais demoram 15s, Urgências são avaliadas rapidamente em 4s.
            if self.patient_data.get("tipo") == "Normal":
                await asyncio.sleep(15)
            else:
                await asyncio.sleep(4)
            
            # GUARDA DE SEGURANÇA: Se entretanto o médico sofreu preempção e mudou de paciente (emergência entrou), matamos a thread antiga em silêncio!
            if self.agent.paciente_atual != doente_jid:
                return
            
            if "Pedro" in nome:
                log(self.agent.nome_medico, f"[CLÍNICA] Gravidade clínica detetada para {nome}. A solicitar MCDT (Raio-X).", "CYAN")
                
                msg_exame = Message(to=jid(COORD_EXAM))
                msg_exame.set_metadata("performative", "request")
                msg_exame.set_metadata("type", "exam_request")
                msg_exame.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": "Radiography",
                    "solicitante": str(self.agent.jid)
                })
                await self.send(msg_exame)
                
                await asyncio.sleep(6)
                log(self.agent.nome_medico, f"[CLÍNICA] Resultados de diagnóstico recebidos para {nome}. A solicitar intervenção cirúrgica urgente.", "MAGENTA")
                
                # Libertar equipamento de diagnóstico
                msg_free_raiox = Message(to=jid(SALA_RAIOX))
                msg_free_raiox.set_metadata("performative", "inform")
                msg_free_raiox.set_metadata("type", "release")
                await self.send(msg_free_raiox)
                
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

                # Libertar sala de consulta (doente de urgência foi encaminhado para Bloco)
                msg_free_sala_urg = Message(to=jid(SALA1))
                msg_free_sala_urg.set_metadata("performative", "inform")
                msg_free_sala_urg.set_metadata("type", "release")
                await self.send(msg_free_sala_urg)
            else:
                log(self.agent.nome_medico, f"[CLÍNICA] Consulta de rotina para {nome} concluída. Alta médica concedida.", "BLUE")
                self.agent.disponivel = True
                self.agent.paciente_atual = None
                
                msg_status = Message(to=jid(SUPERVISOR))
                msg_status.set_metadata("performative", "inform")
                msg_status.set_metadata("type", "resource_status")
                msg_status.body = json.dumps({
                    "recurso_jid": str(self.agent.jid),
                    "nome": self.agent.nome_medico,
                    "disponivel": True,
                    "paciente_atual": None
                })
                await self.send(msg_status)

                # Libertar sala de consulta normal
                msg_free_sala = Message(to=jid(SALA1))
                msg_free_sala.set_metadata("performative", "inform")
                msg_free_sala.set_metadata("type", "release")
                await self.send(msg_free_sala)

    class ExecuteProcedureBehaviour(OneShotBehaviour):
        def __init__(self, patient_data):
            super().__init__()
            self.patient_data = patient_data

        async def run(self):
            nome = self.patient_data.get("nome", "?")
            await asyncio.sleep(8)
            log(self.agent.nome_medico, f"[CIRURGIA] Procedimento cirúrgico a {nome} concluído. Doente transferido para o recobro.", "GREEN")
            
            self.agent.disponivel = True
            self.agent.paciente_atual = None
            
            msg_status = Message(to=jid(SUPERVISOR))
            msg_status.set_metadata("performative", "inform")
            msg_status.set_metadata("type", "resource_status")
            msg_status.body = json.dumps({
                "recurso_jid": str(self.agent.jid),
                "nome": self.agent.nome_medico,
                "disponivel": True,
                "paciente_atual": None
            })
            await self.send(msg_status)
            
            msg_free_bloco = Message(to=jid(BLOCO_OPERATORIO))
            msg_free_bloco.set_metadata("performative", "inform")
            msg_free_bloco.set_metadata("type", "release")
            await self.send(msg_free_bloco)

    class HandleProposalsBehaviour(CyclicBehaviour):
        async def notificar_status(self):
            msg = Message(to=jid(SUPERVISOR))
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "resource_status")
            msg.body = json.dumps({
                "recurso_jid": str(self.agent.jid),
                "nome": self.agent.nome_medico,
                "disponivel": self.agent.disponivel,
                "paciente_atual": self.agent.paciente_atual
            })
            await self.send(msg)

        async def run(self):
            msg = await self.receive(timeout=10)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            agent = self.agent

            if performative == "cfp":
                data = json.loads(msg.body)
                log(agent.nome_medico, f"[CFP] Call for Proposal received for patient {data.get('nome', '?')}", "CYAN")

                reply = msg.make_reply()
                if agent.disponivel or (agent.paciente_atual == data.get("doente_jid")):
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
                        "motivo": "Resource logically occupied.",
                    })
                    log(agent.nome_medico, "[PROPOSAL] CFP rejected (Status: Occupied).", "CYAN")
                await self.send(reply)

            elif performative == "accept-proposal":
                data = json.loads(msg.body)
                agent.disponivel = False
                agent.paciente_atual = data.get("doente_jid")
                
                sender = str(msg.sender).split("@")[0]
                
                if sender in [COORD_CONS, COORD_URG]:
                    log(agent.nome_medico, f"[ALLOCATION] Allocation ACCEPTED for {data.get('nome', '?')}. Initiating consultation.", "BLUE")
                    await self.notificar_status()
                    agent.add_behaviour(agent.EvaluatePatientBehaviour(data))
                elif sender == COORD_CIR:
                    log(agent.nome_medico, f"[ALLOCATION] Surgical Allocation ACCEPTED for {data.get('nome', '?')}. Initiating procedure.", "MAGENTA")
                    await self.notificar_status()
                    agent.add_behaviour(agent.ExecuteProcedureBehaviour(data))
                else:
                    log(agent.nome_medico, f"[ALLOCATION] Generic allocation accepted.", "BLUE")
                    await self.notificar_status()

            elif performative == "cancel":
                prev = agent.paciente_atual
                agent.disponivel = True
                agent.paciente_atual = None
                log(agent.nome_medico, f"[PREEMPTION] Preemption triggered. Resource freed (previous patient ID: {prev}).", "RED")
                await self.notificar_status()

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


class AgenteSala(Agent):
    """
    Manages the temporal availability of a consultation room or clinical specific equipment.
    """
    def __init__(self, agent_jid, password, nome_sala="Sala", **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.nome_sala = nome_sala
        self.disponivel = True
        self.paciente_atual = None

    class StartupStatusBehaviour(OneShotBehaviour):
        async def run(self):
            msg = Message(to=jid(SUPERVISOR))
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "resource_status")
            msg.body = json.dumps({
                "recurso_jid": str(self.agent.jid),
                "nome": self.agent.nome_sala,
                "disponivel": self.agent.disponivel,
                "paciente_atual": self.agent.paciente_atual
            })
            await self.send(msg)

    class HandleProposalsBehaviour(CyclicBehaviour):
        async def notificar_status(self):
            msg = Message(to=jid(SUPERVISOR))
            msg.set_metadata("performative", "inform")
            msg.set_metadata("type", "resource_status")
            msg.body = json.dumps({
                "recurso_jid": str(self.agent.jid),
                "nome": self.agent.nome_sala,
                "disponivel": self.agent.disponivel,
                "paciente_atual": self.agent.paciente_atual
            })
            await self.send(msg)

        async def run(self):
            msg = await self.receive(timeout=10)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            agent = self.agent

            if performative == "cfp":
                data = json.loads(msg.body)
                log(agent.nome_sala, f"[CFP] Call for Proposal received for patient {data.get('nome', '?')}", "MAGENTA")

                reply = msg.make_reply()
                if agent.disponivel:
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "sala_jid": str(agent.jid),
                        "nome_sala": agent.nome_sala,
                        "slot": "next_available",
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
                agent.disponivel = False
                agent.paciente_atual = data.get("doente_jid")
                log(agent.nome_sala, f"[ALLOCATION] Allocation ACCEPTED for {data.get('nome', '?')}", "BLUE")
                await self.notificar_status()

            elif performative == "inform" and msg.get_metadata("type") == "release":
                prev = agent.paciente_atual
                agent.disponivel = True
                agent.paciente_atual = None
                log(agent.nome_sala, f"[LIBERTAÇÃO] Procedimento concluído com sucesso. Instalação livre (doente anterior: {prev}).", "GREEN")
                await self.notificar_status()

            elif performative == "cancel":
                prev = agent.paciente_atual
                agent.disponivel = True
                agent.paciente_atual = None
                log(agent.nome_sala, f"[PREEMPTION] Preemption triggered. Resource freed (previous patient ID: {prev}).", "RED")
                await self.notificar_status()

                reply = msg.make_reply()
                reply.set_metadata("performative", "inform")
                reply.set_metadata("type", "cancel_confirmed")
                reply.body = json.dumps({
                    "sala_jid": str(agent.jid),
                    "status": "freed",
                })
                await self.send(reply)

    async def setup(self):
        log(self.nome_sala, f"AgenteSala initialized (available={self.disponivel})", "MAGENTA")
        self.add_behaviour(self.StartupStatusBehaviour())
        self.add_behaviour(self.HandleProposalsBehaviour())
