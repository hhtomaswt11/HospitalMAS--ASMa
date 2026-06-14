# Research Work — Multi-Agent Systems in Healthcare

This folder contains the research component of the HospitalMAS project, developed for the **Agents and Multi-Agent Systems** course at the **University of Minho**.

**Final Grade:** 17/20

## Overview

The research work presents a state-of-the-art analysis of **Multi-Agent Systems (MAS)** applied to healthcare environments.

The main goal is to understand how autonomous, distributed and cooperative agents can support complex healthcare processes such as triage, resource allocation, patient monitoring and clinical decision support.

## Research Motivation

Healthcare systems are increasingly complex and pressured by demographic, organizational and technological challenges.

Hospitals involve multiple interacting entities, including:

* patients;
* doctors;
* nurses;
* administrative staff;
* rooms;
* diagnostic equipment;
* operating rooms;
* inpatient beds;
* information systems.

These entities must be coordinated in real time, often under uncertainty and urgency. Multi-Agent Systems provide a suitable paradigm because they allow complex systems to be decomposed into autonomous agents that communicate, negotiate and coordinate their actions.

## Main Research Question

The research explores the following question:

How can Multi-Agent Systems improve coordination, adaptability and resource management in modern healthcare environments?

## Topics Studied

The work analyses several domains where MAS have been applied in healthcare:

* clinical triage;
* emergency department management;
* hospital scheduling;
* resource allocation;
* patient monitoring;
* medical IoT and wearables;
* clinical decision support;
* digital twins for hospitals;
* LLM-based healthcare agents;
* knowledge graphs for diagnosis;
* agent communication protocols.

## State of the Art

The research reviews recent work published mainly between 2019 and 2024.

The analysed systems include different architectural approaches:

### BDI Architectures

BDI agents are used when transparent reasoning and explainability are important. They model beliefs, desires and intentions, making them suitable for systems where decisions must be justified.

### Hybrid Architectures

Hybrid approaches combine agent-based simulation with optimization methods, such as deep reinforcement learning, to improve hospital resource allocation and scheduling.

### LLM-Based Multi-Agent Systems

Recent systems use Large Language Models as reasoning components inside specialized agents. These agents can support clinical triage, diagnosis and treatment planning by processing medical context in natural language.

### Digital Twin Architectures

Hospital digital twins use agent-based simulation to reproduce real hospital workflows and test resource allocation policies without affecting real patients.

## Communication and Coordination

The research also studies how agents communicate and coordinate.

Important mechanisms include:

* FIPA-ACL;
* FIPA Contract Net;
* asynchronous communication;
* negotiation protocols;
* shared memory;
* Retrieval-Augmented Generation;
* knowledge-graph-mediated communication.

The **FIPA Contract Net protocol** is especially relevant for resource allocation, where one agent announces a task and other agents submit proposals.

## Main Findings

The research shows that Multi-Agent Systems can provide several benefits in healthcare:

* decentralized coordination;
* adaptability to unexpected events;
* better resource allocation;
* fault tolerance;
* scalability;
* real-time responsiveness;
* modular integration of new agents and services.

However, the literature also presents important limitations:

* lack of prospective clinical validation;
* dependence on simulation-based evaluation;
* difficulty comparing results across studies;
* limited benchmarks;
* interoperability challenges;
* regulatory and ethical concerns;
* need for transparency and human supervision.

## Proposed Implementation

Based on the state-of-the-art review, the research proposes a conceptual architecture for a hospital Multi-Agent System.

The proposed system is organized around three main layers:

```txt
Supervisor Layer
  ↓
Coordinator Agent Layer
  ↓
Resource Agent Layer
```

The system includes:

* patient agents;
* doctor agents;
* room and equipment agents;
* consultation coordinator agents;
* exam coordinator agents;
* surgery coordinator agents;
* hospitalization coordinator agents;
* supervisor agent.

This architecture served as the conceptual basis for the practical implementation developed in the second stage of the project.

## Connection to the Practical Work

The research work directly informed the practical prototype.

Several concepts studied in the research phase were later implemented or adapted in the practical work, including:

* autonomous agents;
* distributed hospital coordination;
* supervisor agents;
* resource agents;
* coordinator agents;
* Contract Net-inspired negotiation;
* patient flow simulation;
* hospital resource allocation.

## Files

This folder contains:

```txt
TrabalhoInvestigacao/
├── README.md
├── TrabalhoInvestigacaoG5.pdf
├── ApresentacaoG5.pdf
└── MIA ASMa_2526_Enunciado_TI.pdf
```

## Academic Context

Developed at:

**University of Minho**
**Master's Degree in Artificial Intelligence**
**Agents and Multi-Agent Systems**
**Academic Year 2025/2026**

## Final Grade

**17/20**

## License

This work is intended for academic and educational purposes.
