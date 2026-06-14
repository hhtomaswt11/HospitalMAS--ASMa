# Practical Work — Multi-Agent Hospital Simulation

This folder contains the practical implementation of **HospitalMAS**, a multi-agent hospital simulation developed for the **Agents and Multi-Agent Systems** course at the **University of Minho**.

**Final Grade:** 17/20

## Overview

The practical work implements a distributed hospital simulation based on autonomous agents.

The system simulates two hospitals, a unified central triage, routine consultations, emergency care, exams, surgeries, hospitalization, human resources, physical resources, waiting queues and a real-time dashboard.

The goal is to demonstrate how **Multi-Agent Systems** can be used to model complex healthcare workflows where multiple autonomous entities interact, negotiate and coordinate decisions.

## Main Objective

The main objective of the prototype is to simulate hospital coordination in a decentralized way.

The system allows agents to:

* represent patients, doctors, nurses, rooms and equipment;
* coordinate routine and emergency patient flows;
* allocate hospital resources;
* negotiate task execution;
* manage future appointment slots;
* prioritize urgent cases;
* monitor hospital load;
* expose the system state through a dashboard.

## System Architecture

The practical implementation is organized as follows:

```txt
TrabalhoPratico/
├── main_sim.py
├── dashboard.py
├── requirements.txt
├── .env.example
├── FLUXOS_AGENTES.md
├── src/
│   ├── config.py
│   ├── scheduling.py
│   ├── metrics.py
│   ├── patch.py
│   └── agents/
│       ├── agente_triagem_geral.py
│       ├── supervisor.py
│       ├── Coordinators/
│       └── Resources/
├── static/
│   └── index.html
├── data/
├── diagrams/
└── tests/
```

## Main Components

### Simulation Entry Point

`main_sim.py` starts the full simulation, including:

* both hospitals;
* the central triage;
* hospital supervisors;
* coordinator agents;
* resource agents;
* patient generators.

### Dashboard Server

`dashboard.py` starts a FastAPI server that serves the web dashboard and exposes the current simulation state.

The dashboard reads the generated state from:

```txt
data/dashboard.json
```

### Configuration

`src/config.py` contains the main simulation configuration, including:

* simulation duration;
* patient arrival rates;
* hospital resources;
* agent registry;
* working shifts;
* routine consultation hours;
* emergency settings;
* retry limits;
* scheduling parameters.

### Scheduling

`src/scheduling.py` contains helper functions for:

* future appointment slots;
* doctor shifts;
* room availability;
* time validation;
* overlap prevention.

### Metrics

`src/metrics.py` contains utilities for collecting and storing simulation metrics.

## Agent Types

The simulation includes several agent categories.

### Patient Agents

Patient agents represent patients entering the hospital system. They can be normal or urgent patients and interact with the appropriate coordinators.

### Central Triage Agent

The central triage agent evaluates hospital load and forwards patients to the hospital with the most suitable capacity.

For routine patients, the load calculation considers not only the current waiting queue but also future scheduled consultations.

### Coordinator Agents

Coordinator agents manage specific hospital workflows:

* consultation coordinator;
* emergency coordinator;
* triage coordinator;
* exam coordinator;
* surgery coordinator;
* hospitalization coordinator.

Each coordinator is responsible for receiving requests, managing queues and allocating the necessary resources.

### Resource Agents

Resource agents represent hospital resources such as:

* doctors;
* triage doctors;
* nurses;
* consultation rooms;
* emergency rooms;
* exam rooms;
* medical equipment;
* operating rooms;
* hospitalization rooms and beds.

### Supervisor Agents

Supervisor agents monitor each hospital and provide state information to the dashboard and central triage.

They aggregate information about:

* waiting queues;
* resource availability;
* current load;
* future scheduled consultations;
* recent events;
* hospital state.

## Coordination Strategy

The system uses a hybrid coordination strategy.

### Routine Consultations

Routine consultations use a centralized future-slot scheduling mechanism.

The consultation coordinator searches for the first valid future slot that satisfies:

* doctor availability;
* doctor working shift;
* routine consultation hours;
* room availability;
* medical specialty;
* no schedule overlap.

A consultation is only confirmed after both the doctor and the room explicitly confirm the reservation.

### Emergency Care, Exams, Surgeries and Hospitalization

Emergency care, exams, surgeries, triage and hospitalization follow a negotiation mechanism inspired by the **FIPA Contract Net protocol**.

The general process is:

```txt
Coordinator sends Call for Proposal
  ↓
Eligible resources reply with proposals
  ↓
Coordinator evaluates proposals
  ↓
Best resource is selected
  ↓
Task is executed
  ↓
Resource is released
```

This allows the system to allocate resources dynamically according to availability, suitability and current load.

## Main Workflows

### Routine Consultations

Normal patients are assigned to routine consultations according to medical specialty, doctor shifts and room availability.

Routine consultations are scheduled within the administrative time window:

```txt
08:00–20:00 simulated time
```

### Emergency Flow

Urgent patients are sent to local triage and then to emergency care. They are prioritized according to clinical severity and are handled separately from routine consultations.

Emergency patients do not cancel or interrupt routine appointments.

### Exams

Doctors may request medical exams. The exam coordinator selects compatible medical staff and equipment using a Contract Net-inspired negotiation process.

### Surgeries

If needed, a patient may be referred to surgery. The surgery coordinator allocates surgeons and operating rooms, considering priority and availability.

### Hospitalization

When hospitalization is required, the hospitalization coordinator allocates a room or bed and the necessary nursing support.

After hospitalization ends, resources are released and the patient receives discharge.

## Dashboard

The project includes a web dashboard for observing the simulation in real time.

The dashboard displays:

* hospital resources;
* resource status;
* routine queues;
* emergency queues;
* recent logs;
* hospital load;
* doctors and rooms;
* waiting patients;
* simulation events.

## Technologies Used

The project uses:

* Python;
* SPADE;
* XMPP;
* FastAPI;
* Uvicorn;
* HTML;
* CSS;
* JavaScript;
* asynchronous message passing;
* FIPA-inspired coordination.

## Requirements

The project requires:

* Python 3.10 or higher;
* an XMPP server compatible with SPADE, such as Prosody;
* Python dependencies listed in `requirements.txt`.

Install dependencies with:

```bash
pip install -r requirements.txt
```

Or using a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

On Windows:

```bash
venv\Scripts\activate
```

## Environment Configuration

The project includes an example environment file:

```txt
.env.example
```

Default configuration:

```env
XMPP_SERVER=127.0.0.1
XMPP_PASSWORD=your_password_here
SIMULATION_DURATION=180
SIM_SHUTDOWN_DRAIN_SECONDS=3
PATIENT_SHUTDOWN_GRACE_SECONDS=2
AUTO_START_DASHBOARD=0
CONTRACT_NET_SEND_REJECT_PROPOSALS=0
```

The most important variables are:

| Variable                             | Description                                  |
| ------------------------------------ | -------------------------------------------- |
| `XMPP_SERVER`                        | Address of the XMPP server                   |
| `XMPP_PASSWORD`                      | Password used by the agents                  |
| `SIMULATION_DURATION`                | Simulation duration in real seconds          |
| `AUTO_START_DASHBOARD`               | Enables automatic dashboard startup          |
| `CONTRACT_NET_SEND_REJECT_PROPOSALS` | Enables stricter Contract Net debug messages |

## Running the Simulation

Start the simulation with:

```bash
python3 main_sim.py
```

To run the simulation for a custom duration:

```bash
SIMULATION_DURATION=300 python3 main_sim.py
```

For a longer execution:

```bash
SIMULATION_DURATION=1680 python3 main_sim.py
```

## Running the Dashboard

Start the dashboard with:

```bash
python3 dashboard.py
```

Then open:

```txt
http://localhost:8000
```

The dashboard can be executed in parallel with the simulation:

```bash
# Terminal 1
python3 dashboard.py

# Terminal 2
python3 main_sim.py
```

## Recommended Demo Command

For a short and stable demonstration:

```bash
python3 dashboard.py
```

In another terminal:

```bash
SIMULATION_DURATION=180 python3 main_sim.py
```

## Dashboard API

The dashboard server exposes:

| Endpoint     | Description                             |
| ------------ | --------------------------------------- |
| `/`          | Web dashboard                           |
| `/api/state` | Current simulation state in JSON format |

## Diagrams

The `diagrams/` folder contains supporting documentation for the system design, including:

* activity diagrams;
* class diagrams;
* collaboration diagrams.

## Tests

The `tests/` folder contains tests for validating important simulation behaviours and agent interactions.

## Limitations

The current prototype has some limitations:

* it is a simulation, not a real hospital management system;
* clinical decisions are simplified;
* the system depends on an XMPP server;
* real-world deployment would require integration with hospital information systems;
* medical validation was not performed;
* legal, ethical and regulatory requirements would need deeper treatment before any real use.

## Future Improvements

Possible future improvements include:

* adding more hospitals;
* expanding medical specialties;
* improving emergency prioritization;
* adding richer patient profiles;
* integrating digital twin concepts;
* adding real-time analytics;
* improving the dashboard;
* adding persistence with a database;
* integrating LLM-based clinical reasoning agents;
* supporting interoperability standards such as HL7/FHIR;
* improving simulation metrics and reporting.

## Academic Context

Developed at:

**University of Minho**
**Master's Degree in Artificial Intelligence**
**Agents and Multi-Agent Systems**
**Academic Year 2025/2026**

## Final Grade

**17/20**

## Disclaimer

This project is an academic simulation and is not intended for real clinical use.

## License

This project is intended for academic and educational purposes.
