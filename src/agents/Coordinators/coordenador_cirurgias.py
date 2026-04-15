import asyncio
import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

from src.config import *

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
            medicos_cirurgia = [
                m_jid
                for m_jid in MEDICOS
                if AGENT_REGISTRY.get(m_jid, {}).get("specialty") == SPECIALTY_CIRURGIA
            ]

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

            # 2) CFP apenas a médicos cirurgiões
            for m_jid in medicos_cirurgia:
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
            expected_replies = len(BLOCOS) + len(medicos_cirurgia)

            for _ in range(expected_replies):
                reply = await self.receive(timeout=3)
                if reply is None:
                    continue

                if reply.thread != doente_jid:
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
                    "sala_jid": bloco_proposta["sala_jid"],
                })
                acc_m.thread = doente_jid
                await self.send(acc_m)

                log(COORD_CIR,
                    f"[ALOCAÇÃO] CIRURGIA AGENDADA: {nome} → "
                    f"Bloco={bloco_proposta.get('nome_sala', '?')}, "
                    f"Cirurgião={medico_proposta.get('nome_medico', '?')}",
                    "BOLD")

                # NOTIFICAR SOLICITANTE (Médico)
                solicitante = patient_data.get("solicitante")
                if solicitante:
                    notif = Message(to=solicitante)
                    notif.set_metadata("performative", "inform")
                    notif.set_metadata("type", "allocation_confirmed")
                    notif.body = json.dumps({
                        "doente_jid": doente_jid,
                        "sala_jid": bloco_proposta["sala_jid"],
                        "procedure": "surgery"
                    })
                    await self.send(notif)
            else:
                log(COORD_CIR,
                    f"[ALLOCATION-FAILED] No valid surgical resources available for {nome}.", "RED")

    async def setup(self):
        log(COORD_CIR, "Coordenador de Cirurgias iniciado.", "MAGENTA")
        self.add_behaviour(self.SurgeryCoordinatorBehaviour())
