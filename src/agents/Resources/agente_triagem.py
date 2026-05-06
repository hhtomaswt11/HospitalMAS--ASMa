import json
import random
import asyncio

from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message

from src.agents.Resources.resource_agent import ResourceAgent
from src.config import *


class AgenteTriagem(ResourceAgent):
    """Triage physician: receives triage CFPs and classifies urgent patients."""

    def __init__(self, agent_jid, password, nome_medico="Medico Triagem", hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, hospital_config=hospital_config, **kwargs)
        self.nome_medico = nome_medico
        self.sala_triagem = None
        cfg = hospital_config or H1_CONFIG
        self._coord_urg = cfg["coord_urg"]
        self._supervisor = cfg["supervisor"]

    def get_resource_name(self):
        return self.nome_medico

    class ClassifyUrgentPatientBehaviour(OneShotBehaviour):
        def __init__(self, data):
            super().__init__()
            self.data = data

        async def run(self):
            nome = self.data.get("nome", "?")
            doente_jid = self.data.get("doente_jid")

            await self.agent.send_status(self)
            log(self.agent.nome_medico, f"[TRIAGEM] A classificar urgencia para {nome}.", "YELLOW")

            await asyncio.sleep(TRIAGE_CLASSIFICATION_SECONDS)
            self.data["prioridade"] = random.randint(URGENT_PRIORITY_MIN, URGENT_PRIORITY_MAX)
            self.data["especialidade"] = random.choice(URGENT_TRIAGE_SPECIALTIES)
            self.data["triagem_medico"] = self.agent.nome_medico

            # Determine dest for triaged patient — use coord_urg from hospital_config or payload
            coord_urg = self.data.pop("coord_urg", None) or self.agent._coord_urg

            msg_urg = Message(to=coord_urg)
            msg_urg.body = json.dumps(self.data)
            msg_urg.set_metadata("performative", "request")
            msg_urg.set_metadata("type", "triaged_patient")
            msg_urg.thread = doente_jid
            await self.send(msg_urg)

            alert = Message(to=self.agent._supervisor)
            alert.body = json.dumps({
                "alert": "EMERGENCY",
                "doente_jid": doente_jid,
                "nome": nome,
                "prioridade": self.data["prioridade"],
                "especialidade": self.data["especialidade"],
            })
            alert.set_metadata("performative", "inform")
            alert.set_metadata("type", "emergency_alert")
            alert.thread = doente_jid
            await self.send(alert)

            if self.agent.sala_triagem:
                release = Message(to=self.agent.sala_triagem)
                release.set_metadata("performative", "inform")
                release.set_metadata("type", "release")
                await self.send(release)

            log(self.agent.nome_medico,
                f"[TRIAGEM] {nome} classificado com prioridade={self.data['prioridade']} "
                f"e especialidade={self.data['especialidade']}.", "YELLOW")
            self.agent.disponivel = True
            self.agent.paciente_atual = None
            self.agent.sala_triagem = None
            await self.agent.send_status(self)

    class HandleTriagemBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=RESOURCE_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            if performative == "cfp":
                data = json.loads(msg.body)
                reply = msg.make_reply()
                if self.agent.disponivel:
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "medico_jid": str(self.agent.jid),
                        "nome_medico": self.agent.nome_medico,
                        "slot": "next_available",
                    })
                    log(self.agent.nome_medico,
                        f"[TRIAGEM] Proposta enviada para {data.get('nome', '?')}.", "YELLOW")
                else:
                    reply.set_metadata("performative", "reject-proposal")
                    reply.body = json.dumps({
                        "medico_jid": str(self.agent.jid),
                        "motivo": "Triagem ocupada.",
                    })
                await self.send(reply)

            elif performative == "accept-proposal":
                data = json.loads(msg.body)
                self.agent.disponivel = False
                self.agent.paciente_atual = data.get("doente_jid")
                self.agent.sala_triagem = data.get("sala_jid")
                self.agent.add_behaviour(self.agent.ClassifyUrgentPatientBehaviour(data))

    async def setup(self):
        log(self.nome_medico, "AgenteTriagem inicializado.", "YELLOW")
        self.add_behaviour(self.StartupStatusBehaviour())
        self.add_behaviour(self.HandleTriagemBehaviour())
