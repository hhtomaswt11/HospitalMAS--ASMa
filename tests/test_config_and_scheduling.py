from src.config import arrival_rate_for_hour, CONSULTATION_SLOT_SECONDS
from src.scheduling import find_next_routine_slot_for_pair


def test_arrival_rate_for_hour_respects_routine_window_and_profiles():
    assert arrival_rate_for_hour("Normal", 7, base_rate=10) == 0.0
    assert arrival_rate_for_hour("Normal", 9, base_rate=10) == 18.0
    assert arrival_rate_for_hour("Urgencia", 9, base_rate=10) == 12.5


def test_find_next_routine_slot_for_pair_uses_first_free_slot():
    sim_start = 0.0
    duration = 2.5
    medico_profile = {"shift": "morning"}

    first_slot = find_next_routine_slot_for_pair(
        medico_profile=medico_profile,
        medico_schedule=[],
        sala_schedule=[],
        earliest_start=0.0,
        duration=duration,
        sim_start_time=sim_start,
    )
    assert first_slot == (80.0, 82.5)

    occupied = [{"start_at": 80.0, "end_at": 82.5, "estado": "agendada"}]
    second_slot = find_next_routine_slot_for_pair(
        medico_profile=medico_profile,
        medico_schedule=occupied,
        sala_schedule=[],
        earliest_start=0.0,
        duration=duration,
        sim_start_time=sim_start,
    )
    assert second_slot == (80.0 + CONSULTATION_SLOT_SECONDS, 82.5 + CONSULTATION_SLOT_SECONDS)
