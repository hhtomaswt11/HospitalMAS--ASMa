"""
tests/test_simulation.py — Testes de unidade para o sistema multiagente hospitalar.

Cobre:
  1. arrival_rate_for_hour           (src/config.py)
  2. find_next_routine_slot_for_pair (src/scheduling.py)
  3. CoordenadorBase.enqueue/dequeue (src/agents/Coordinators/coordenador_base.py)
  4. select_best_resource_pair       (src/agents/Coordinators/coordenador_base.py)
  5. Módulo de métricas              (src/metrics.py)

Dependências de SPADE são resolvidas pelo conftest.py desta pasta,
que injeta fakes de spade.agent, spade.message e spade.behaviour
antes de qualquer import, eliminando a necessidade de stubs manuais.
"""

import sys
import os

# Garante que a raiz do projecto está no sys.path quando o ficheiro é
# invocado directamente: python3 tests/test_simulation.py -v
# (O conftest.py também faz isto, mas a ordem de import pode variar.)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Carrega os fakes de SPADE antes de qualquer import do projecto.
import tests.conftest  # noqa: F401 — efeito lateral: injeta mocks em sys.modules

import time
import unittest

# ─────────────────────────────────────────────────────────────
# 1. arrival_rate_for_hour
# ─────────────────────────────────────────────────────────────
from src.config import (
    arrival_rate_for_hour,
    ARRIVAL_RATE_NORMAL_BASE,
    ARRIVAL_RATE_URGENT_BASE,
    ROUTINE_START_H,
    ROUTINE_END_H,
)


class TestArrivalRateForHour(unittest.TestCase):

    def test_normal_inside_window_returns_positive_rate(self):
        """Taxa de chegada de rotina deve ser positiva dentro da janela administrativa."""
        for hour in [8, 10, 14, 19]:
            rate = arrival_rate_for_hour("Normal", float(hour))
            self.assertGreater(rate, 0.0,
                msg=f"Esperava taxa > 0 para hora {hour} (Normal)")

    def test_normal_outside_window_returns_zero(self):
        """Taxa de chegada de rotina deve ser zero fora da janela 08h-20h."""
        for hour in [0, 3, 7, 20, 23]:
            rate = arrival_rate_for_hour("Normal", float(hour))
            self.assertEqual(rate, 0.0,
                msg=f"Esperava taxa=0 fora da janela para hora {hour}")

    def test_urgent_nonzero_all_day(self):
        """Urgências devem ter taxa positiva a qualquer hora do dia."""
        for hour in range(0, 24):
            rate = arrival_rate_for_hour("Urgencia", float(hour))
            self.assertGreater(rate, 0.0,
                msg=f"Esperava taxa urgente > 0 para hora {hour}")

    def test_custom_base_rate_is_respected(self):
        """A taxa personalizada deve usar o mesmo multiplicador de perfil que a taxa global."""
        custom_base = 5.0
        rate = arrival_rate_for_hour("Urgencia", 10.0, base_rate=custom_base)
        default_rate = arrival_rate_for_hour("Urgencia", 10.0)
        ratio_custom = rate / custom_base
        ratio_default = default_rate / ARRIVAL_RATE_URGENT_BASE
        self.assertAlmostEqual(ratio_custom, ratio_default, places=5,
            msg="O multiplicador do perfil deve ser o mesmo independentemente da taxa base")

    def test_peak_morning_higher_than_midday(self):
        """O pico da manhã (08h-10h) deve ter taxa mais alta que o período calmo (12h-14h)."""
        rate_peak = arrival_rate_for_hour("Normal", 9.0)
        rate_calm = arrival_rate_for_hour("Normal", 13.0)
        self.assertGreater(rate_peak, rate_calm,
            msg="Pico da manhã deve ter taxa superior ao período calmo")


# ─────────────────────────────────────────────────────────────
# 2. find_next_routine_slot_for_pair
# ─────────────────────────────────────────────────────────────
from src.scheduling import (
    find_next_routine_slot_for_pair,
    sim_day_and_hour,
)
from src.config import (
    SIM_HOUR_SECONDS,
    CONSULTATION_DURATION_NORMAL_SECONDS,
)


def _sim_start_at_8h():
    """Devolve um sim_start_time tal que t=agora corresponde às 08h00."""
    return time.time() - 8 * SIM_HOUR_SECONDS


class TestFindNextRoutineSlot(unittest.TestCase):

    def _morning_profile(self):
        return {"shift": "morning", "specialty": "cardiologia", "consult_mode": "routine"}

    def test_returns_slot_within_shift_and_routine_window(self):
        """O slot devolvido deve cair dentro do turno do médico E da janela de rotina."""
        sim_start = _sim_start_at_8h()
        result = find_next_routine_slot_for_pair(
            medico_profile=self._morning_profile(),
            medico_schedule=[],
            sala_schedule=[],
            earliest_start=time.time(),
            duration=CONSULTATION_DURATION_NORMAL_SECONDS,
            sim_start_time=sim_start,
            lookahead_days=7,
        )
        self.assertIsNotNone(result, "Devia encontrar um slot para um médico de manhã")
        start_at, end_at = result
        self.assertGreater(end_at, start_at)
        _, h_start = sim_day_and_hour(start_at, sim_start)
        self.assertGreaterEqual(h_start, float(ROUTINE_START_H) - 1e-6)
        self.assertLess(h_start, float(ROUTINE_END_H))

    def test_slot_respects_duration(self):
        """A duração do slot deve ser pelo menos a duração da consulta."""
        sim_start = _sim_start_at_8h()
        duration = CONSULTATION_DURATION_NORMAL_SECONDS
        result = find_next_routine_slot_for_pair(
            medico_profile=self._morning_profile(),
            medico_schedule=[],
            sala_schedule=[],
            earliest_start=time.time(),
            duration=duration,
            sim_start_time=sim_start,
        )
        self.assertIsNotNone(result)
        start_at, end_at = result
        self.assertGreaterEqual(end_at - start_at, duration - 1e-6)

    def test_no_overlap_with_existing_schedule(self):
        """Não deve ser atribuído um slot que sobreponha uma consulta já agendada."""
        sim_start = _sim_start_at_8h()
        duration = CONSULTATION_DURATION_NORMAL_SECONDS
        first_start, first_end = find_next_routine_slot_for_pair(
            medico_profile=self._morning_profile(),
            medico_schedule=[],
            sala_schedule=[],
            earliest_start=time.time(),
            duration=duration,
            sim_start_time=sim_start,
        )
        occupied = {"start_at": first_start, "end_at": first_end,
                    "consultation_start_at": first_start, "consultation_end_at": first_end,
                    "estado": "agendada"}
        second_start, second_end = find_next_routine_slot_for_pair(
            medico_profile=self._morning_profile(),
            medico_schedule=[occupied],
            sala_schedule=[],
            earliest_start=time.time(),
            duration=duration,
            sim_start_time=sim_start,
        )
        overlaps = (second_start < first_end) and (first_start < second_end)
        self.assertFalse(overlaps, "O segundo slot não deve sobrepor o primeiro")

    def test_night_shift_doctor_outside_routine_window_returns_none(self):
        """Um médico de noite (00h-08h) não tem interseção com a janela de rotina."""
        sim_start = _sim_start_at_8h()
        result = find_next_routine_slot_for_pair(
            medico_profile={"shift": "night"},
            medico_schedule=[],
            sala_schedule=[],
            earliest_start=time.time(),
            duration=CONSULTATION_DURATION_NORMAL_SECONDS,
            sim_start_time=sim_start,
            lookahead_days=1,
        )
        self.assertIsNone(result,
            "Médico de noite não deve ter slots de rotina (janela sem interseção)")


# ─────────────────────────────────────────────────────────────
# 3. CoordenadorBase.enqueue / dequeue
#    Usa CoordenadorBase directamente (sem stub manual) graças ao conftest.py
# ─────────────────────────────────────────────────────────────
from src.agents.Coordinators.coordenador_base import CoordenadorBase


def _make_coord() -> CoordenadorBase:
    """Instancia CoordenadorBase real com fakes de SPADE injectados pelo conftest."""
    return CoordenadorBase(
        "coord_test@localhost",
        "password",
        hospital_config={"supervisor": "supervisor@localhost"},
    )


class TestCoordenadorBaseQueue(unittest.TestCase):

    def setUp(self):
        self.coord = _make_coord()

    def _patient(self, jid: str, priority: int = 3) -> dict:
        return {"doente_jid": jid, "nome": f"Doente_{jid}", "prioridade": priority}

    def test_enqueue_adds_patient(self):
        """Enqueue deve adicionar um doente à fila."""
        result = self.coord.enqueue(self._patient("joao@h1"))
        self.assertTrue(result)
        self.assertEqual(len(self.coord.pending_requests), 1)
        self.assertIn("joao@h1", self.coord.pending_patient_ids)

    def test_enqueue_duplicate_is_rejected(self):
        """Enqueue deve rejeitar duplicados pelo JID do doente."""
        p = self._patient("joao@h1")
        self.coord.enqueue(p)
        self.assertFalse(self.coord.enqueue(dict(p)))
        self.assertEqual(len(self.coord.pending_requests), 1)

    def test_dequeue_removes_and_returns_patient(self):
        """Dequeue deve remover e devolver o doente correto."""
        self.coord.enqueue(self._patient("alice@h1"))
        self.coord.enqueue(self._patient("bob@h1"))
        removed = self.coord.dequeue("alice@h1")
        self.assertIsNotNone(removed)
        self.assertEqual(removed["doente_jid"], "alice@h1")
        self.assertEqual(len(self.coord.pending_requests), 1)
        self.assertNotIn("alice@h1", self.coord.pending_patient_ids)

    def test_dequeue_nonexistent_returns_none(self):
        """Dequeue de um JID inexistente deve devolver None sem erros."""
        self.assertIsNone(self.coord.dequeue("ninguem@h1"))

    def test_enqueue_sets_defaults(self):
        """Enqueue deve inicializar _retry_count=0 e _next_retry_at=0.0."""
        self.coord.enqueue(self._patient("carlos@h1"))
        req = self.coord.pending_requests[0]
        self.assertEqual(req.get("_retry_count"), 0)
        self.assertAlmostEqual(req.get("_next_retry_at"), 0.0)

    def test_total_pending(self):
        """total_pending deve reflectir o tamanho actual da fila."""
        self.assertEqual(self.coord.total_pending(), 0)
        self.coord.enqueue(self._patient("d1@h1"))
        self.coord.enqueue(self._patient("d2@h1"))
        self.assertEqual(self.coord.total_pending(), 2)


# ─────────────────────────────────────────────────────────────
# 4. select_best_resource_pair
# ─────────────────────────────────────────────────────────────

class TestSelectBestResourcePair(unittest.TestCase):

    def setUp(self):
        self.coord = _make_coord()

    def _medico(self, jid, slot_at, score=1, **kw):
        return {"medico_jid": jid, "nome_medico": jid, "slot_at": slot_at, "score": score, **kw}

    def _sala(self, jid, slot_at, score=1, **kw):
        return {"sala_jid": jid, "nome_sala": jid, "slot_at": slot_at, "score": score, **kw}

    def test_returns_none_when_no_proposals(self):
        """Sem propostas deve devolver (None, None, None, None, None)."""
        self.assertEqual(self.coord.select_best_resource_pair([], [], {}),
                         (None, None, None, None, None))

    def test_selects_earliest_common_slot(self):
        """Deve seleccionar o par com o slot mais cedo."""
        now = time.time()
        m_prop, s_prop, start_at, _, _ = self.coord.select_best_resource_pair(
            [self._medico("m2@h1", now + 100), self._medico("m1@h1", now + 10)],
            [self._sala("s2@h1", now + 100), self._sala("s1@h1", now + 10)],
            {"tipo": "Normal", "tipo_original": "Normal"},
        )
        self.assertEqual(m_prop["medico_jid"], "m1@h1")
        self.assertEqual(s_prop["sala_jid"], "s1@h1")
        self.assertAlmostEqual(start_at, now + 10, delta=1.0)

    def test_returns_none_when_only_medic_proposals(self):
        """Sem propostas de sala deve devolver None."""
        self.assertEqual(
            self.coord.select_best_resource_pair(
                [self._medico("m1@h1", time.time())], [], {}),
            (None, None, None, None, None),
        )

    def test_urgent_preemption_selects_urgency_slot(self):
        """Para urgência com slot_at_urgency, deve usar o slot de preempção."""
        now = time.time()
        m = self._medico("m1@h1", now + 50,
                         slot_at_urgency=now + 5,
                         score_urgency=1,
                         preempt_target="rotina_m1")
        s = self._sala("s1@h1", now + 50,
                       slot_at_urgency=now + 5,
                       score_urgency=1,
                       preempt_target="rotina_s1")
        m_prop, s_prop, start_at, preempt_m, preempt_s = self.coord.select_best_resource_pair(
            [m], [s], {"tipo": "Urgencia", "tipo_original": "Urgencia"})
        self.assertAlmostEqual(start_at, now + 5, delta=1.0)
        self.assertEqual(preempt_m, "rotina_m1")
        self.assertEqual(preempt_s, "rotina_s1")


# ─────────────────────────────────────────────────────────────
# 5. Módulo de métricas — inclui novos campos da Versão B
# ─────────────────────────────────────────────────────────────
import src.metrics as metrics


class TestMetrics(unittest.TestCase):

    def setUp(self):
        """Estado limpo antes de cada teste."""
        metrics.reset()

    # ── Atendidos ─────────────────────────────────────────────

    def test_register_spawn_and_attended_computes_wait(self):
        """Depois de spawn e attended, o tempo de espera deve ser positivo."""
        metrics.register_spawn("alice@h1")
        time.sleep(0.05)
        metrics.register_attended("alice@h1", "Normal", hospital_id=1)
        s = metrics.get_summary(1)
        self.assertEqual(s["atendidos_rotina"], 1)
        self.assertIsNotNone(s["media_espera_rotina_s"])
        self.assertGreater(s["media_espera_rotina_s"], 0.0)

    def test_attended_deduplication_ignores_second_call(self):
        """O mesmo JID não deve ser contado duas vezes como atendido."""
        metrics.register_spawn("dup@h1")
        metrics.register_attended("dup@h1", "Normal", hospital_id=1)
        metrics.register_attended("dup@h1", "Normal", hospital_id=1)  # duplicado
        self.assertEqual(metrics.get_summary(1)["atendidos_total"], 1)

    def test_attended_without_spawn_still_counts(self):
        """Atendimento sem spawn prévio deve contar, mas sem tempo de espera."""
        metrics.register_attended("novo@h1", "Normal", hospital_id=1)
        s = metrics.get_summary(1)
        self.assertEqual(s["atendidos_rotina"], 1)
        self.assertEqual(s["amostras_espera_rotina"], 0)
        self.assertIsNone(s["media_espera_rotina_s"])

    def test_global_aggregates_both_hospitals(self):
        """A vista global deve agregar H1 e H2."""
        metrics.register_attended("p1@h1", "Normal", hospital_id=1)
        metrics.register_attended("p2@h2", "Urgencia", hospital_id=2)
        g = metrics.get_summary(None)
        self.assertEqual(g["atendidos_total"], 2)
        self.assertEqual(g["atendidos_rotina"], 1)
        self.assertEqual(g["atendidos_urgencia"], 1)

    def test_overall_wait_combines_routine_and_urgency(self):
        """media_espera_global_s deve ser a média de rotina + urgência combinados."""
        metrics.register_spawn("r@h1")
        time.sleep(0.02)
        metrics.register_attended("r@h1", "Normal", hospital_id=1)
        metrics.register_spawn("u@h1")
        time.sleep(0.02)
        metrics.register_attended("u@h1", "Urgencia", hospital_id=1)
        s = metrics.get_summary(1)
        self.assertIsNotNone(s["media_espera_global_s"])
        self.assertGreater(s["media_espera_global_s"], 0.0)

    # ── Abandonados ───────────────────────────────────────────

    def test_register_abandoned_increments_counter(self):
        """register_abandoned deve incrementar o contador de abandonados."""
        metrics.register_abandoned("bob@h2", "Urgencia", hospital_id=2,
                                   procedimento="exame")
        s = metrics.get_summary(2)
        self.assertEqual(s["abandonados_urgencia"], 1)
        self.assertEqual(s["abandonados_total"], 1)
        self.assertEqual(s["atendidos_total"], 0)

    def test_abandoned_by_procedure_is_tracked(self):
        """Falhas devem ser discriminadas por procedimento."""
        metrics.register_abandoned("p1@h1", "urgencia", hospital_id=1,
                                   procedimento="exame")
        metrics.register_abandoned("p2@h1", "urgencia", hospital_id=1,
                                   procedimento="cirurgia")
        metrics.register_abandoned("p3@h1", "urgencia", hospital_id=1,
                                   procedimento="exame")
        s = metrics.get_summary(1)
        self.assertEqual(s["abandonados_por_procedimento"]["exame"], 2)
        self.assertEqual(s["abandonados_por_procedimento"]["cirurgia"], 1)

    def test_abandoned_by_motivo_is_tracked(self):
        """Falhas devem ser discriminadas pelo motivo."""
        metrics.register_abandoned("p1@h1", "urgencia", hospital_id=1,
                                   procedimento="exame", motivo="sem médico")
        metrics.register_abandoned("p2@h1", "urgencia", hospital_id=1,
                                   procedimento="cirurgia", motivo="sem médico")
        s = metrics.get_summary(1)
        self.assertEqual(s["abandonados_por_motivo"]["sem médico"], 2)

    def test_abandoned_deduplication_same_procedure(self):
        """(doente_jid, procedimento) duplicado não deve ser contado duas vezes."""
        metrics.register_abandoned("p1@h1", "urgencia", hospital_id=1, procedimento="exame")
        metrics.register_abandoned("p1@h1", "urgencia", hospital_id=1, procedimento="exame")
        self.assertEqual(metrics.get_summary(1)["abandonados_total"], 1)

    def test_abandoned_different_procedures_are_counted_separately(self):
        """O mesmo doente pode falhar procedimentos diferentes — ambos devem contar."""
        metrics.register_abandoned("p1@h1", "urgencia", hospital_id=1, procedimento="exame")
        metrics.register_abandoned("p1@h1", "urgencia", hospital_id=1, procedimento="cirurgia")
        self.assertEqual(metrics.get_summary(1)["abandonados_total"], 2)

    # ── Reset ─────────────────────────────────────────────────

    def test_reset_clears_all_metrics(self):
        """reset() deve repor todos os contadores a zero."""
        metrics.register_attended("x@h1", "Normal", 1)
        metrics.register_abandoned("y@h1", "urgencia", 1, procedimento="exame")
        metrics.reset()
        g = metrics.get_summary(None)
        self.assertEqual(g["atendidos_total"], 0)
        self.assertEqual(g["abandonados_total"], 0)
        self.assertEqual(g["abandonados_por_procedimento"], {})
        self.assertIsNone(g["media_espera_rotina_s"])
        self.assertIsNone(g["media_espera_global_s"])
        # Após reset, o mesmo JID deve poder ser registado de novo
        self.assertTrue(metrics.register_attended("x@h1", "Normal", 1))


if __name__ == "__main__":
    unittest.main()
