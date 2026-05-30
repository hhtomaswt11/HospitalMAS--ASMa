from src.agents.Coordinators.coordenador_base import CoordenadorBase


def make_coord():
    return CoordenadorBase(
        "coord_test@localhost",
        "password",
        hospital_config={"supervisor": "supervisor_test@localhost"},
    )


def test_enqueue_dequeue_deduplicates_by_patient_jid():
    coord = make_coord()
    patient = {"doente_jid": "doente1@localhost", "prioridade": 2}

    assert coord.enqueue(patient) is True
    assert coord.enqueue(dict(patient)) is False
    assert coord.total_pending() == 1

    removed = coord.dequeue("doente1@localhost")
    assert removed["doente_jid"] == "doente1@localhost"
    assert coord.total_pending() == 0
    assert coord.dequeue("doente1@localhost") is None


def test_select_best_resource_pair_prefers_earliest_common_start_then_score():
    coord = make_coord()
    medicos = [
        {"medico": "m1", "slot_at": 30.0, "score": 1},
        {"medico": "m2", "slot_at": 10.0, "score": 10},
    ]
    salas = [
        {"sala": "s1", "slot_at": 10.0, "score": 3},
        {"sala": "s2", "slot_at": 30.0, "score": 0},
    ]

    medico, sala, start_at, preempt_medico, preempt_sala = coord.select_best_resource_pair(
        medicos, salas, {"tipo": "Normal", "tipo_original": "Normal"}
    )

    assert medico["medico"] == "m2"
    assert sala["sala"] == "s1"
    assert start_at == 10.0
    assert preempt_medico is None
    assert preempt_sala is None


def test_select_best_resource_pair_allows_urgent_preemption_when_better():
    coord = make_coord()
    medicos = [{
        "medico": "m1",
        "slot_at": 50.0,
        "score": 1,
        "slot_at_urgency": 5.0,
        "score_urgency": 1,
        "preempt_target": "consulta_rotina_1",
    }]
    salas = [{
        "sala": "s1",
        "slot_at": 50.0,
        "score": 1,
        "slot_at_urgency": 5.0,
        "score_urgency": 1,
        "preempt_target": "sala_rotina_1",
    }]

    medico, sala, start_at, preempt_medico, preempt_sala = coord.select_best_resource_pair(
        medicos, salas, {"tipo": "Urgencia", "tipo_original": "Urgencia"}
    )

    assert medico["medico"] == "m1"
    assert sala["sala"] == "s1"
    assert start_at == 5.0
    assert preempt_medico == "consulta_rotina_1"
    assert preempt_sala == "sala_rotina_1"
