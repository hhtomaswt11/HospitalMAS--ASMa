"""Helpers de agenda/tempo simulado para consultas de rotina.

Este módulo concentra a validação temporal pedida para a marcação realista de
consultas: slots, turnos dos médicos, janela administrativa de rotina e
sobreposição de médico/sala.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Tuple

from src.config import (
    CONSULTATION_SLOT_SECONDS,
    ROUTINE_END_H,
    ROUTINE_START_H,
    SIM_DAY_SECONDS,
    SIM_HOUR_SECONDS,
)

SHIFT_WINDOWS_HOURS = {
    "morning": (8.0, 16.0),
    "afternoon": (16.0, 24.0),
    "night": (0.0, 8.0),
}

ACTIVE_STATES = {"agendada", "em curso", "reservada", "scheduled", "in_progress", None}


def sim_day_and_hour(abs_time: float, sim_start_time: float) -> Tuple[int, float]:
    """Return (zero-based day, simulated hour in [0, 24))."""
    elapsed = max(0.0, float(abs_time) - float(sim_start_time))
    day = int(elapsed // SIM_DAY_SECONDS)
    hour = (elapsed % SIM_DAY_SECONDS) / SIM_HOUR_SECONDS
    return day, hour


def sim_time_label(abs_time: float, sim_start_time: float) -> str:
    """Human-readable simulated time label, e.g. 'D1 08:15'."""
    day, hour = sim_day_and_hour(abs_time, sim_start_time)
    h = int(hour)
    minutes_float = (hour - h) * 60.0
    m = int(round(minutes_float))
    if m >= 60:
        h += 1
        m -= 60
    if h >= 24:
        day += 1
        h -= 24
    return f"D{day + 1} {h:02d}:{m:02d}"


def ceil_to_slot(abs_time: float, sim_start_time: float) -> float:
    """Round an absolute timestamp up to the next configured consultation slot."""
    if abs_time <= sim_start_time:
        return sim_start_time
    offset = abs_time - sim_start_time
    slots = math.ceil((offset - 1e-9) / CONSULTATION_SLOT_SECONDS)
    return sim_start_time + slots * CONSULTATION_SLOT_SECONDS


def day_hour_to_abs(sim_start_time: float, day: int, hour: float) -> float:
    return sim_start_time + day * SIM_DAY_SECONDS + hour * SIM_HOUR_SECONDS


def routine_interval_for_doctor(profile: Dict, sim_start_time: float, day: int) -> Optional[Tuple[float, float]]:
    """Intersection between doctor's shift and routine-consultation window."""
    shift = profile.get("shift")
    shift_window = SHIFT_WINDOWS_HOURS.get(shift)
    if shift_window is None:
        return None

    shift_start_h, shift_end_h = shift_window
    start_h = max(float(ROUTINE_START_H), shift_start_h)
    end_h = min(float(ROUTINE_END_H), shift_end_h)
    if start_h >= end_h:
        return None
    return day_hour_to_abs(sim_start_time, day, start_h), day_hour_to_abs(sim_start_time, day, end_h)


def _entry_interval(entry: Dict, default_duration: float) -> Optional[Tuple[float, float]]:
    start = (
        entry.get("start_at")
        or entry.get("consultation_start_at")
        or entry.get("exam_start_at")
        or entry.get("surgery_start_at")
    )
    if start is None:
        return None
    try:
        start = float(start)
    except Exception:
        return None

    end = entry.get("end_at") or entry.get("consultation_end_at")
    if end is None:
        if "surgery_start_at" in entry:
            end = start + float(entry.get("surgery_duration_seconds", default_duration))
        elif "exam_start_at" in entry:
            # conservative fallback; caller can pass exam duration if needed
            end = start + default_duration
        else:
            end = start + default_duration
    try:
        end = float(end)
    except Exception:
        end = start + default_duration
    return start, end


def interval_overlaps(start: float, end: float, other_start: float, other_end: float) -> bool:
    return start < other_end and other_start < end


def is_interval_free(schedule: Iterable[Dict], start: float, end: float, default_duration: float) -> bool:
    """True if [start, end) does not overlap active scheduled intervals."""
    for entry in schedule:
        if not isinstance(entry, dict):
            continue
        estado = entry.get("estado")
        if estado not in ACTIVE_STATES:
            continue
        interval = _entry_interval(entry, default_duration)
        if interval is None:
            continue
        if interval_overlaps(start, end, interval[0], interval[1]):
            return False
    return True


def find_next_routine_slot_for_pair(
    medico_profile: Dict,
    medico_schedule: List[Dict],
    sala_schedule: List[Dict],
    earliest_start: float,
    duration: float,
    sim_start_time: float,
    lookahead_days: int = 7,
) -> Optional[Tuple[float, float]]:
    """Find the earliest slot valid for both doctor and room.

    The slot must be inside the doctor's real shift, inside the configured
    routine-consultation window and free in both schedules.
    """
    first_day, _ = sim_day_and_hour(earliest_start, sim_start_time)
    cursor_floor = ceil_to_slot(earliest_start, sim_start_time)

    for day in range(first_day, first_day + max(1, lookahead_days)):
        interval = routine_interval_for_doctor(medico_profile, sim_start_time, day)
        if interval is None:
            continue
        interval_start, interval_end = interval
        cursor = ceil_to_slot(max(cursor_floor, interval_start), sim_start_time)

        while cursor + duration <= interval_end + 1e-9:
            end = cursor + duration
            if (
                is_interval_free(medico_schedule, cursor, end, duration)
                and is_interval_free(sala_schedule, cursor, end, duration)
            ):
                return cursor, end
            cursor += CONSULTATION_SLOT_SECONDS

    return None


def validate_routine_slot(
    medico_profile: Dict,
    start_at: float,
    end_at: float,
    sim_start_time: float,
) -> bool:
    """Validate that a routine slot fits the doctor's shift and routine window."""
    day, _ = sim_day_and_hour(start_at, sim_start_time)
    interval = routine_interval_for_doctor(medico_profile, sim_start_time, day)
    if interval is None:
        return False
    interval_start, interval_end = interval
    return start_at >= interval_start - 1e-9 and end_at <= interval_end + 1e-9
