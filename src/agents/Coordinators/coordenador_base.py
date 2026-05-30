"""
CoordenadorBase — Classe base para todos os coordenadores hospitalares.

Centraliza atributos e lógica comum:
  - Identificação (nome, config, supervisor)
  - Fila genérica com deduplicação por doente_jid
  - Backoff exponencial para retentativas
  - Métodos utilitários para Contract Net (reject)
"""
import json
import time
import asyncio

from spade.agent import Agent
from spade.message import Message

from src.config import H1_CONFIG, ROUTINE_SURGERY_PRIORITY, CONTRACT_NET_SEND_REJECT_PROPOSALS, log


class CoordenadorBase(Agent):

    def __init__(self, agent_jid, password, hospital_config=None, **kwargs):
        super().__init__(agent_jid, password, **kwargs)
        cfg = hospital_config or H1_CONFIG
        self.hospital_config = cfg
        self._coord_name = str(agent_jid).split("@")[0]
        self._supervisor = cfg.get("supervisor")

        # Fila genérica com deduplicação
        self.pending_requests = []
        self.pending_patient_ids = set()

    # ── Gestão de Fila ──

    def enqueue(self, data):
        """Adiciona pedido à fila se não for duplicado."""
        doente_jid = data.get("doente_jid")
        if not doente_jid or doente_jid in self.pending_patient_ids:
            return False
        data.setdefault("_retry_count", 0)
        data.setdefault("_next_retry_at", 0.0)
        self.pending_requests.append(data)
        self.pending_patient_ids.add(doente_jid)
        return True

    def dequeue(self, doente_jid):
        """Remove e retorna pedido da fila pelo JID do doente."""
        for i, p in enumerate(self.pending_requests):
            if p.get("doente_jid") == doente_jid:
                removed = self.pending_requests.pop(i)
                self.pending_patient_ids.discard(doente_jid)
                return removed
        self.pending_patient_ids.discard(doente_jid)
        return None

    def total_pending(self):
        return len(self.pending_requests)

    # ── Retentativas com Backoff ──

    def get_ready_index(self):
        """Retorna o índice do pedido pronto com melhor prioridade."""
        now = time.monotonic()
        best_idx, best_pri = None, float('inf')
        for idx, req in enumerate(self.pending_requests):
            if float(req.get("_next_retry_at", 0.0)) <= now:
                p_val = req.get("prioridade")
                prioridade = float(p_val) if p_val is not None else float(ROUTINE_SURGERY_PRIORITY)
                if prioridade < best_pri:
                    best_pri = prioridade
                    best_idx = idx
        return best_idx

    def schedule_retry(self, data, max_retries, base_seconds, max_seconds):
        """Aplica backoff exponencial para retentativas."""
        retries = int(data.get("_retry_count", 0)) + 1
        data["_retry_count"] = retries
        if retries >= max_retries:
            return None, retries, True
        delay = min(base_seconds * (2 ** (retries - 1)), max_seconds)
        data["_next_retry_at"] = time.monotonic() + delay
        return delay, retries, False


    async def emit_metric_event(self, behaviour, event, patient_data, **extra):
        """Send a lightweight simulation-metrics event to this hospital's Supervisor.

        The Supervisor/state_store computes the aggregate counters and averages.
        This keeps metrics collection out of the clinical allocation logic.
        """
        payload = {
            "event": event,
            "doente_jid": patient_data.get("doente_jid"),
            "nome": patient_data.get("nome"),
            "tipo": patient_data.get("tipo"),
            "tipo_original": patient_data.get("tipo_original"),
            "spawned_at": patient_data.get("spawned_at") or patient_data.get("created_at"),
        }
        payload.update(extra)
        msg = Message(to=self._supervisor)
        msg.set_metadata("performative", "inform")
        msg.set_metadata("type", "metrics_event")
        msg.body = json.dumps(payload)
        msg.thread = payload.get("doente_jid")
        await behaviour.send(msg)

    # ── Utilitários Contract Net ──

    async def reject_unselected(self, behaviour, propostas, selected_jid, jid_key, thread, motivo):
        """Rejeita propostas não selecionadas quando o modo estrito está ativo.

        No modelo implementado, os recursos não ficam reservados após ``propose``;
        só alteram estado ao receber ``accept-proposal``. Assim, as mensagens
        ``reject-proposal`` são apenas informativas. Por defeito são omitidas
        para evitar ruído assíncrono do SPADE/XMPP no fim de ciclos de negociação
        ou durante o encerramento da simulação.
        """
        if not CONTRACT_NET_SEND_REJECT_PROPOSALS:
            return

        for proposta in propostas:
            target = proposta.get(jid_key)
            if not target or target == selected_jid:
                continue
            rej = Message(to=target)
            rej.set_metadata("performative", "reject-proposal")
            rej.body = json.dumps({"motivo": motivo, "doente_jid": thread})
            rej.thread = thread
            await behaviour.send(rej)

    async def reject_all(self, behaviour, propostas, jid_key, thread, motivo):
        """Rejeita todas as propostas."""
        await self.reject_unselected(behaviour, propostas, None, jid_key, thread, motivo)

    async def wait_for_confirmations(self, behaviour, doente_jid, expected_jids,
                                     timeout_seconds, oob_handler=None):
        """Aguarda reservation_confirmed de todos os recursos esperados.

        Returns:
            (all_confirmed: bool, confirmed_set: set of resource JIDs)
        """
        confirmed = set()
        expected = set(expected_jids)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds

        while len(confirmed) < len(expected):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            reply = await behaviour.receive(timeout=remaining)
            if reply is None:
                break
            msg_type = reply.get_metadata("type")
            if msg_type == "reservation_confirmed":
                try:
                    body = json.loads(reply.body) if reply.body else {}
                except Exception:
                    body = {}
                resource_jid = body.get("resource_jid")
                if resource_jid in expected:
                    confirmed.add(resource_jid)
                    log(self._coord_name,
                        f"[CONFIRMAÇÃO] {body.get('resource_role', 'recurso')} confirmou reserva "
                        f"para {body.get('doente_jid', '?')}.",
                        "GREEN")
            elif oob_handler:
                await oob_handler(reply)

        return confirmed == expected, confirmed

    def select_best_resource_pair(self, medico_propostas, sala_propostas, patient_data):
        """Seleciona a melhor combinação de médico e sala (bloco ou equipamento),
        respeitando a prioridade de urgência para preempção de exames/cirurgias de rotina.
        
        Returns:
            (medico_proposta, sala_proposta, start_at, preempt_medico, preempt_sala)
        """
        if not medico_propostas or not sala_propostas:
            return None, None, None, None, None

        now = time.time()
        is_urgent = patient_data.get("tipo_original") != "Normal" and patient_data.get("tipo") != "Normal"

        def _slot_at(proposta, use_urgency=False):
            slot = proposta.get("slot_at_urgency" if use_urgency else "slot_at", proposta.get("slot_at"))
            try:
                return float(slot)
            except Exception:
                return now

        def _score(proposta, use_urgency=False):
            return proposta.get("score_urgency" if use_urgency else "score", proposta.get("score", 999))

        best = None

        for m_prop in medico_propostas:
            for s_prop in sala_propostas:
                start_at = max(_slot_at(m_prop), _slot_at(s_prop))
                combined_score = _score(m_prop) + _score(s_prop)
                key = (start_at, combined_score)
                if best is None or key < best[0]:
                    best = (key, m_prop, s_prop, start_at, None, None)
                    
                if is_urgent:
                    u_start_at = max(_slot_at(m_prop, True), _slot_at(s_prop, True))
                    u_combined_score = _score(m_prop, True) + _score(s_prop, True)
                    if u_start_at < start_at:
                        u_key = (u_start_at, u_combined_score)
                        preempt_m = m_prop.get("preempt_target")
                        preempt_s = s_prop.get("preempt_target")
                        if best is None or u_key < best[0]:
                            best = (u_key, m_prop, s_prop, u_start_at, preempt_m, preempt_s)

        if best:
            _, m_prop, s_prop, start_at, preempt_m, preempt_s = best
            return m_prop, s_prop, start_at, preempt_m, preempt_s
            
        return None, None, None, None, None

