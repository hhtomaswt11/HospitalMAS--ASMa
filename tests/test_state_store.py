from src.state_store import DashboardStateStore


def test_state_store_keeps_hospitals_namespaced_and_builds_aggregates():
    store = DashboardStateStore()
    h1_patient = {"doente_jid": "h1_patient@localhost"}
    h2_patient = {"doente_jid": "h2_patient@localhost"}

    store.update_waitlist(1, "routine", [h1_patient], {"Cardiologia": [h1_patient]})
    store.update_waitlist(2, "routine", [h2_patient], {"Ortopedia": [h2_patient]})

    snapshot = store.build_state_snapshot(sim_time=42)
    waitlist = snapshot["waitlist"]

    assert waitlist["h1_routine"] == [h1_patient]
    assert waitlist["h2_routine"] == [h2_patient]
    assert waitlist["routine"] == [h1_patient, h2_patient]
    assert waitlist["routine_by_specialty"]["Cardiologia"] == [h1_patient]
    assert waitlist["routine_by_specialty"]["Ortopedia"] == [h2_patient]


def test_state_store_records_metrics_for_started_and_failed_patients():
    store = DashboardStateStore()
    store.record_metrics_event(1, {
        "event": "patient_started",
        "doente_jid": "p1@localhost",
        "tipo": "Normal",
        "spawned_at": 10.0,
        "actual_start_at": 16.0,
    })
    store.record_metrics_event(1, {
        "event": "patient_failed_after_retries",
        "doente_jid": "p2@localhost",
        "procedure": "exam",
        "reason": "timeout",
    })

    metrics = store.build_state_snapshot(sim_time=0)["metrics"]["by_hospital"]["h1"]
    assert metrics["attended_by_type"]["routine"] == 1
    assert metrics["average_wait_seconds"]["routine"] == 6.0
    assert metrics["failed_after_retries"] == 1
    assert metrics["failed_after_retries_by_procedure"]["exam"] == 1
    assert metrics["failed_after_retries_by_reason"]["timeout"] == 1
