import json

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template

from src.config import *

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


