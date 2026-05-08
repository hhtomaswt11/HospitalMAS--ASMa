import re

with open("src/config.py", "r") as f:
    content = f.read()

# Replace H1_CONFIG medicos definition
h1_medicos_replacement = """    medicos_names=[f"medico{i}" for i in range(1, 31)],
    medicos_triagem_names=[f"medico_triagem{i}" for i in range(1, 4)],
    medicos_consultas_routine_names=[f"medico{i}" for i in [1, 2, 3, 12, 13, 14]],
    medicos_consultas_emergency_names=[f"medico{i}" for i in [4, 5, 6, 15, 16, 17, 23, 24, 25]],
    salas_consultas_routine_names=[SALA1, SALA2, SALA3, SALA4, SALA5, SALA6, SALA7],
    salas_consultas_emergency_names=[SALA8, SALA9, SALA10],
    equipamentos_map=[
        (SALA_RAIOX1, SPECIALTY_RX), (SALA_RAIOX2, SPECIALTY_RX),
        (SALA_TAC1, SPECIALTY_TAC), (SALA_TAC2, SPECIALTY_TAC),
        (SALA_ANALISES1, SPECIALTY_ANALISES), (SALA_ANALISES2, SPECIALTY_ANALISES),
    ],
    blocos_names=[BLOCO_OPERATORIO1, BLOCO_OPERATORIO2, BLOCO_OPERATORIO3],
    salas_triagem_names=[SALA_TRIAGEM1, SALA_TRIAGEM2],
    internamento_names=[INTERNAMENTO1, INTERNAMENTO2, INTERNAMENTO3, INTERNAMENTO4],
    enfermeiros_names=[f"enfermeiro{i}" for i in range(1, 7)],"""

content = re.sub(r'    medicos_names=\[MEDICO1.*?enfermeiros_names=\[ENFERMEIRO1, ENFERMEIRO2, ENFERMEIRO3\],', h1_medicos_replacement, content, flags=re.DOTALL)

# Replace H2_CONFIG medicos definition
h2_medicos_replacement = """    medicos_names=[f"h2_medico{i}" for i in range(1, 31)],
    medicos_triagem_names=[f"h2_medico_triagem{i}" for i in range(1, 4)],
    medicos_consultas_routine_names=[f"h2_medico{i}" for i in [1, 2, 3, 12, 13, 14]],
    medicos_consultas_emergency_names=[f"h2_medico{i}" for i in [4, 5, 6, 15, 16, 17, 23, 24, 25]],
    salas_consultas_routine_names=[H2_SALA1, H2_SALA2, H2_SALA3, H2_SALA4, H2_SALA5, H2_SALA6, H2_SALA7],
    salas_consultas_emergency_names=[H2_SALA8, H2_SALA9, H2_SALA10],
    equipamentos_map=[
        (H2_SALA_RAIOX1, SPECIALTY_RX), (H2_SALA_RAIOX2, SPECIALTY_RX),
        (H2_SALA_TAC1, SPECIALTY_TAC), (H2_SALA_TAC2, SPECIALTY_TAC),
        (H2_SALA_ANALISES1, SPECIALTY_ANALISES), (H2_SALA_ANALISES2, SPECIALTY_ANALISES),
    ],
    blocos_names=[H2_BLOCO_OPERATORIO1, H2_BLOCO_OPERATORIO2, H2_BLOCO_OPERATORIO3],
    salas_triagem_names=[H2_SALA_TRIAGEM1, H2_SALA_TRIAGEM2],
    internamento_names=[H2_INTERNAMENTO1, H2_INTERNAMENTO2, H2_INTERNAMENTO3, H2_INTERNAMENTO4],
    enfermeiros_names=[f"h2_enfermeiro{i}" for i in range(1, 7)],"""

content = re.sub(r'    medicos_names=\[H2_MEDICO1.*?enfermeiros_names=\[H2_ENFERMEIRO1, H2_ENFERMEIRO2, H2_ENFERMEIRO3\],', h2_medicos_replacement, content, flags=re.DOTALL)

# Now _build_registry_for_hospital
registry_code = """def _build_registry_for_hospital(prefix, hospital_id, doctor_names=None, names=None):
    \"\"\"Build registry entries for one hospital. prefix='' for H1, 'h2_' for H2.\"\"\"
    p = prefix
    reg = {}
    
    # Morning shift
    reg[jid(f"{p}medico1")] = {"name": f"[H{hospital_id}] Dr(a). Routine Pediatria", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_PEDIATRIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico2")] = {"name": f"[H{hospital_id}] Dr(a). Routine Ortopedia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_ORTOPEDIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico3")] = {"name": f"[H{hospital_id}] Dr(a). Routine Cardiologia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_CARDIOLOGIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "morning"}
    
    reg[jid(f"{p}medico4")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Pediatria", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_PEDIATRIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico5")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Ortopedia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_ORTOPEDIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico6")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Cardiologia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_CARDIOLOGIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "morning"}
    
    reg[jid(f"{p}medico7")] = {"name": f"[H{hospital_id}] Dr(a). RX", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_RX, "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico8")] = {"name": f"[H{hospital_id}] Dr(a). TAC", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_TAC, "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico9")] = {"name": f"[H{hospital_id}] Dr(a). Analises", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id, "shift": "morning"}
    
    reg[jid(f"{p}medico10")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 1", "type": "Especialista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico11")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 2", "type": "Especialista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "morning"}

    # Afternoon shift
    reg[jid(f"{p}medico12")] = {"name": f"[H{hospital_id}] Dr(a). Routine Pediatria", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_PEDIATRIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico13")] = {"name": f"[H{hospital_id}] Dr(a). Routine Ortopedia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_ORTOPEDIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico14")] = {"name": f"[H{hospital_id}] Dr(a). Routine Cardiologia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_CARDIOLOGIA, "consult_mode": "routine", "hospital": hospital_id, "shift": "afternoon"}
    
    reg[jid(f"{p}medico15")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Pediatria", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_PEDIATRIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico16")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Ortopedia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_ORTOPEDIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico17")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Cardiologia", "type": "Especialista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_CARDIOLOGIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "afternoon"}
    
    reg[jid(f"{p}medico18")] = {"name": f"[H{hospital_id}] Dr(a). RX", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_RX, "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico19")] = {"name": f"[H{hospital_id}] Dr(a). TAC", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_TAC, "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico20")] = {"name": f"[H{hospital_id}] Dr(a). Analises", "type": "Especialista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id, "shift": "afternoon"}
    
    reg[jid(f"{p}medico21")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 1", "type": "Especialista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico22")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 2", "type": "Especialista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "afternoon"}

    # Night shift
    reg[jid(f"{p}medico23")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Pediatria", "type": "Urgencista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_PEDIATRIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "night"}
    reg[jid(f"{p}medico24")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Ortopedia", "type": "Urgencista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_ORTOPEDIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "night"}
    reg[jid(f"{p}medico25")] = {"name": f"[H{hospital_id}] Dr(a). Urgent Cardiologia", "type": "Urgencista", "role": "medic", "zone": "normal", "specialty": SPECIALTY_CARDIOLOGIA, "consult_mode": "emergency", "hospital": hospital_id, "shift": "night"}
    
    reg[jid(f"{p}medico26")] = {"name": f"[H{hospital_id}] Dr(a). RX", "type": "Urgencista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_RX, "hospital": hospital_id, "shift": "night"}
    reg[jid(f"{p}medico27")] = {"name": f"[H{hospital_id}] Dr(a). TAC", "type": "Urgencista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_TAC, "hospital": hospital_id, "shift": "night"}
    reg[jid(f"{p}medico28")] = {"name": f"[H{hospital_id}] Dr(a). Analises", "type": "Urgencista", "role": "medic", "zone": "exam", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id, "shift": "night"}
    
    reg[jid(f"{p}medico29")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 1", "type": "Urgencista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "night"}
    reg[jid(f"{p}medico30")] = {"name": f"[H{hospital_id}] Dr(a). Cirurgia 2", "type": "Urgencista", "role": "medic", "zone": "surgery", "specialty": SPECIALTY_CIRURGIA, "hospital": hospital_id, "shift": "night"}

    reg[jid(f"{p}medico_triagem1")] = {"name": f"[H{hospital_id}] Dr. Tiago Pinto",   "type": "Triagem", "role": "triage_medic", "zone": "triage", "specialty": SPECIALTY_TRIAGEM, "hospital": hospital_id, "shift": "morning"}
    reg[jid(f"{p}medico_triagem2")] = {"name": f"[H{hospital_id}] Dra. Leonor Viana", "type": "Triagem", "role": "triage_medic", "zone": "triage", "specialty": SPECIALTY_TRIAGEM, "hospital": hospital_id, "shift": "afternoon"}
    reg[jid(f"{p}medico_triagem3")] = {"name": f"[H{hospital_id}] Dr(a). Triagem 3", "type": "Triagem", "role": "triage_medic", "zone": "triage", "specialty": SPECIALTY_TRIAGEM, "hospital": hospital_id, "shift": "night"}

    reg[jid(f"{p}sala1")] =  {"name": f"[H{hospital_id}] Consultorio 1",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala2")] =  {"name": f"[H{hospital_id}] Consultorio 2",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala3")] =  {"name": f"[H{hospital_id}] Consultorio 3",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala4")] =  {"name": f"[H{hospital_id}] Consultorio 4",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala5")] =  {"name": f"[H{hospital_id}] Consultorio 5",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala6")] =  {"name": f"[H{hospital_id}] Consultorio 6",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala7")] =  {"name": f"[H{hospital_id}] Consultorio 7",  "wing": "primary",    "role": "room", "category": "routine",   "hospital": hospital_id}
    reg[jid(f"{p}sala8")] =  {"name": f"[H{hospital_id}] Consultorio 8",  "wing": "primary",    "role": "room", "category": "emergency", "hospital": hospital_id}
    reg[jid(f"{p}sala9")] =  {"name": f"[H{hospital_id}] Consultorio 9",  "wing": "primary",    "role": "room", "category": "emergency", "hospital": hospital_id}
    reg[jid(f"{p}sala10")] = {"name": f"[H{hospital_id}] Consultorio 10", "wing": "primary",    "role": "room", "category": "emergency", "hospital": hospital_id}

    reg[jid(f"{p}sala_raiox1")] =   {"name": f"[H{hospital_id}] Sala de Raio-X 1",  "wing": "specialized", "role": "room", "specialty": SPECIALTY_RX,       "hospital": hospital_id}
    reg[jid(f"{p}sala_raiox2")] =   {"name": f"[H{hospital_id}] Sala de Raio-X 2",  "wing": "specialized", "role": "room", "specialty": SPECIALTY_RX,       "hospital": hospital_id}
    reg[jid(f"{p}sala_tac1")] =     {"name": f"[H{hospital_id}] Sala de TAC 1",      "wing": "specialized", "role": "room", "specialty": SPECIALTY_TAC,      "hospital": hospital_id}
    reg[jid(f"{p}sala_tac2")] =     {"name": f"[H{hospital_id}] Sala de TAC 2",      "wing": "specialized", "role": "room", "specialty": SPECIALTY_TAC,      "hospital": hospital_id}
    reg[jid(f"{p}sala_analises1")] ={"name": f"[H{hospital_id}] Sala de Analises 1", "wing": "specialized", "role": "room", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id}
    reg[jid(f"{p}sala_analises2")] ={"name": f"[H{hospital_id}] Sala de Analises 2", "wing": "specialized", "role": "room", "specialty": SPECIALTY_ANALISES, "hospital": hospital_id}

    reg[jid(f"{p}bloco_operatorio1")] = {"name": f"[H{hospital_id}] Bloco Operatório A", "wing": "surgical",   "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}bloco_operatorio2")] = {"name": f"[H{hospital_id}] Bloco Operatório B", "wing": "surgical",   "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}bloco_operatorio3")] = {"name": f"[H{hospital_id}] Bloco Operatório C", "wing": "surgical",   "role": "room", "hospital": hospital_id}

    reg[jid(f"{p}sala_triagem1")] = {"name": f"[H{hospital_id}] Triagem 1", "wing": "triage",    "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}sala_triagem2")] = {"name": f"[H{hospital_id}] Triagem 2", "wing": "triage",    "role": "room", "hospital": hospital_id}

    reg[jid(f"{p}internamento1")] = {"name": f"[H{hospital_id}] Internamento 1", "wing": "inpatient", "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}internamento2")] = {"name": f"[H{hospital_id}] Internamento 2", "wing": "inpatient", "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}internamento3")] = {"name": f"[H{hospital_id}] Internamento 3", "wing": "inpatient", "role": "room", "hospital": hospital_id}
    reg[jid(f"{p}internamento4")] = {"name": f"[H{hospital_id}] Internamento 4", "wing": "inpatient", "role": "room", "hospital": hospital_id}

    reg[jid(f"{p}enfermeiro1")] = {"name": f"[H{hospital_id}] Enf. Internamento 1", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "morning"}
    reg[jid(f"{p}enfermeiro2")] = {"name": f"[H{hospital_id}] Enf. Internamento 2", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "morning"}
    reg[jid(f"{p}enfermeiro3")] = {"name": f"[H{hospital_id}] Enf. Internamento 3", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "afternoon"}
    reg[jid(f"{p}enfermeiro4")] = {"name": f"[H{hospital_id}] Enf. Internamento 4", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "afternoon"}
    reg[jid(f"{p}enfermeiro5")] = {"name": f"[H{hospital_id}] Enf. Internamento 5", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "night"}
    reg[jid(f"{p}enfermeiro6")] = {"name": f"[H{hospital_id}] Enf. Internamento 6", "role": "nurse", "hospital": hospital_id, "on_call": True, "shift": "night"}

    reg[jid(f"{p}coord_triagem")] =     {"name": f"[H{hospital_id}] Coordenador de Triagem",     "role": "infra", "hospital": hospital_id}
    reg[jid(f"{p}coord_internamento")] ={"name": f"[H{hospital_id}] Coordenador de Internamento", "role": "infra", "hospital": hospital_id}
    reg[jid(f"{p}supervisor")] =        {"name": f"[H{hospital_id}] Supervisor de Ala",           "role": "infra", "hospital": hospital_id}
    
    return reg"""

content = re.sub(r'def _build_registry_for_hospital\(.*?\n    return \{.*?\n    \}', registry_code, content, flags=re.DOTALL)

with open("src/config.py", "w") as f:
    f.write(content)
