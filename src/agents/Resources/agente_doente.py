import json
import time
import asyncio

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message

from src.config import *
from src.scheduling import sim_time_label

class AgenteDoente(Agent):
    
    def __init__(self, agent_jid, password, nome_doente, tipo_entrada="Normal",
                 tipo_original=None, especialidade=None, hospital_config=None, sim_start_time=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        self.nome_doente = nome_doente
        self.tipo_entrada = tipo_entrada
        # Quando o doente passa pela Triagem Geral, tipo_entrada fica "Central",
        # mas o fluxo clínico precisa de saber se a origem era Normal ou Urgencia.
        self.tipo_original = tipo_original or tipo_entrada
        self.especialidade = especialidade
        self.hospital_config = hospital_config  # set for Normal/Urgencia patients
        self._sim_start_time = sim_start_time or (time.time() - (8 * SIM_HOUR_SECONDS))
        self.spawned_at = time.time()
        self.finished = False

    class DelayedStopBehaviour(OneShotBehaviour):
        """Stops the patient only after a short drain window.

        In SPADE/XMPP, late messages can arrive a few milliseconds after a
        discharge/allocation event.  Stopping immediately causes noisy
        "No behaviour matched" warnings even though the clinical flow is already
        complete.  This small grace period lets the patient absorb and ignore
        those messages cleanly.
        """

        async def run(self):
            await asyncio.sleep(PATIENT_SHUTDOWN_GRACE_SECONDS)
            # Mantido por compatibilidade, mas já não é usado no fluxo normal.
            # Os doentes ficam vivos até ao shutdown global para absorverem
            # mensagens tardias sem gerar avisos SPADE/XMPP.

    class SendRequestBehaviour(OneShotBehaviour):
        async def run(self):
            agent = self.agent
            body = json.dumps({
                "doente_jid": str(agent.jid),
                "nome": agent.nome_doente,
                "tipo": agent.tipo_entrada,
                "tipo_original": agent.tipo_original,
                "via_central": agent.tipo_entrada == "Central",
                "especialidade": agent.especialidade,
                "spawned_at": agent.spawned_at,
            })

            if agent.tipo_entrada == "Central":
                # Redirected to the central triage agent for hospital selection
                dest = jid(UNIFIED_TRIAGE)
                log(agent.nome_doente,
                    f"[PEDIDO] Encaminhado para TRIAGEM GERAL CENTRAL ({UNIFIED_TRIAGE})",
                    "MAGENTA")
            elif agent.tipo_entrada == "Normal":
                cfg = agent.hospital_config or H1_CONFIG
                dest = cfg["coord_cons"]
                log(agent.nome_doente,
                    f"[PEDIDO] Consulta de ROTINA para {dest} (esp={agent.especialidade})",
                    "GREEN")
            else:
                # Urgencia — goes to hospital-specific triage coordinator
                cfg = agent.hospital_config or H1_CONFIG
                dest = cfg["coord_tri"]
                log(agent.nome_doente, f"[PEDIDO] EMERGENCIA enviada para {dest}", "RED")

            msg = Message(to=dest)
            msg.body = body
            msg.set_metadata("performative", "request")
            msg.set_metadata("type", "patient_request")
            msg.thread = str(agent.jid)
            await self.send(msg)
            log(agent.nome_doente, "[SUCESSO] Pedido enviado com sucesso.", "GREEN")

    class ReceiveStatusBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=RESOURCE_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                return

            msg_type = msg.get_metadata("type") or "sem_tipo"
            try:
                payload = json.loads(msg.body) if msg.body else {}
            except Exception:
                payload = {"raw": msg.body}

            resumo = payload.get("estado") or payload.get("status") or payload.get("nome") or str(payload)
            log(self.agent.nome_doente, f"[STATUS] Atualização recebida ({msg_type}): {resumo}", "CYAN")

            if self.agent.finished and msg_type != "discharge":
                log(
                    self.agent.nome_doente,
                    f"[IGNORADO] Mensagem tardia após alta ignorada ({msg_type}).",
                    "YELLOW",
                )
                return

            if msg_type == "consultation_scheduled":
                start_at = payload.get("consultation_start_at")
                eta = None
                try:
                    eta = max(0.0, float(start_at) - time.time())
                except Exception:
                    eta = None

                if eta is not None:
                    log(
                        self.agent.nome_doente,
                        f"[AGENDA] Consulta de rotina marcada | médico={payload.get('medico_nome', payload.get('medico_jid', '?'))} | "
                        f"sala={payload.get('sala_nome', payload.get('sala_jid', '?'))} | "
                        f"especialidade={payload.get('especialidade', '?')} | "
                        f"início={payload.get('hora_inicio_marcada', '?')} | "
                        f"fim previsto={payload.get('hora_fim_prevista', '?')} | "
                        f"ETA={eta:.1f}s | Estado={payload.get('estado', 'agendada')}",
                        "GREEN",
                    )
                else:
                    log(
                        self.agent.nome_doente,
                        "[AGENDA] Consulta marcada (horário indisponível no payload).",
                        "GREEN",
                    )
                return

            if msg_type == "allocation_confirmed":
                proc = payload.get("procedure", "MCDT/Procedimento")
                sala = payload.get("sala_jid", "?").split("@")[0]
                med_raw = payload.get("medico_jid") or payload.get("enfermeiro_jid") or "?"
                med = med_raw.split("@")[0]
                
                if proc == "exam":
                    start_at = payload.get("exam_start_at")
                    t_label = "agendado para breve"
                    eta = 0.0
                    if start_at:
                        try:
                            t_label = f"agendado para {sim_time_label(float(start_at), self.agent._sim_start_time)}"
                            eta = max(0.0, float(start_at) - time.time())
                        except Exception:
                            pass
                    log(self.agent.nome_doente,
                        f"[SMS-NOTIFICAÇÃO] O seu exame de {payload.get('especialidade', 'MCDT')} foi {t_label} | "
                        f"Sala={sala} | Médico={med} | ETA={eta:.1f}s", "CYAN")
                elif proc == "surgery":
                    start_at = payload.get("surgery_start_at")
                    t_label = "agendada para breve"
                    eta = 0.0
                    if start_at:
                        try:
                            t_label = f"agendada para {sim_time_label(float(start_at), self.agent._sim_start_time)}"
                            eta = max(0.0, float(start_at) - time.time())
                        except Exception:
                            pass
                    log(self.agent.nome_doente,
                        f"[SMS-NOTIFICAÇÃO] A sua cirurgia foi {t_label} | "
                        f"Bloco={sala} | Cirurgião={med} | ETA={eta:.1f}s", "MAGENTA")
                elif proc == "internment":
                    dur = payload.get("duration", 0)
                    log(self.agent.nome_doente,
                        f"[SMS-NOTIFICAÇÃO] Internamento confirmado no Quarto {sala} | "
                        f"Enfermeiro(a) responsável={med} | Duração prevista={dur}s (simulação)", "YELLOW")
                return

            if msg_type == "discharge":
                if self.agent.finished:
                    log(self.agent.nome_doente, "[ALTA] Alta duplicada ignorada.", "YELLOW")
                    return
                self.agent.finished = True
                log(
                    self.agent.nome_doente,
                    "[ALTA] Recebi alta médica! Doente marcado como concluído; "
                    "permanece ativo até ao encerramento global para absorver mensagens tardias.",
                    "GREEN",
                )
                return

    async def setup(self):
        log(self.nome_doente, f"AgenteDoente initialized (type={self.tipo_entrada})", "GREEN")
        self.add_behaviour(self.SendRequestBehaviour())
        self.add_behaviour(self.ReceiveStatusBehaviour())
