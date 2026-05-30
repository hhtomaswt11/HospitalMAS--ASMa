"""
metrics.py — Módulo de métricas de simulação hospitalar.

Regista e calcula:
  - Número de doentes atendidos por tipo (rotina/urgência) e por hospital
  - Tempo médio de espera (spawn → início de consulta/atendimento)
    incluindo média global combinada (rotina + urgência)
  - Número de doentes que esgotaram retentativas, com detalhe por
    procedimento (exame, cirurgia, internamento) e por motivo

Todas as operações são thread-safe via RLock interno.
Deduplicação explícita via conjuntos internos:
  - _ATTENDED_IDS  → evita duplo registo do mesmo atendimento
  - _FAILED_IDS    → chave (doente_jid, procedimento) para falhas
"""
from __future__ import annotations

import json
import os
import time
from threading import RLock
from typing import Dict, List, Optional, Set, Tuple

_LOCK = RLock()

# ─────────────────────────────────────────────────────────────
#  Estrutura de métricas por hospital
# ─────────────────────────────────────────────────────────────
def _empty_hospital_metrics() -> dict:
    return {
        # Atendidos
        "atendidos_rotina": 0,
        "atendidos_urgencia": 0,
        "atendidos_total": 0,
        # Tempos de espera — listas de floats (segundos reais)
        "tempos_espera_rotina": [],
        "tempos_espera_urgencia": [],
        # Abandonados (esgotaram retentativas)
        "abandonados_rotina": 0,
        "abandonados_urgencia": 0,
        "abandonados_total": 0,
        # Falhas com detalhe (da Versão B)
        "abandonados_por_procedimento": {},   # e.g. {"exame": 3, "cirurgia": 1}
        "abandonados_por_motivo": {},         # e.g. {"sem médico": 2, ...}
    }


_METRICS: Dict[str, dict] = {
    "h1": _empty_hospital_metrics(),
    "h2": _empty_hospital_metrics(),
    "global": _empty_hospital_metrics(),
}

# Registo de tempos de spawn por doente_jid → timestamp real
_SPAWN_TIMES: Dict[str, float] = {}

# Conjuntos de deduplicação (da Versão B)
_ATTENDED_IDS: Set[str] = set()
_FAILED_IDS: Set[Tuple[str, str]] = set()  # (doente_jid, procedimento)


# ─────────────────────────────────────────────────────────────
#  API pública
# ─────────────────────────────────────────────────────────────

def register_spawn(doente_jid: str) -> None:
    """Regista o momento de criação de um doente (para cálculo de espera)."""
    with _LOCK:
        _SPAWN_TIMES[doente_jid] = time.time()


def register_attended(
    doente_jid: str,
    tipo: str,
    hospital_id: int,
    attended_at: Optional[float] = None,
) -> bool:
    """Regista um doente como atendido e calcula o tempo de espera.

    Retorna False se o doente já foi registado (deduplicação).

    Args:
        doente_jid: JID do doente.
        tipo: 'rotina' | 'urgencia' (insensitive).
        hospital_id: 1 ou 2.
        attended_at: timestamp real do início do atendimento (default: agora).
    """
    attended_at = attended_at or time.time()
    tipo_norm = _normalize_tipo(tipo)
    h_key = _hospital_key(hospital_id)

    with _LOCK:
        if doente_jid in _ATTENDED_IDS:
            return False  # já registado — ignora
        _ATTENDED_IDS.add(doente_jid)

        spawn_ts = _SPAWN_TIMES.pop(doente_jid, None)
        wait_seconds = (attended_at - spawn_ts) if spawn_ts is not None else None

        for key in (h_key, "global"):
            m = _METRICS[key]
            if tipo_norm == "rotina":
                m["atendidos_rotina"] += 1
                if wait_seconds is not None:
                    m["tempos_espera_rotina"].append(wait_seconds)
            else:
                m["atendidos_urgencia"] += 1
                if wait_seconds is not None:
                    m["tempos_espera_urgencia"].append(wait_seconds)
            m["atendidos_total"] += 1
    return True


def register_abandoned(
    doente_jid: str,
    tipo: str,
    hospital_id: int,
    procedimento: str = "desconhecido",
    motivo: str = "",
) -> bool:
    """Regista um doente que esgotou retentativas e saiu sem ser atendido.

    Retorna False se (doente_jid, procedimento) já foi registado.

    Args:
        doente_jid: JID do doente.
        tipo: 'rotina' | 'urgencia' (insensitive).
        hospital_id: 1 ou 2.
        procedimento: ex. 'exame', 'cirurgia', 'internamento'.
        motivo: descrição da causa da falha.
    """
    tipo_norm = _normalize_tipo(tipo)
    h_key = _hospital_key(hospital_id)
    fail_key = (doente_jid, procedimento)

    with _LOCK:
        if fail_key in _FAILED_IDS:
            return False  # já registado — ignora
        _FAILED_IDS.add(fail_key)

        _SPAWN_TIMES.pop(doente_jid, None)  # limpa o registo de spawn

        for key in (h_key, "global"):
            m = _METRICS[key]
            if tipo_norm == "rotina":
                m["abandonados_rotina"] += 1
            else:
                m["abandonados_urgencia"] += 1
            m["abandonados_total"] += 1

            # Detalhe por procedimento e motivo
            by_proc = m["abandonados_por_procedimento"]
            by_proc[procedimento] = by_proc.get(procedimento, 0) + 1
            if motivo:
                by_mot = m["abandonados_por_motivo"]
                by_mot[motivo] = by_mot.get(motivo, 0) + 1
    return True


def get_summary(hospital_id: Optional[int] = None) -> dict:
    """Devolve um snapshot calculado das métricas.

    Inclui média global combinada (rotina + urgência).

    Args:
        hospital_id: 1, 2 ou None (global).
    """
    key = _hospital_key(hospital_id) if hospital_id is not None else "global"
    with _LOCK:
        m = _METRICS[key]
        wait_rotina = list(m["tempos_espera_rotina"])
        wait_urg = list(m["tempos_espera_urgencia"])
        by_proc = dict(m["abandonados_por_procedimento"])
        by_mot = dict(m["abandonados_por_motivo"])

    def _avg(lst: List[float]) -> Optional[float]:
        return round(sum(lst) / len(lst), 2) if lst else None

    all_waits = wait_rotina + wait_urg

    return {
        "hospital": hospital_id or "global",
        # Atendidos
        "atendidos_rotina": m["atendidos_rotina"],
        "atendidos_urgencia": m["atendidos_urgencia"],
        "atendidos_total": m["atendidos_total"],
        # Tempos de espera
        "media_espera_rotina_s": _avg(wait_rotina),
        "media_espera_urgencia_s": _avg(wait_urg),
        "media_espera_global_s": _avg(all_waits),          # ← novo (Versão B)
        "amostras_espera_rotina": len(wait_rotina),
        "amostras_espera_urgencia": len(wait_urg),
        # Abandonados
        "abandonados_rotina": m["abandonados_rotina"],
        "abandonados_urgencia": m["abandonados_urgencia"],
        "abandonados_total": m["abandonados_total"],
        "abandonados_por_procedimento": by_proc,            # ← novo (Versão B)
        "abandonados_por_motivo": by_mot,                   # ← novo (Versão B)
    }


def get_all_summaries() -> dict:
    """Devolve todas as métricas (H1, H2, global) de uma só vez."""
    return {
        "h1": get_summary(1),
        "h2": get_summary(2),
        "global": get_summary(None),
    }


def dump_metrics(path: str = "data/metrics.json") -> None:
    """Persiste as métricas calculadas em JSON (escrita atómica)."""
    summaries = get_all_summaries()
    summaries["_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tmp = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(summaries, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        print(f"[METRICS] dump_metrics falhou: {exc}")


def reset() -> None:
    """Reinicia todas as métricas (útil entre simulações / testes)."""
    with _LOCK:
        for key in _METRICS:
            _METRICS[key] = _empty_hospital_metrics()
        _SPAWN_TIMES.clear()
        _ATTENDED_IDS.clear()
        _FAILED_IDS.clear()


# ─────────────────────────────────────────────────────────────
#  Helpers internos
# ─────────────────────────────────────────────────────────────

def _normalize_tipo(tipo: str) -> str:
    """Normaliza o tipo de doente para 'rotina' ou 'urgencia'."""
    t = str(tipo).lower()
    if t in {"normal", "rotina", "routine"}:
        return "rotina"
    return "urgencia"


def _hospital_key(hospital_id) -> str:
    return f"h{hospital_id}" if hospital_id in (1, 2) else "global"
