# Sistema Multiagente — Simulação Hospitalar Multi-Hospital

> Python · SPADE/XMPP · FIPA Contract Net · FastAPI Dashboard

Este projeto simula um sistema hospitalar distribuído baseado em agentes autónomos. A simulação inclui dois hospitais, uma triagem central unificada, consultas de rotina, urgências, exames/MCDT, cirurgias, internamento, recursos físicos e humanos, filas de espera, alocação por propostas e um dashboard de observação.

## 1. Visão geral

O sistema modela um ambiente hospitalar onde diferentes agentes comunicam por mensagens SPADE/XMPP:

- **AgenteDoente**: representa cada paciente criado durante a simulação.
- **AgenteTriagemGeral**: representa a triagem central, responsável por encaminhar o paciente para o hospital com menor carga.
- **Coordenadores hospitalares**: gerem consultas, urgências, triagem local, exames, cirurgias e internamento.
- **Agentes de recursos**: médicos, médicos de triagem, enfermeiros, salas, equipamentos, blocos operatórios e quartos/camas de internamento.
- **Supervisores**: recolhem estado dos hospitais e alimentam os ficheiros usados pelo dashboard.

A arquitetura segue uma lógica descentralizada: os coordenadores não executam diretamente os atos clínicos. Nos fluxos de urgência, exames, cirurgias, triagem e internamento usam uma lógica próxima do protocolo **FIPA Contract Net**. Nas consultas de rotina, por exigência de realismo da agenda, o coordenador usa uma **agenda centralizada de slots futuros** e só confirma a marcação ao doente depois de receber confirmação explícita do médico e da sala.

## 2. Estrutura atual do projeto

```text
ASMa-25_26/
├── main_sim.py                         # Entry-point principal da simulação
├── dashboard.py                        # Servidor FastAPI para o dashboard
├── requirements.txt                    # Dependências Python
├── README.md                           # Este documento
├── FLUXOS_AGENTES.md                   # Descrição dos fluxos entre agentes
├── src/
│   ├── config.py                       # Configuração geral, JIDs, tempos, probabilidades e registry
│   ├── scheduling.py                   # Helpers de agenda, turnos, slots e validação temporal
│   ├── patch.py                        # Patch de compatibilidade XMPP/SPADE
│   └── agents/
│       ├── agente_triagem_geral.py     # Triagem central multi-hospital
│       ├── supervisor.py               # Supervisores e estado para dashboard
│       ├── Coordinators/
│       │   ├── coordenador_consultas.py
│       │   ├── coordenador_urgencias.py
│       │   ├── coordenador_triagem.py
│       │   ├── coordenador_exames.py
│       │   ├── coordenador_cirurgias.py
│       │   └── coordenador_internamento.py
│       └── Resources/
│           ├── agente_doente.py
│           ├── agente_medico.py
│           ├── agente_enfermeiro.py
│           ├── agente_sala.py
│           ├── agente_triagem.py
│           └── resource_agent.py
├── static/
│   └── index.html                      # Interface web do dashboard
├── data/                               # Estado/logs gerados em execução
└── outputs/                            # Logs de execuções da simulação
```

## 3. Pré-requisitos

É necessário ter:

- Python 3.10 ou superior;
- servidor XMPP compatível com SPADE, por exemplo Prosody;
- dependências Python instaladas a partir de `requirements.txt`.

Instalação das dependências:

```bash
pip install -r requirements.txt
```

Se usares ambiente virtual:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Configuração XMPP

Por defeito, o projeto usa:

```text
XMPP_SERVER=127.0.0.1
XMPP_PASSWORD=password
```

Estes valores são definidos em `src/config.py` através de `os.getenv`, portanto podem ser alterados antes de executar:

```bash
export XMPP_SERVER=127.0.0.1
export XMPP_PASSWORD=password
python3 main_sim.py
```

O ficheiro `.env.example` serve como modelo de configuração local. Nesta versão, o carregamento automático de `.env` está desativado por segurança/compatibilidade local; se quiseres usar `.env` diretamente, ativa `load_dotenv()` em `src/config.py` e garante que o `.env` tem valores corretos.

Para verificar se o servidor XMPP está ativo localmente:

```bash
sudo systemctl status prosody
ss -ltnp | grep 5222
```

## 5. Execução da simulação

O entry-point correto é:

```bash
python3 main_sim.py
```

A simulação arranca os dois hospitais, a triagem central, os supervisores, os coordenadores, os recursos e os geradores de pacientes.

Por defeito, a duração está configurada para uma demonstração curta, mas suficientemente longa para observar triagem, filas, atendimentos e alguns encaminhamentos entre hospitais:

```text
SIMULATION_DURATION=180 segundos
```

Este valor pode ser alterado por variável de ambiente, sem mexer no código.

Para executar durante mais tempo, podes definir a variável antes de correr:

```bash
SIMULATION_DURATION=300 python3 main_sim.py
```

Ou, para simular uma semana completa no modelo temporal atual:

```bash
SIMULATION_DURATION=1680 python3 main_sim.py
```

## 6. Dashboard

O dashboard lê o estado gerado em `data/dashboard.json` e apresenta recursos, filas e eventos recentes.

Para iniciar o dashboard:

```bash
python3 dashboard.py
```

Depois abre no browser:

```text
http://localhost:8000
```

O dashboard pode ser corrido em paralelo com a simulação, em terminais separados:

```bash
# Terminal 1
python3 dashboard.py

# Terminal 2
python3 main_sim.py
```

## 7. Fluxos principais implementados

### 7.1 Consultas de rotina

Pacientes normais entram diretamente no hospital ou passam pela triagem central. Quando chegam ao fluxo de rotina, o `CoordenadorConsultas` coloca o pedido na fila por especialidade e tenta associá-lo rapidamente a uma marcação concreta com:

- médico de rotina;
- sala/consultório de rotina;
- especialidade;
- hora marcada de início;
- hora prevista de fim;
- estado da consulta.

Nesta versão, as consultas de rotina **não dependem da disponibilidade “agora”** do médico/sala nem usam Contract Net clássico para escolher propostas momentâneas. O coordenador consulta uma agenda centralizada, procura o primeiro par médico+sala com slot futuro válido e valida simultaneamente:

- turno real do médico;
- janela administrativa das consultas de rotina;
- disponibilidade futura do médico;
- disponibilidade futura da sala;
- ausência de sobreposição.

A consulta clínica continua a durar 15 minutos simulados (`CONSULTATION_DURATION_NORMAL_SECONDS`), mas os slots são espaçados de 20 minutos (`CONSULTATION_SLOT_MINUTES = 20`). Esta folga reduz atrasos provocados por mensagens assíncronas e libertação de recursos, mantendo o comportamento realista.

Após escolher o slot, o coordenador faz uma reserva tentativa e envia a marcação ao médico e à sala. O doente só recebe `consultation_scheduled` depois de ambos os recursos responderem com `reservation_confirmed`. Se alguma confirmação falhar, a reserva tentativa é cancelada e o pedido permanece na fila para nova tentativa.

A janela administrativa configurada é:

```text
08h00–20h00 simuladas
```

Fora desse período, a triagem central envia uma alta administrativa ao doente caso ainda não tenha sido encaminhado. Urgências não interrompem nem cancelam consultas de rotina.

### 7.2 Urgências

Pacientes urgentes são encaminhados para triagem local e urgência. O sistema atribui prioridade clínica e mantém a fila ordenada por gravidade/prioridade. As urgências:

- não têm horário fixo de consulta;
- usam apenas médicos classificados como urgência;
- usam apenas salas classificadas como urgência;
- não preemptam consultas de rotina;
- podem acionar chamada extraordinária de médicos de urgência fora do turno quando permitido pela configuração.

### 7.3 Triagem central multi-hospital

A triagem central preserva o `tipo_original` do doente, distinguindo corretamente pacientes normais e urgentes mesmo quando entram pela via central. Depois consulta os supervisores dos hospitais e encaminha o paciente para o hospital com menor carga relevante.

Para consultas de rotina, a carga já não corresponde apenas à fila pendente. O supervisor considera também as consultas futuras já agendadas/em curso, por especialidade e no total. Assim, um hospital que esvaziou a fila à custa de uma agenda futura muito cheia continua a aparecer como carregado na triagem central.

### 7.4 Exames/MCDT

Quando um médico pede exame, o pedido passa pelo coordenador de exames. O coordenador usa Contract Net para escolher equipamento e médico por disponibilidade, especialidade e `score`. O médico solicitante aguarda um `exam_result` real. Se o exame falhar por indisponibilidade persistente, é enviada uma resposta explícita de falha.

Exames já não são bloqueados pela janela administrativa das consultas de rotina; dependem da escala, especialidade e disponibilidade dos recursos. A lógica de prioridade/preempção fica limitada a exames e cirurgias, não contaminando as consultas.

### 7.5 Cirurgias

Quando um exame recomenda cirurgia, o médico solicitante pede intervenção ao coordenador de cirurgias e aguarda um `surgery_result` real. O coordenador de cirurgias usa fila com backoff e limite de tentativas para evitar repetição constante de falhas.

Cirurgias também não são bloqueadas pela janela administrativa das consultas de rotina; dependem da escala cirúrgica, bloco disponível e cirurgião adequado. Tal como nos exames, podem manter prioridade/preempção para casos urgentes.

### 7.6 Internamento

O internamento é coordenado por fila com backoff, limite de tentativas e alocação de quarto/enfermeiro. No fim do internamento, o recurso é libertado e o doente recebe alta, evitando agentes de pacientes presos até ao fim da simulação.

## 8. Estratégia de alocação

A estratégia de alocação é híbrida:

### Consultas de rotina

As consultas de rotina usam agenda centralizada no `CoordenadorConsultas`. O algoritmo procura o primeiro slot futuro válido para médico+sala dentro do turno e da janela 08h–20h. A reserva fica inicialmente em estado `reservada`; só passa a `agendada` depois das confirmações explícitas do médico e da sala.

### Urgências, exames, cirurgias, triagem e internamento

Os restantes fluxos usam uma estratégia inspirada no **FIPA Contract Net**:

1. o coordenador envia um CFP aos recursos candidatos;
2. os recursos disponíveis respondem com proposta;
3. cada proposta inclui um `score`;
4. o coordenador escolhe a melhor proposta, privilegiando menor carga/maior disponibilidade;
5. o recurso selecionado executa o ato e liberta-se no fim.

A preempção fica limitada a exames e cirurgias. Consultas de rotina não são preemptáveis.

## 9. Configurações úteis

As principais constantes estão em `src/config.py`:

```text
SIMULATION_DURATION              duração real da simulação
ARRIVAL_RATE_NORMAL              taxa base de chegada de pacientes normais
ARRIVAL_RATE_URGENT              taxa base de chegada de pacientes urgentes
ARRIVAL_PROFILE_NORMAL           multiplicadores por período horário para rotina
ARRIVAL_PROFILE_URGENT           multiplicadores por período horário para urgência
PROB_CENTRAL_TRIAGE              probabilidade de entrada pela triagem central
ROUTINE_START_H / ROUTINE_END_H  janela das consultas de rotina
CONSULTATION_SLOT_MINUTES        espaçamento entre slots de rotina
CONSULTATION_DURATION_NORMAL_SECONDS duração clínica da consulta de rotina
ROUTINE_DISPATCH_BATCH_LIMIT     máximo de pedidos de rotina despachados por ciclo
DISPATCH_BATCH_LIMIT             limite-base dos restantes coordenadores
ROUTINE_RESERVATION_CONFIRM_TIMEOUT_SECONDS tempo máximo para confirmar médico+sala
EXAM_MAX_RETRIES                 limite de tentativas para exames
SURGERY_MAX_RETRIES              limite de tentativas para cirurgias
INTERNMENT_MAX_RETRIES           limite de tentativas para internamento
```



### Afluência variável

As chegadas deixaram de ser lineares. O gerador usa `arrival_rate_for_hour()` e os perfis `ARRIVAL_PROFILE_NORMAL` / `ARRIVAL_PROFILE_URGENT`, configurados em `src/config.py`, para simular picos de manhã, períodos mais calmos a meio do dia e variação ao fim da tarde/noite. Não foi implementado o sistema de centros de saúde, por decisão de âmbito.

### Separação de recursos

Os médicos e salas estão classificados por função no `AGENT_REGISTRY`. Nas consultas de rotina, o coordenador escolhe diretamente apenas médicos `consult_mode="routine"` e salas `category="routine"` através da agenda centralizada. Nas urgências, só são consultados médicos `consult_mode="emergency"` e salas `category="emergency"`. As salas continuam a validar a sua categoria antes de responder a propostas nos fluxos que usam Contract Net.

## 10. Logs e outputs

Durante a execução, o sistema escreve eventos no terminal e gera ficheiros em:

```text
data/
outputs/
```

Para uma entrega final, recomenda-se não incluir ficheiros temporários, logs antigos, `.env`, `.git` e pastas `__pycache__`.

## 11. Comando recomendado para demonstração

Para uma demonstração curta e estável:

```bash
python3 dashboard.py
```

Noutro terminal:

```bash
SIMULATION_DURATION=180 python3 main_sim.py
```

Durante a defesa, podes explicar que os 180 segundos reais correspondem a uma execução reduzida para apresentação, mas que o tempo pode ser aumentado por configuração.
