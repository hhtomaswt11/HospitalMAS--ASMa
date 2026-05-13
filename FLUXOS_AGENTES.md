# Mapa de Fluxos de Interação

Este documento descreve os fluxos principais da simulação hospitalar multiagente. A lógica atual separa rigidamente consultas de rotina e consultas de urgência, mantendo prioridade/preempção apenas nos fluxos de exames e cirurgias.

## 1. Fluxo de consultas de rotina

1. O `AgenteDoente` normal envia `request/patient_request` para o `CoordenadorConsultas` do hospital escolhido.
2. O coordenador coloca o pedido na fila de rotina, agrupada por especialidade.
3. O coordenador consulta a agenda centralizada de rotina e considera apenas:
   - médicos de rotina (`consult_mode = routine`);
   - salas de rotina (`category = routine`).
4. Para cada par médico+sala compatível, o coordenador procura o primeiro slot futuro livre que respeite simultaneamente:
   - turno real do médico;
   - horário administrativo das consultas de rotina;
   - disponibilidade futura do médico;
   - disponibilidade futura da sala;
   - ausência de sobreposição.
5. O coordenador escolhe o par com consulta mais cedo e, em empate, distribui a carga por médicos/salas com menos marcações ativas.
6. A reserva fica inicialmente em estado `reservada` na agenda central.
7. O coordenador envia `accept-proposal/type=consultation_schedule` ao médico e à sala apenas para confirmar a reserva escolhida.
8. Médico e sala registam a reserva localmente e respondem com `inform/type=reservation_confirmed`.
9. Só depois das duas confirmações o coordenador muda o estado para `agendada` e envia ao doente `inform/type=consultation_scheduled` com médico, sala, especialidade, hora marcada e hora prevista de fim.
10. No horário marcado, médico e sala iniciam a consulta. A consulta clínica dura 15 minutos simulados, mas os slots são espaçados de 20 minutos para dar folga operacional entre marcações.

Notas importantes:

- Este fluxo já não usa Contract Net clássico para escolher recursos por disponibilidade “agora”; usa agenda de slots futuros.
- Urgências não interrompem consultas de rotina.
- Médicos de urgência não fazem rotina.
- Salas de urgência não recebem rotina.
- O mesmo médico/sala pode ter várias marcações futuras, porque a agenda usa slots e não uma reserva única bloqueante.
- Se médico ou sala não confirmarem a reserva dentro do timeout, a reserva tentativa é cancelada e o pedido permanece pendente para nova tentativa.

## 2. Fluxo de urgência com triagem

1. O `AgenteDoente` urgente envia pedido para o coordenador de triagem local.
2. O coordenador de triagem usa Contract Net com médicos/salas de triagem.
3. O agente de triagem classifica a gravidade e envia `request/triaged_patient` para `CoordenadorUrgencias`.
4. O coordenador de urgências insere o doente numa fila ordenada por prioridade clínica/gravity/severity.
5. O coordenador inicia Contract Net apenas com:
   - médicos de urgência (`consult_mode = emergency`);
   - salas de urgência (`category = emergency`).
6. O doente urgente não recebe horário fixo: é atendido assim que houver recurso adequado, respeitando a prioridade da fila.

Notas importantes:

- A urgência não usa médicos nem salas de rotina.
- A urgência não cancela nem preempta consultas de rotina.
- Pode existir chamada extraordinária de médicos de urgência fora do turno se a configuração o permitir.

## 3. Exames/MCDT

1. Após uma consulta ou urgência, o médico pode pedir exame ao `CoordenadorExames`.
2. O coordenador seleciona recursos compatíveis por especialidade: médico de exame e sala/equipamento especializado.
3. O fluxo mantém lógica de prioridade para casos urgentes.
4. Se existir preempção, ela só deve afetar reservas/execuções de exames, nunca consultas de rotina.
5. O médico solicitante aguarda `exam_result` real antes de continuar a decisão clínica.

## 4. Cirurgias

1. Após exame ou decisão clínica, o médico pode pedir cirurgia ao `CoordenadorCirurgias`.
2. O coordenador negocia com cirurgiões e blocos operatórios.
3. Casos urgentes podem manter prioridade/preempção.
4. A preempção cirúrgica fica limitada ao fluxo de cirurgia e não deve cancelar consultas de rotina.
5. O médico solicitante aguarda `surgery_result` real.

## 5. Internamento

1. O médico pede internamento ao `CoordenadorInternamento` quando aplicável.
2. O coordenador usa Contract Net com quartos/camas e equipa de enfermagem.
3. Se o internamento falhar por indisponibilidade persistente, é enviada resposta explícita para evitar doentes bloqueados.
4. No fim, o recurso é libertado e o doente recebe alta/observação conforme o fluxo clínico.

## 6. Supervisor e dashboard

O supervisor recebe e agrega:

- `resource_status` dos recursos;
- `waitlist_update` dos coordenadores;
- consultas de rotina pendentes e consultas já agendadas/em curso;
- logs operacionais;
- estado de filas, recursos ocupados e recursos livres.

Nas respostas `load_query` enviadas à triagem central, o supervisor calcula a carga de rotina como:

```text
carga = doentes pendentes em fila + consultas futuras/agendadas/em curso
```

Isto é feito por especialidade e no total, evitando que um hospital pareça livre apenas porque já transformou a fila numa agenda futura muito preenchida.

O dashboard mostra a separação entre consultórios de rotina e urgência, estado dos recursos, tipo/função dos médicos e carga semanal trabalhada em relação às 40 horas.

## 7. Afluência variável

O gerador de doentes usa perfis horários configuráveis em `src/config.py`:

- maior afluência de manhã, sobretudo perto das 08h-10h;
- menor afluência a meio do dia;
- afluência normal/alta à tarde;
- períodos mais calmos ao fim do dia/noite.

Não foi implementado um sistema de centros de saúde, porque ficou fora do âmbito útil indicado pelo professor.
