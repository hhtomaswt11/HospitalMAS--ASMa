# HospitalMAS — Multi-Agent Hospital Simulation

HospitalMAS is an academic project developed for the **Agents and Multi-Agent Systems** course, as part of the **Master's Degree in Artificial Intelligence** at the **University of Minho**.

The project explores the use of **Multi-Agent Systems (MAS)** to model, coordinate and simulate hospital workflows in a distributed and autonomous way.

The repository contains both stages of the work:

* **Research Work**: state-of-the-art analysis of Multi-Agent Systems in healthcare;
* **Practical Work**: implementation of a multi-hospital simulation using autonomous agents.

## Final Grades

| Component      | Description                       | Grade |
| -------------- | --------------------------------- | ----: |
| Research Work  | Multi-Agent Systems in Healthcare | 17/20 |
| Practical Work | Multi-Agent Hospital Simulation   | 17/20 |

## Project Motivation

Modern healthcare systems are complex, dynamic and resource-constrained environments. Hospitals must coordinate doctors, nurses, patients, consultation rooms, emergency services, exams, surgeries and inpatient beds, often under time-critical conditions.

Traditional centralized systems may struggle to adapt to unexpected events, such as sudden emergency demand, resource unavailability or changes in clinical priority.

This project investigates how **Multi-Agent Systems** can support more flexible, decentralized and adaptive hospital management.

## General Objective

The main objective of HospitalMAS is to design and implement a simulation where hospital entities are represented as autonomous agents capable of:

* communicating with each other;
* negotiating resource allocation;
* managing patient flows;
* prioritizing urgent cases;
* scheduling routine consultations;
* coordinating exams, surgeries and hospitalization;
* monitoring hospital load through supervisors and a dashboard.

## Research and Practical Development

The project was developed in two stages.

### Research Work

The research phase presents a state-of-the-art review of Multi-Agent Systems applied to healthcare.

It studies several application domains, including:

* clinical triage;
* hospital resource management;
* patient monitoring;
* medical IoT;
* clinical decision support;
* digital twins;
* LLM-based healthcare agents;
* agent communication protocols.

The research also proposes a conceptual architecture for a hospital MAS, which later served as the basis for the practical implementation.

### Practical Work

The practical phase implements a working simulation of a distributed hospital environment.

The implemented system includes:

* two hospitals;
* a unified central triage;
* routine consultations;
* emergency consultations;
* exams and medical tests;
* surgeries;
* hospitalization;
* medical staff agents;
* room and equipment agents;
* coordinator agents;
* supervisor agents;
* real-time dashboard.

## Main Technologies

The project uses:

* Python;
* SPADE;
* XMPP;
* FIPA-inspired Contract Net protocol;
* FastAPI;
* Uvicorn;
* HTML/CSS/JavaScript dashboard;
* asynchronous agent communication.

## Repository Structure

```txt
.
├── TrabalhoInvestigacao/
│   ├── README.md
│   ├── TrabalhoInvestigacaoG5.pdf
│   ├── ApresentacaoG5.pdf
│   └── MIA ASMa_2526_Enunciado_TI.pdf
│
├── TrabalhoPratico/
│   ├── README.md
│   ├── main_sim.py
│   ├── dashboard.py
│   ├── requirements.txt
│   ├── FLUXOS_AGENTES.md
│   ├── src/
│   ├── static/
│   ├── data/
│   ├── diagrams/
│   └── tests/
│
└── README.md
```

## System Overview

The practical system follows a distributed multi-agent architecture.

```txt
Patients
  ↓
Central Triage Agent
  ↓
Hospital Supervisor Agents
  ↓
Coordinator Agents
  ↓
Resource Agents
  ↓
Medical Acts and Hospital Flow
```

Each hospital contains specialized coordinator agents responsible for different workflows. These coordinators interact with resource agents to allocate doctors, nurses, rooms, equipment, operating rooms and hospitalization beds.

## Main Agent Types

The system includes several types of agents:

* **Patient Agents**: represent patients entering the hospital system;
* **Central Triage Agent**: selects the hospital with the lowest relevant load;
* **Consultation Coordinator Agents**: manage routine consultation scheduling;
* **Emergency Coordinator Agents**: manage urgent patients and priority-based care;
* **Exam Coordinator Agents**: coordinate medical exams and diagnostic tests;
* **Surgery Coordinator Agents**: allocate surgeons and operating rooms;
* **Hospitalization Coordinator Agents**: manage rooms, beds and nursing resources;
* **Doctor Agents**: represent medical professionals;
* **Nurse Agents**: represent nursing staff;
* **Room and Equipment Agents**: represent physical hospital resources;
* **Supervisor Agents**: monitor hospital state and provide data to the dashboard.

## Coordination Strategy

The system uses a hybrid coordination approach.

Routine consultations are managed through a centralized future-slot scheduling mechanism, ensuring realistic appointment planning according to doctor shifts, room availability and administrative working hours.

Emergency care, exams, surgeries, triage and hospitalization use a negotiation strategy inspired by the **FIPA Contract Net protocol**, where coordinators request proposals from available resources and select the best candidate according to availability, suitability and load.

## Dashboard

The project includes a web dashboard that allows the user to observe the current state of the simulation.

The dashboard displays:

* hospital resources;
* active queues;
* routine and emergency patients;
* recent events;
* hospital load;
* resource occupation;
* system logs.

## Academic Context

Developed at:

**University of Minho**
**Master's Degree in Artificial Intelligence**
**Agents and Multi-Agent Systems**
**Academic Year 2025/2026**

## Disclaimer

This project is an academic simulation and is not intended for real clinical use. It does not replace certified hospital management systems, medical decision-support tools or healthcare professionals.

## License

This repository is intended for academic and educational purposes.
