import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *

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

                # NOTIFICAR SOLICITANTE (Médico)
                solicitante = patient_data.get("solicitante")
                if solicitante:
                    notif = Message(to=solicitante)
                    notif.set_metadata("performative", "inform")
                    notif.set_metadata("type", "allocation_confirmed")
                    notif.body = json.dumps({
                        "doente_jid": doente_jid,
                        "sala_jid": equipamento_proposta["sala_jid"],
                        "procedure": "exam"
                    })
                    await self.send(notif)
            else:
                log(COORD_EXAM,
                    f"[ALLOCATION-FAILED] No diagnostic equipment available for {nome}.",
                    "RED")

    async def setup(self):
        log(COORD_EXAM, "Coordenador de Exames iniciado.", "CYAN")
        # SEM TEMPLATE — filtragem manual no run()
        self.add_behaviour(self.ExamCoordinatorBehaviour())
