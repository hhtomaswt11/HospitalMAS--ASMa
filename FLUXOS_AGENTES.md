# Mapa de Fluxos de Interação

### Fluxo de Rotina (consulta normal)

1. Doente envia pedido:
   - `AgenteDoente` -> `COORD_CONS`
   - `performative=request`, `type=patient_request`
   - Referência: `src/agents/Resources/agente_doente.py:46`

2. Coordenador de consultas processa fila e inicia Contract-Net:
   - Publica fila (`waitlist_update`) para supervisor.
   - Envia CFP para médicos compatíveis e salas.
   - Referências: `src/agents/Coordinators/coordenador_consultas.py:86`, `src/agents/Coordinators/coordenador_consultas.py:232`

3. Recursos respondem:
   - `AgenteMedico`/`AgenteSala` respondem `propose` ou `reject-proposal`.
   - Referências: `src/agents/Resources/agente_medico.py:266`, `src/agents/Resources/agente_sala.py:31`

4. Adjudicação:
   - Coordenador envia `accept-proposal` para médico e sala.
   - Referência: `src/agents/Coordinators/coordenador_consultas.py:291`

5. Execução clínica:
   - Médico executa avaliação, pode dar alta, pedir exame, cirurgia ou internamento (dependendo do caso/probabilidades).
   - Referência: `src/agents/Resources/agente_medico.py:291`

### Fluxo de Urgência com Triagem

1. Doente urgente envia pedido:
   - `AgenteDoente` -> `COORD_TRI`
   - `request/patient_request`
   - Referência: `src/agents/Resources/agente_doente.py:40`

2. Coordenador de triagem:
   - Mantém fila de triagem.
   - Contract-Net com médicos de triagem + salas de triagem.
   - Referências: `src/agents/Coordinators/coordenador_triagem.py:28`, `src/agents/Coordinators/coordenador_triagem.py:67`

3. Agente de triagem classifica:
   - Envia `request/triaged_patient` para `COORD_URG`.
   - Envia `inform/emergency_alert` para `SUPERVISOR`.
   - Referências: `src/agents/Resources/agente_triagem.py:43`, `src/agents/Resources/agente_triagem.py:56`

4. Coordenador de urgências:
   - Atualiza fila de urgências.
   - Fecha gate da rotina (`routine_gate: hold=true`) para `COORD_CONS`.
   - Aguarda `resources_freed` do supervisor para despachar próximo urgente.
   - Referências: `src/agents/Coordinators/coordenador_urgencias.py:47`, `src/agents/Coordinators/coordenador_urgencias.py:57`, `src/agents/Coordinators/coordenador_urgencias.py:96`

### Fluxo de Preempção

1. Supervisor recebe alerta:
   - `inform/emergency_alert`
   - Referência: `src/agents/supervisor.py:121`

2. Supervisor ordena preempção:
   - `request/preemption_order` para `COORD_CONS`
   - Referência: `src/agents/supervisor.py:139`

3. Coordenador de consultas cancela alocação de rotina:
   - Envia `cancel/preemption_cancel` para médico e sala.
   - Reencola doente preemptado na fila de rotina.
   - Referências: `src/agents/Coordinators/coordenador_consultas.py:358`, `src/agents/Coordinators/coordenador_consultas.py:369`, `src/agents/Coordinators/coordenador_consultas.py:393`

4. Recursos libertam e respondem:
   - Médico/Sala tratam `cancel` e enviam `inform/cancel_confirmed`.
   - Referências: `src/agents/Resources/agente_medico.py:342`, `src/agents/Resources/agente_sala.py:75`

5. Coordenador de consultas notifica supervisor:
   - `inform/preemption_done`
   - Referência: `src/agents/Coordinators/coordenador_consultas.py:400`

6. Supervisor libera urgências:
   - Envia `inform/resources_freed` para `COORD_URG`
   - Referência: `src/agents/supervisor.py:157`

### 2.4 Fluxo de Exames

1. Médico solicita exame:
   - `request/exam_request` para `COORD_EXAM`
   - Referência: `src/agents/Resources/agente_medico.py:85`

2. Coordenador de exames:
   - Seleciona equipamentos e médicos de exame por especialidade.
   - Contract-Net e adjudicação.
   - Referências: `src/agents/Coordinators/coordenador_exames.py:15`, `src/agents/Coordinators/coordenador_exames.py:53`

3. Confirmação de alocação ao solicitante:
   - `inform/allocation_confirmed` (`procedure=exam`)
   - Referência: `src/agents/Coordinators/coordenador_exames.py:157`

### Fluxo de Cirurgia

1. Médico solicita cirurgia:
   - `request/surgery_request` para `COORD_CIR`
   - Referência: `src/agents/Resources/agente_medico.py:115`

2. Coordenador de cirurgias:
   - Contract-Net com blocos + cirurgiões.
   - Referência: `src/agents/Coordinators/coordenador_cirurgias.py:35`

3. Confirmação ao solicitante:
   - `inform/allocation_confirmed` (`procedure=surgery`)
   - Referência: `src/agents/Coordinators/coordenador_cirurgias.py:132`

### Fluxo de Internamento

1. Pedido de internamento:
   - `request/internment_request` para `COORD_INT`
   - Referências: `src/agents/Resources/agente_medico.py:170`, `src/agents/Resources/agente_medico.py:226`

2. Coordenador de internamento:
   - Contract-Net com quartos de internamento.
   - Referência: `src/agents/Coordinators/coordenador_internamento.py:68`

3. Conclusão:
   - Médico envia `inform/internment_finished` para coordenador.
   - Referência: `src/agents/Resources/agente_medico.py:256`

---

## Observabilidade e Estado Global

Supervisor centraliza:
- Estado de recursos via `resource_status`.
- Filas via `waitlist_update`.
- Alertas de urgência/preempção.

Referências:
- `src/agents/supervisor.py:71`
- `src/agents/supervisor.py:107`
- `src/agents/supervisor.py:121`
- `src/agents/supervisor.py:149`

Persistência:
- `data/dashboard.json`
- `data/log_supervisor.txt`


