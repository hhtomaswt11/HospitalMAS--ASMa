"""
AgenteTriagemGeral — Central Triage Agent

Receives patients with tipo_entrada="Central", diagnoses them (specialty + priority),
then uses a load_query Contract-Net to select the least-loaded hospital, and routes
the patient to that hospital's appropriate coordinator.

Fix: ReceivePatientsBehaviour acts as the sole mailbox consumer and dispatches
load_response messages into per-patient asyncio.Queues, eliminating the race
condition where the CyclicBehaviour would steal responses meant for
DiagnoseAndRouteBehaviour.
"""
import asyncio
import json
import random
import time

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message

from src.config import *


class AgenteTriagemGeral(Agent):

    def __init__(self, agent_jid, password, hospital_configs=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        # List of hospital_config dicts — one per hospital participating in load balancing
        self.hospital_configs = hospital_configs or [H1_CONFIG, H2_CONFIG]
        # Per-patient queues: doente_jid -> asyncio.Queue of load_response dicts
        self.pending_load_responses: dict = {}
        self._sim_start_time = time.time() - (8 * SIM_HOUR_SECONDS)

    class DiagnoseAndRouteBehaviour(OneShotBehaviour):
        """One-shot behaviour launched per patient arrival."""

        def __init__(self, data):
            super().__init__()
            self.data = data

        async def run(self):
            nome = self.data.get("nome", "?")
            doente_jid = self.data.get("doente_jid")
            tipo = self.data.get("tipo_original") or self.data.get("tipo", "Normal")
            if tipo == "Central":
                # Salvaguarda para mensagens antigas sem tipo_original.
                tipo = "Normal"
            self.data["tipo"] = tipo
            self.data["tipo_original"] = tipo
            self.data["via_central"] = True

            log(UNIFIED_TRIAGE,
                f"[TRIAGEM-GERAL] Paciente recebido: {nome} (tipo_original={tipo}). A diagnosticar...",
                "MAGENTA")

            # 1. Diagnose: assign specialty and priority
            await asyncio.sleep(CENTRAL_TRIAGE_DIAGNOSIS_SECONDS)

            if tipo == "Urgencia":
                self.data["prioridade"] = random.randint(URGENT_PRIORITY_MIN, URGENT_PRIORITY_MAX)
                self.data["especialidade"] = random.choice(URGENT_TRIAGE_SPECIALTIES)
            else:
                self.data["especialidade"] = random.choice(ROUTINE_SPECIALTIES)
                self.data["prioridade"] = 0

            especialidade = self.data["especialidade"]
            # 1.5 Check if we can route routine patients at this hour
            if tipo == "Normal":
                elapsed = time.time() - self.agent._sim_start_time
                current_hour = (elapsed % SIM_DAY_SECONDS) / SIM_HOUR_SECONDS
                if not (ROUTINE_START_H <= current_hour < ROUTINE_END_H):
                    log(UNIFIED_TRIAGE,
                        f"[TRIAGEM-GERAL] Bloqueado encaminhamento de {nome} (Rotina) - Fora do horário (Hora: {current_hour:.1f}). Alta administrativa enviada.",
                        "MAGENTA")

                    # O doente ainda não foi encaminhado para nenhum coordenador hospitalar.
                    # Sem esta resposta explícita, o agente doente ficava vivo até ao fim da simulação.
                    if doente_jid:
                        msg_discharge = Message(to=doente_jid)
                        msg_discharge.set_metadata("performative", "inform")
                        msg_discharge.set_metadata("type", "discharge")
                        msg_discharge.body = json.dumps({
                            "estado": "Encaminhamento de rotina recusado fora do horario de consultas",
                            "motivo": "fora_horario_rotina",
                            "hora_simulada": round(current_hour, 2),
                        })
                        msg_discharge.thread = doente_jid
                        await self.send(msg_discharge)
                    return # Cancel routing for this routine patient

            # 2. Register a queue for this patient's load responses BEFORE sending CFPs
            queue = asyncio.Queue()
            self.agent.pending_load_responses[doente_jid] = queue

            # 3. Send load_query CFP to the Supervisor of each hospital
            query_targets = [cfg["supervisor"] for cfg in self.agent.hospital_configs]

            for target in query_targets:
                cfp = Message(to=target)
                cfp.set_metadata("performative", "cfp")
                cfp.set_metadata("type", "load_query")
                cfp.body = json.dumps({
                    "doente_jid": doente_jid,
                    "nome": nome,
                    "especialidade": especialidade,
                    "tipo": tipo
                })
                cfp.thread = doente_jid
                await self.send(cfp)

            log(UNIFIED_TRIAGE,
                f"[TRIAGEM-GERAL] Load query (especialidade={especialidade}) enviado para {len(query_targets)} hospitais.", "MAGENTA")

            # 4. Collect responses from the per-patient queue (no mailbox contention)
            responses = []
            expected = len(query_targets)
            deadline = asyncio.get_running_loop().time() + LOAD_QUERY_RESPONSE_WAIT_SECONDS

            for _ in range(expected):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    body = await asyncio.wait_for(queue.get(), timeout=remaining)
                    responses.append(body)
                except asyncio.TimeoutError:
                    break

            # 5. Clean up the queue entry
            self.agent.pending_load_responses.pop(doente_jid, None)

            if not responses:
                log(UNIFIED_TRIAGE,
                    f"[TRIAGEM-GERAL] Sem respostas (timeout) para {nome}. "
                    f"A usar Hospital 1 por defeito.", "RED")
                best_cfg = self.agent.hospital_configs[0]
                best_metric = "Timeout (H1 Default)"
            else:
                # Nuanced selection:
                # 1. Primary: specialty_load (bottleneck for this specific patient)
                # 2. Secondary: total_load (overall hospital congestion)
                best = min(responses, key=lambda r: (r.get("specialty_load", 999), r.get("total_load", 999)))
                best_metric = (
                    f"spec={best.get('specialty_load', '?')} "
                    f"(fila={best.get('pending_specialty_load', '?')}, agenda={best.get('scheduled_specialty_load', '?')}), "
                    f"total={best.get('total_load', '?')} "
                    f"(fila={best.get('pending_total_load', '?')}, agenda={best.get('scheduled_total_load', '?')})"
                )

                # Map the responding supervisor back to its hospital_config
                responding_jid = best.get("supervisor_jid", "")
                best_cfg = None
                for cfg in self.agent.hospital_configs:
                    if cfg.get("supervisor") == responding_jid:
                        best_cfg = cfg
                        break
                if best_cfg is None:
                    best_cfg = self.agent.hospital_configs[0]

                log(UNIFIED_TRIAGE,
                    f"[TRIAGEM-GERAL] Hospital selecionado para {nome}: "
                    f"H{best.get('hospital_id', '?')} ({best_metric}).", "MAGENTA")

            # 6. Route patient to winning hospital
            if tipo == "Urgencia":
                dest = best_cfg["coord_tri"]
                msg_type = "patient_request"
                log(UNIFIED_TRIAGE,
                    f"[TRIAGEM-GERAL] {nome} encaminhado para Triagem de Urgência em {dest}.", "RED")
            else:
                dest = best_cfg["coord_cons"]
                msg_type = "patient_request"
                log(UNIFIED_TRIAGE,
                    f"[TRIAGEM-GERAL] {nome} encaminhado para Consultas de Rotina em {dest}.", "GREEN")

            route_msg = Message(to=dest)
            route_msg.set_metadata("performative", "request")
            route_msg.set_metadata("type", msg_type)
            route_msg.body = json.dumps(self.data)
            route_msg.thread = doente_jid
            await self.send(route_msg)

            # 7. Inform Supervisor for Dashboard visualization
            info_msg = Message(to=jid(SUPERVISOR))  # Primary dashboard aggregator (H1 supervisor)
            info_msg.set_metadata("performative", "inform")
            info_msg.set_metadata("type", "routing_update")
            info_msg.body = json.dumps({
                "nome": nome,
                "doente_jid": doente_jid,
                "dest": dest,
                "tipo": tipo,
                "especialidade": especialidade,
                "load": best_metric
            })
            await self.send(info_msg)

            log(UNIFIED_TRIAGE,
                f"[TRIAGEM-GERAL] Encaminhamento de {nome} concluído.", "MAGENTA")

    class ReceivePatientsBehaviour(CyclicBehaviour):
        """
        Main cyclic loop — sole consumer of the agent mailbox.

        Dispatches:
          - patient_request  → launches DiagnoseAndRouteBehaviour
          - load_response    → pushes into the per-patient asyncio.Queue
        """

        async def run(self):
            msg = await self.receive(timeout=COORDINATOR_RECEIVE_TIMEOUT_SECONDS)
            if msg is None:
                return

            performative = msg.get_metadata("performative")
            msg_type = msg.get_metadata("type")

            if performative == "request" and msg_type == "patient_request":
                data = json.loads(msg.body)
                log(UNIFIED_TRIAGE,
                    f"[TRIAGEM-GERAL] Novo paciente central: {data.get('nome', '?')}", "MAGENTA")
                self.agent.add_behaviour(self.agent.DiagnoseAndRouteBehaviour(data))

            elif performative == "propose" and msg_type == "load_response":
                # Dispatch to the waiting DiagnoseAndRouteBehaviour via the patient's queue
                patient_jid = msg.thread
                queue = self.agent.pending_load_responses.get(patient_jid)
                if queue is not None:
                    try:
                        body = json.loads(msg.body)
                        queue.put_nowait(body)
                    except Exception:
                        pass
                # else: response arrived after timeout was already hit — silently discard

    async def setup(self):
        log(UNIFIED_TRIAGE, "AgenteTriagemGeral iniciado. A aguardar pacientes centrais...", "MAGENTA")
        self.add_behaviour(self.ReceivePatientsBehaviour())
