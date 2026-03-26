# camada2_coordenacao.py
# -*- coding: utf-8 -*-
"""
Layer 2 — Coordination Motor
"""

import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *


# ============================================================================
# COORDENADOR DE CONSULTAS (Fluxo Normal)
# ============================================================================
class CoordenadorConsultas(Agent):
    """
    Receives routine consultation requests and negotiates.
    """

    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.alocacoes = {}         # doente_jid → {medico, sala, nome}
        self.pending_requests = []  # fila de pedidos pendentes

    class CoordinatorBehaviour(CyclicBehaviour):


        async def run(self):
            msg = await self.receive(timeout=5)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            # ---- Pedido de consulta normal ----
            if performative == "request" and msg_type == "patient_request":
                data = json.loads(msg.body)
                log(COORD_CONS,
                    f"[PEDIDO] Pedido de consulta de rotina recebido: {data['nome']}",
                    "GREEN")
                await self.run_contract_net(data)

            # ---- Ordem de preemption do Supervisor ----
            elif performative == "request" and msg_type == "preemption_order":
                data = json.loads(msg.body)
                await self.handle_preemption(data)

        # -----------------------------------------------------------------
        # CONTRACT-NET: CFP → Recolher propostas → Adjudicar
        # -----------------------------------------------------------------
        async def run_contract_net(self, patient_data):
            """Executa o protocolo Contract-Net para alocar médico + sala."""
            agent = self.agent
            nome = patient_data["nome"]
            doente_jid = patient_data["doente_jid"]

            log(COORD_CONS,
                f"[CONTRACT-NET] A iniciar negociação para {nome}...", "GREEN")

            # 1) Enviar CFP a todos os Médicos
            for m_jid in MEDICOS:
                cfp = Message(to=m_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "consultation_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_CONS, f"[CFP] Call for Proposal enviado ao médico {m_jid}", "GREEN")

            # 2) Enviar CFP a todas as Salas
            for s_jid in SALAS:
                cfp = Message(to=s_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "consultation_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_CONS, f"[CFP] Call for Proposal enviado à sala {s_jid}", "GREEN")

            # 3) Aguardar e recolher propostas
            await asyncio.sleep(2)  # tempo para respostas chegarem

            medico_proposta = None
            sala_proposta = None
            expected_replies = len(MEDICOS) + len(SALAS)

            for _ in range(expected_replies):
                reply = await self.receive(timeout=3)
                if reply is None:
                    continue

                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)

                if perf == "propose":
                    if "medico_jid" in body:
                        medico_proposta = body
                        log(COORD_CONS,
                            f"Proposta de médico recebida: "
                            f"{body['nome_medico']}", "GREEN")
                    elif "sala_jid" in body:
                        sala_proposta = body
                        log(COORD_CONS,
                            f"Proposta de sala recebida: "
                            f"{body['nome_sala']}", "GREEN")
                elif perf == "reject-proposal":
                    log(COORD_CONS,
                        f"[PROPOSTA] Proposta rejeitada: {body.get('motivo', '?')}",
                        "YELLOW")

            # 4) Adjudicar ou recusar
            if medico_proposta and sala_proposta:
                # Aceitar médico
                acc_m = Message(to=medico_proposta["medico_jid"])
                acc_m.set_metadata("performative", "accept-proposal")
                acc_m.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": patient_data.get("tipo", "Normal")
                })
                acc_m.thread = doente_jid
                await self.send(acc_m)

                # Aceitar sala
                acc_s = Message(to=sala_proposta["sala_jid"])
                acc_s.set_metadata("performative", "accept-proposal")
                acc_s.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": patient_data.get("tipo", "Normal")
                })
                acc_s.thread = doente_jid
                await self.send(acc_s)

                # Registar alocação
                agent.alocacoes[doente_jid] = {
                    "nome": nome,
                    "medico_jid": medico_proposta["medico_jid"],
                    "sala_jid": sala_proposta["sala_jid"],
                }

                log(COORD_CONS,
                    f"[ALOCAÇÃO] Consulta de Rotina AGENDADA: {nome} → "
                    f"Médico={medico_proposta['nome_medico']}, "
                    f"Sala={sala_proposta['nome_sala']}", "BOLD")
            else:
                log(COORD_CONS,
                    f"[ALOCAÇÃO-FALHOU] Impossível agendar consulta de rotina a {nome} "
                    f"(recursos indisponíveis). Pedido pendente.", "RED")
                agent.pending_requests.append(patient_data)

        # -----------------------------------------------------------------
        # PREEMPTION: Cancelar alocação normal para libertar recursos
        # -----------------------------------------------------------------
        async def handle_preemption(self, data):
            """Processa ordem de preemption do Supervisor."""
            log(COORD_CONS,
                f"⚠️  ORDEM DE PREEMPTION recebida do Supervisor! "
                f"Motivo: urgência de {data.get('urgente_nome', '?')}",
                "RED")

            agent = self.agent

            if agent.alocacoes:
                # Cancelar a primeira alocação encontrada
                doente_cancelar = list(agent.alocacoes.keys())[0]
                aloc = agent.alocacoes.pop(doente_cancelar)

                log(COORD_CONS,
                    f"[PREEMPÇÃO] A cancelar alocação de rotina de {aloc['nome']} para "
                    f"libertar recursos...", "RED")

                # Enviar cancel ao médico
                cancel_m = Message(to=aloc["medico_jid"])
                cancel_m.set_metadata("performative", "cancel")
                cancel_m.set_metadata("type", "preemption_cancel")
                cancel_m.body = json.dumps({
                    "motivo": "Preemption por urgência",
                    "doente_original": aloc["nome"],
                })
                cancel_m.thread = doente_cancelar
                await self.send(cancel_m)

                # Enviar cancel à sala
                cancel_s = Message(to=aloc["sala_jid"])
                cancel_s.set_metadata("performative", "cancel")
                cancel_s.set_metadata("type", "preemption_cancel")
                cancel_s.body = json.dumps({
                    "motivo": "Preemption por urgência",
                    "doente_original": aloc["nome"],
                })
                cancel_s.thread = doente_cancelar
                await self.send(cancel_s)

                log(COORD_CONS,
                    f"[PREEMPTION] Cancellation dispatched. Doente {aloc['nome']} "
                    f"será reagendado.", "YELLOW")

                # Colocar o doente cancelado na fila de pendentes
                agent.pending_requests.append({
                    "doente_jid": doente_cancelar,
                    "nome": aloc["nome"],
                    "tipo": "Normal",
                    "prioridade": 0,
                })

                # Aguardar confirmações de cancelamento
                await asyncio.sleep(2)

                # Informar o Supervisor que os recursos foram libertados
                confirm = Message(to=jid(SUPERVISOR))
                confirm.set_metadata("performative", "inform")
                confirm.set_metadata("type", "preemption_done")
                confirm.body = json.dumps({
                    "status": "resources_freed",
                    "medico_jid": aloc["medico_jid"],
                    "sala_jid": aloc["sala_jid"],
                })
                await self.send(confirm)
                log(COORD_CONS,
                    "[PREEMPÇÃO] Recursos libertados com sucesso e supervisor notificado.", "YELLOW")
            else:
                log(COORD_CONS,
                    "[PREEMPÇÃO-FALHOU] Não existem alocações de rotina ativas para libertar.", "RED")
                confirm = Message(to=jid(SUPERVISOR))
                confirm.set_metadata("performative", "inform")
                confirm.set_metadata("type", "preemption_done")
                confirm.body = json.dumps({"status": "no_allocations"})
                await self.send(confirm)

    async def setup(self):
        log(COORD_CONS, "Coordenador de Consultas iniciado.", "GREEN")
        # SEM TEMPLATE — o behaviour único aceita TODAS as mensagens
        # (request, propose, reject-proposal, etc.)
        # A filtragem é feita manualmente no run() com if/elif.
        self.add_behaviour(self.CoordinatorBehaviour())


# ============================================================================
# COORDENADOR DE URGÊNCIAS (Fluxo de Urgência)
# ============================================================================
class CoordenadorUrgencias(Agent):


    def __init__(self, agent_jid, password, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.pending_urgencies = []

    class EmergencyCoordinatorBehaviour(CyclicBehaviour):


        async def run(self):
            msg = await self.receive(timeout=5)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            # ---- Pedido triado (da Triagem) ----
            if performative == "request" and msg_type == "triaged_patient":
                data = json.loads(msg.body)
                log(COORD_URG,
                    f"[PEDIDO] Pedido triado de emergência recebido: {data['nome']} "
                    f"(prioridade={data['prioridade']})", "RED")
                self.agent.pending_urgencies.append(data)
                log(COORD_URG,
                    "[A AGUARDAR] A aguardar confirmação de libertação de recursos do Supervisor...",
                    "YELLOW")

            # ---- Recursos libertados (do Supervisor) ----
            elif performative == "inform" and msg_type == "resources_freed":
                log(COORD_URG,
                    "[NOTIFICAÇÃO] Confirmação de preempção recebida do Supervisor.",
                    "GREEN")
                if self.agent.pending_urgencies:
                    patient = self.agent.pending_urgencies.pop(0)
                    await self.run_emergency_contract_net(patient)

        # -----------------------------------------------------------------
        # CONTRACT-NET DE EMERGÊNCIA
        # -----------------------------------------------------------------
        async def run_emergency_contract_net(self, patient_data):
            """Contract-Net de emergência para alocação imediata."""
            nome = patient_data["nome"]
            doente_jid = patient_data["doente_jid"]

            log(COORD_URG,
                f"[CONTRACT-NET] A iniciar negociação de EMERGÊNCIA para {nome}...",
                "RED")

            # 1) CFP a Médicos
            for m_jid in MEDICOS:
                cfp = Message(to=m_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "emergency_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_URG,
                    f"[CFP] CFP de Emergência enviado para {m_jid}", "RED")

            # 2) CFP a Salas
            for s_jid in SALAS:
                cfp = Message(to=s_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "emergency_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_URG,
                    f"[CFP] CFP de Emergência enviado para {s_jid}", "RED")

            # 3) Recolher propostas
            await asyncio.sleep(2)

            medico_proposta = None
            sala_proposta = None
            expected_replies = len(MEDICOS) + len(SALAS)

            for _ in range(expected_replies):
                reply = await self.receive(timeout=3)
                if reply is None:
                    continue

                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)

                if perf == "propose":
                    if "medico_jid" in body:
                        medico_proposta = body
                        log(COORD_URG,
                            f"[PROPOSTA] Proposta recebida de: {body['nome_medico']}",
                            "GREEN")
                    elif "sala_jid" in body:
                        sala_proposta = body
                        log(COORD_URG,
                            f"[PROPOSTA] Proposta recebida de: {body['nome_sala']}",
                            "GREEN")
                elif perf == "reject-proposal":
                    log(COORD_URG,
                        f"[PROPOSTA] Proposta rejeitada: {body.get('motivo', '?')}",
                        "YELLOW")

            # 4) Adjudicar
            if medico_proposta and sala_proposta:
                acc_m = Message(to=medico_proposta["medico_jid"])
                acc_m.set_metadata("performative", "accept-proposal")
                acc_m.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": patient_data.get("tipo", "Urgencia")
                })
                acc_m.thread = doente_jid
                await self.send(acc_m)

                acc_s = Message(to=sala_proposta["sala_jid"])
                acc_s.set_metadata("performative", "accept-proposal")
                acc_s.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "tipo": patient_data.get("tipo", "Urgencia")
                })
                acc_s.thread = doente_jid
                await self.send(acc_s)

                log(COORD_URG,
                    f"[ALOCAÇÃO] EMERGÊNCIA AGENDADA: {nome} → "
                    f"Médico={medico_proposta['nome_medico']}, "
                    f"Sala={sala_proposta['nome_sala']}", "BOLD")
            else:
                log(COORD_URG,
                    f"[FALHA CRÍTICA] Impossível alocar recursos de emergência para {nome}! "
                    f"Recursos continuam indisponíveis.", "RED")

    async def setup(self):
        log(COORD_URG, "Coordenador de Urgências iniciado.", "RED")
        # SEM TEMPLATE — aceita todas as mensagens, filtragem manual no run()
        self.add_behaviour(self.EmergencyCoordinatorBehaviour())


# ============================================================================
# COORDENADOR DE EXAMES (Fase 4 — Cascata de Cuidados)
# ============================================================================
class CoordenadorExames(Agent):


    class ExamCoordinatorBehaviour(CyclicBehaviour):

        async def run(self):
            msg = await self.receive(timeout=5)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            msg_type     = msg.get_metadata("type")

            # ---- Pedido de exame ----
            if performative == "request" and msg_type == "exam_request":
                data = json.loads(msg.body)
                log(COORD_EXAM,
                    f"[PEDIDO] Pedido de diagnóstico MCDT recebido para: {data.get('nome', '?')}",
                    "CYAN")
                await self.run_exam_contract_net(data)

            # Propostas chegam ao mesmo behaviour (sem template restritivo)
            # — tratadas dentro de run_exam_contract_net via receive().

        async def run_exam_contract_net(self, patient_data):
            """Contract-Net com equipamentos de exame."""
            nome       = patient_data.get("nome", "?")
            doente_jid = patient_data.get("doente_jid", "")

            log(COORD_EXAM,
                f"[CONTRACT-NET] A iniciar negociação de DIAGNÓSTICO para {nome}...", "CYAN")

            # 1) CFP a todos os equipamentos
            for eq_jid in EQUIPAMENTOS:
                cfp = Message(to=eq_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "exam_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_EXAM, f"[CFP] CFP enviado para equipamento {eq_jid}", "CYAN")

            # 2) Aguardar respostas
            await asyncio.sleep(2)

            equipamento_proposta = None

            for _ in range(len(EQUIPAMENTOS)):
                reply = await self.receive(timeout=3)
                if reply is None:
                    continue

                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)

                if perf == "propose":
                    equipamento_proposta = body
                    log(COORD_EXAM,
                        f"[PROPOSTA] Proposta recebida de: "
                        f"{body.get('nome_sala', '?')}", "CYAN")
                elif perf == "reject-proposal":
                    log(COORD_EXAM,
                        f"[PROPOSTA] Proposta rejeitada: {body.get('motivo', '?')}",
                        "YELLOW")

            # 3) Adjudicar
            if equipamento_proposta:
                acc = Message(to=equipamento_proposta["sala_jid"])
                acc.set_metadata("performative", "accept-proposal")
                acc.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                })
                acc.thread = doente_jid
                await self.send(acc)
                log(COORD_EXAM,
                    f"[ALOCAÇÃO] DIAGNÓSTICO AGENDADO: {nome} → "
                    f"Equipamento={equipamento_proposta.get('nome_sala', '?')}",
                    "BOLD")
            else:
                log(COORD_EXAM,
                    f"[ALLOCATION-FAILED] No diagnostic equipment available for {nome}.",
                    "RED")

    async def setup(self):
        log(COORD_EXAM, "Coordenador de Exames iniciado.", "CYAN")
        # SEM TEMPLATE — filtragem manual no run()
        self.add_behaviour(self.ExamCoordinatorBehaviour())


# ============================================================================
# COORDENADOR DE CIRURGIAS (Fase 4 — Cascata de Cuidados)
# ============================================================================
class CoordenadorCirurgias(Agent):


    class SurgeryCoordinatorBehaviour(CyclicBehaviour):

        async def run(self):
            msg = await self.receive(timeout=5)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            msg_type     = msg.get_metadata("type")

            # ---- Pedido de cirurgia ----
            if performative == "request" and msg_type == "surgery_request":
                data = json.loads(msg.body)
                log(COORD_CIR,
                    f"[PEDIDO] Pedido de cirurgia recebido para: {data.get('nome', '?')}",
                    "MAGENTA")
                await self.run_surgery_contract_net(data)

        async def run_surgery_contract_net(self, patient_data):
            """Contract-Net com blocos operatórios e médicos."""
            nome       = patient_data.get("nome", "?")
            doente_jid = patient_data.get("doente_jid", "")

            log(COORD_CIR,
                f"[CONTRACT-NET] A iniciar negociação CIRÚRGICA para {nome}...",
                "MAGENTA")

            # 1) CFP a todos os blocos operatórios
            for b_jid in BLOCOS:
                cfp = Message(to=b_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "surgery_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_CIR, f"[CFP] CFP enviado para bloco operatório {b_jid}", "MAGENTA")

            # 2) CFP a todos os médicos (cirurgião)
            for m_jid in MEDICOS:
                cfp = Message(to=m_jid)
                cfp.body = json.dumps(patient_data)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "surgery_cfp")
                cfp.thread = doente_jid
                await self.send(cfp)
                log(COORD_CIR, f"[CFP] Call for Proposal enviado ao médico/cirurgião {m_jid}",
                    "MAGENTA")

            # 3) Aguardar respostas
            await asyncio.sleep(2)

            bloco_proposta  = None
            medico_proposta = None
            expected_replies = len(BLOCOS) + len(MEDICOS)

            for _ in range(expected_replies):
                reply = await self.receive(timeout=3)
                if reply is None:
                    continue

                perf = reply.get_metadata("performative")
                body = json.loads(reply.body)

                if perf == "propose":
                    if "sala_jid" in body:
                        bloco_proposta = body
                        log(COORD_CIR,
                            f"[PROPOSAL] Proposta recebida da sala: "
                            f"{body.get('nome_sala', '?')}", "MAGENTA")
                    elif "medico_jid" in body:
                        medico_proposta = body
                        log(COORD_CIR,
                            f"[PROPOSAL] Proposta recebida do cirurgião: "
                            f"{body.get('nome_medico', '?')}", "MAGENTA")
                elif perf == "reject-proposal":
                    log(COORD_CIR,
                        f"[PROPOSTA] Proposta rejeitada: {body.get('motivo', '?')}",
                        "YELLOW")

            # 4) Adjudicar bloco + médico
            if bloco_proposta and medico_proposta:
                acc_b = Message(to=bloco_proposta["sala_jid"])
                acc_b.set_metadata("performative", "accept-proposal")
                acc_b.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                })
                acc_b.thread = doente_jid
                await self.send(acc_b)

                acc_m = Message(to=medico_proposta["medico_jid"])
                acc_m.set_metadata("performative", "accept-proposal")
                acc_m.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                })
                acc_m.thread = doente_jid
                await self.send(acc_m)

                log(COORD_CIR,
                    f"[ALOCAÇÃO] CIRURGIA AGENDADA: {nome} → "
                    f"Bloco={bloco_proposta.get('nome_sala', '?')}, "
                    f"Cirurgião={medico_proposta.get('nome_medico', '?')}",
                    "BOLD")
            else:
                log(COORD_CIR,
                    f"[ALLOCATION-FAILED] No valid surgical resources available for {nome}.", "RED")

    async def setup(self):
        log(COORD_CIR, "Coordenador de Cirurgias iniciado.", "MAGENTA")
        self.add_behaviour(self.SurgeryCoordinatorBehaviour())
