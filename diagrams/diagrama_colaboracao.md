# Diagrama de Colaboração — Comunicação entre agentes (simplificado)

Este diagrama mostra as principais trocas de mensagens (cfp, request, propose, accept-proposal, inform) entre agentes do sistema.

```mermaid
graph LR
  AD["AgenteDoente"]
  AG["AgenteTriagemGeral"]
  SV1["Supervisor H1"]
  SV2["Supervisor H2"]
  CC["CoordenadorConsultas H1"]
  MED["AgenteMedico (H1)"]
  SALA["AgenteSala (H1)"]
  CT["CoordenadorTriagem H1"]
  CG["CoordenadorUrgencias H1"]
  CE["CoordenadorExames H1"]
  CI["CoordenadorInternamento H1"]
  CCirurgias["CoordenadorCirurgias H1"]
  MT["AgenteTriagem (H1)"]
  ENF["AgenteEnfermeiro (H1)"]

  %% Triagem Central — Load Balancing
  AD -->|1: request / patient_request| AG
  AG -->|2a: cfp / load_query| SV1
  AG -->|2b: cfp / load_query| SV2
  SV1 -->|3a: propose / load_response| AG
  SV2 -->|3b: propose / load_response| AG
  AG -->|4a: request / patient_request| CC
  AG -->|4b: request / patient_request| CT
  AG -->|4c: inform / routing_update| SV1

  %% Consultas de Rotina — Contract-Net c/ agenda centralizada
  CC -->|5a: accept-proposal / consultation_schedule| MED
  CC -->|5b: accept-proposal / consultation_schedule| SALA
  MED -->|6a: inform / reservation_confirmed| CC
  SALA -->|6b: inform / reservation_confirmed| CC
  CC -->|7: inform / consultation_scheduled| AD
  CC -->|8: inform / waitlist_update| SV1

  %% Urgência — Triagem Local (Contract-Net)
  AD -->|9: request / patient_request| CT
  CT -->|10a: cfp / triage_cfp| MT
  CT -->|10b: cfp / triage_cfp| SALA
  MT -->|11a: propose / triage_propose| CT
  SALA -->|11b: propose / triage_propose| CT
  CT -->|12a: accept-proposal / triage_accept| MT
  CT -->|12b: accept-proposal / triage_accept| SALA
  MT -->|13: request / triaged_patient| CG

  %% Urgência — Alocação de Consulta de Emergência (Contract-Net)
  CG -->|14a: cfp / emergency_cfp| MED
  CG -->|14b: cfp / emergency_cfp| SALA
  MED -->|15a: propose / emergency_propose| CG
  SALA -->|15b: propose / emergency_propose| CG
  CG -->|16a: accept-proposal / emergency_accept| MED
  CG -->|16b: accept-proposal / emergency_accept| SALA

  %% Exames (Contract-Net)
  MED -->|17: request / exam_request| CE
  CE -->|18a: cfp / exam_cfp| MED
  CE -->|18b: cfp / exam_cfp| SALA
  MED -->|19a: propose / exam_propose| CE
  SALA -->|19b: propose / exam_propose| CE
  CE -->|20a: accept-proposal / exam_accept| MED
  CE -->|20b: accept-proposal / exam_accept| SALA

  %% Cirurgias (Contract-Net)
  MED -->|21: request / surgery_request| CCirurgias
  CCirurgias -->|22a: cfp / surgery_cfp| SALA
  CCirurgias -->|22b: cfp / surgery_cfp| MED
  SALA -->|23a: propose / surgery_propose| CCirurgias
  MED -->|23b: propose / surgery_propose| CCirurgias
  CCirurgias -->|24a: accept-proposal / surgery_accept| SALA
  CCirurgias -->|24b: accept-proposal / surgery_accept| MED

  %% Internamento (Contract-Net)
  MED -->|25: request / internment_request| CI
  CI -->|26a: cfp / internment_cfp| SALA
  CI -->|26b: cfp / internment_cfp| ENF
  SALA -->|27a: propose / internment_propose| CI
  ENF -->|27b: propose / internment_propose| CI
  CI -->|28a: accept-proposal / internment_accept| SALA
  CI -->|28b: accept-proposal / internment_accept| ENF
  ENF -->|29: inform / internment_finished| CI

  %% Notificações push ao doente (após confirmação de alocação)
  CE -.->|30a: inform / allocation_confirmed| AD
  CCirurgias -.->|30b: inform / allocation_confirmed| AD
  CI -.->|30c: inform / allocation_confirmed| AD
```

