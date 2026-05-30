import asyncio
import json
import time

from spade.behaviour import CyclicBehaviour, OneShotBehaviour, PeriodicBehaviour
from spade.message import Message

from src.agents.Resources.resource_agent import ResourceAgent
from src.config import (
    RESOURCE_RECEIVE_TIMEOUT_SECONDS,
    WEEKLY_MAX_HOURS, PROCEDURE_HOURS,
    INTERNAMENTO_MIN_SECONDS,
    SIM_DAY_SECONDS, SIM_WEEK_SECONDS,
    SIM_HOUR_SECONDS,
    AGENT_REGISTRY,
    H1_CONFIG, log,
)


class AgenteEnfermeiro(ResourceAgent):
    """
    Nurse agent — responds to internment CFPs from CoordenadorInternamento.
    Manages the full internment duration and releases the room when done.
    Also participates in shift rotation (morning/afternoon).
    """

    def __init__(self, agent_jid, password, nome_enfermeiro="Enfermeiro/a",
                 hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, hospital_config=hospital_config, **kwargs)
        self.nome_enfermeiro = nome_enfermeiro
        cfg = hospital_config or H1_CONFIG
        self._coord_int = cfg["coord_int"]

        # (max_weekly_hours, weekly_hours_used, current_assignment_type
        #  já são herdados de ResourceAgent)
        self.role = "nurse"

    def get_resource_name(self):
        return self.nome_enfermeiro

    def add_hours(self, procedure_type: str):
        hours = PROCEDURE_HOURS.get(procedure_type, 2)
        self.weekly_hours_used += hours
        log(self.nome_enfermeiro,
            f"[HORAS] {self.nome_enfermeiro} acumulou {self.weekly_hours_used:.0f}/{self.max_weekly_hours}h semanais "
            f"(+{hours}h por {procedure_type}).", "YELLOW")

    class ManageInternmentBehaviour(OneShotBehaviour):
        def __init__(self, data):
            super().__init__()
            self.data = data

        async def run(self):
            sala_jid = self.data.get("sala_jid")
            nome = self.data.get("nome", "?")
            duration = int(self.data.get("duration", INTERNAMENTO_MIN_SECONDS))

            log(self.agent.nome_enfermeiro,
                f"[ENFERMAGEM] {self.agent.nome_enfermeiro} iniciou vigilância do doente {nome} "
                f"em {sala_jid} por {duration}s.", "YELLOW")

            await asyncio.sleep(duration)

            # Release the room
            if sala_jid:
                msg_release = Message(to=sala_jid)
                msg_release.set_metadata("performative", "inform")
                msg_release.set_metadata("type", "release")
                await self.send(msg_release)

            # Notify coordinator
            done = Message(to=self.agent._coord_int)
            done.set_metadata("performative", "inform")
            done.set_metadata("type", "internment_finished")
            done.body = json.dumps({
                "doente_jid": self.data.get("doente_jid"),
                "nome": nome,
            })
            done.thread = self.data.get("doente_jid")
            await self.send(done)

            # Notify patient discharge; otherwise patient agents remain alive after internment.
            msg_discharge = Message(to=self.data.get("doente_jid"))
            msg_discharge.set_metadata("performative", "inform")
            msg_discharge.set_metadata("type", "discharge")
            msg_discharge.body = json.dumps({"estado": "Alta de internamento"})
            msg_discharge.thread = self.data.get("doente_jid")
            await self.send(msg_discharge)

            # Free the nurse
            self.agent.clear_assignment()
            await self.agent.send_status(self)

            log(self.agent.nome_enfermeiro,
                f"[ENFERMAGEM] Internamento de {nome} concluído. "
                f"Enfermeiro/a e quarto libertados.", "GREEN")

    class HandleProposalsBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=RESOURCE_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            agent = self.agent

            if performative == "cfp":
                data = json.loads(msg.body)
                reply = msg.make_reply()

                at_limit = agent.weekly_hours_used >= agent.max_weekly_hours
                # Enfermeiro só aceita se estiver em turno E disponível E dentro do limite
                if agent.disponivel and agent.on_shift and not at_limit:
                    reply.set_metadata("performative", "propose")
                    reply.body = json.dumps({
                        "enfermeiro_jid": str(agent.jid),
                        "nome_enfermeiro": agent.nome_enfermeiro,
                        "weekly_hours_used": agent.weekly_hours_used,
                        "max_weekly_hours": agent.max_weekly_hours,
                        "on_shift": agent.on_shift,
                        "slot": "next_available",
                        "score": agent.weekly_hours_used,
                    })
                    log(agent.nome_enfermeiro,
                        f"[PROPOSAL] Proposta de internamento emitida para {data.get('nome', '?')}.", "YELLOW")
                else:
                    if not agent.on_shift:
                        reason = "fora de turno"
                    elif at_limit:
                        reason = "limite horário atingido"
                    else:
                        reason = "ocupado/a"
                    reply.set_metadata("performative", "refuse")
                    reply.body = json.dumps({
                        "enfermeiro_jid": str(agent.jid),
                        "motivo": reason,
                    })
                    log(agent.nome_enfermeiro,
                        f"[PROPOSAL] CFP de internamento recusado ({reason}).", "YELLOW")
                await self.send(reply)

            elif performative == "accept-proposal":
                data = json.loads(msg.body)
                agent.disponivel = False
                agent.paciente_atual = data.get("doente_jid")
                agent.current_assignment_type = "internment"
                agent.add_hours("internment")
                await agent.send_status(self)
                log(agent.nome_enfermeiro,
                    f"[INTERNAMENTO] {data.get('nome', '?')} admitido/a. "
                    f"A iniciar vigilância de enfermagem.", "YELLOW")
                agent.add_behaviour(agent.ManageInternmentBehaviour(data))

            elif performative == "reject-proposal":
                log(agent.nome_enfermeiro,
                    "[CONTRACT-NET] Proposta rejeitada pelo coordenador; enfermeiro/a mantém-se livre.",
                    "YELLOW")

            elif performative == "cancel":
                prev = agent.paciente_atual
                agent.clear_assignment()
                log(agent.nome_enfermeiro,
                    f"[CANCEL] Internamento cancelado/libertado (doente anterior: {prev}).",
                    "RED")
                await agent.send_status(self)

            else:
                log(agent.nome_enfermeiro,
                    f"[IGNORADO] Mensagem sem handler explícito: performative={performative}, type={msg.get_metadata('type')}",
                    "YELLOW")

    async def setup(self):
        turno_inicial = "em turno" if self.on_shift else "fora de turno"
        log(self.nome_enfermeiro,
            f"AgenteEnfermeiro iniciado (disponivel={self.disponivel}, "
            f"turno={self._shift_type}, {turno_inicial})", "YELLOW")
        self.add_behaviour(self.StartupStatusBehaviour())
        self.add_behaviour(self.HandleProposalsBehaviour())
        self.add_behaviour(self.ShiftRotationBehaviour(period=10))
        self.add_behaviour(self.WeeklyResetBehaviour(period=10))
