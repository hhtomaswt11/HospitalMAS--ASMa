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

A arquitetura segue uma lógica descentralizada: os coordenadores não executam diretamente os atos clínicos; negoceiam com recursos disponíveis através de uma lógica próxima do protocolo **FIPA Contract Net**.

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

Por defeito, a duração está configurada para demonstração curta:

```text
SIMULATION_DURATION=180 segundos
```

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

Pacientes normais entram diretamente no hospital ou passam pela triagem central. As consultas de rotina respeitam a janela administrativa configurada:

```text
08h00–20h00 simuladas
```

Fora desse período, a triagem central envia uma alta administrativa ao doente caso ainda não tenha sido encaminhado.

### 7.2 Urgências

Pacientes urgentes são encaminhados para triagem local e urgência. O sistema atribui prioridade clínica e tenta alocar médico/sala adequados. A urgência pode acionar chamada extraordinária de médicos fora do turno quando permitido pela configuração.

### 7.3 Triagem central multi-hospital

A triagem central preserva o `tipo_original` do doente, distinguindo corretamente pacientes normais e urgentes mesmo quando entram pela via central. Depois consulta os supervisores dos hospitais e encaminha o paciente para o hospital com menor carga relevante.

### 7.4 Exames/MCDT

Quando um médico pede exame, o pedido passa pelo coordenador de exames. O coordenador usa Contract Net para escolher equipamento e médico por disponibilidade, especialidade e `score`. O médico solicitante aguarda um `exam_result` real. Se o exame falhar por indisponibilidade persistente, é enviada uma resposta explícita de falha.

Exames já não são bloqueados pela janela administrativa das consultas de rotina; dependem da escala, especialidade e disponibilidade dos recursos.

### 7.5 Cirurgias

Quando um exame recomenda cirurgia, o médico solicitante pede intervenção ao coordenador de cirurgias e aguarda um `surgery_result` real. O coordenador de cirurgias usa fila com backoff e limite de tentativas para evitar repetição constante de falhas.

Cirurgias também não são bloqueadas pela janela administrativa das consultas de rotina; dependem da escala cirúrgica, bloco disponível e cirurgião adequado.

### 7.6 Internamento

O internamento é coordenado por fila com backoff, limite de tentativas e alocação de quarto/enfermeiro. No fim do internamento, o recurso é libertado e o doente recebe alta, evitando agentes de pacientes presos até ao fim da simulação.

## 8. Estratégia de alocação

Os coordenadores usam uma estratégia inspirada no **FIPA Contract Net**:

1. o coordenador envia um CFP aos recursos candidatos;
2. os recursos disponíveis respondem com proposta;
3. cada proposta inclui um `score`;
4. o coordenador escolhe a melhor proposta, privilegiando menor carga/maior disponibilidade;
5. o recurso selecionado executa o ato e liberta-se no fim.

Isto aplica-se a consultas, urgências, exames, cirurgias, triagem e internamento.

## 9. Configurações úteis

As principais constantes estão em `src/config.py`:

```text
SIMULATION_DURATION              duração real da simulação
ARRIVAL_RATE_NORMAL              probabilidade/ritmo de chegada de pacientes normais
ARRIVAL_RATE_URGENT              probabilidade/ritmo de chegada de pacientes urgentes
PROB_CENTRAL_TRIAGE              probabilidade de entrada pela triagem central
ROUTINE_START_H / ROUTINE_END_H  janela das consultas de rotina
EXAM_MAX_RETRIES                 limite de tentativas para exames
SURGERY_MAX_RETRIES              limite de tentativas para cirurgias
INTERNMENT_MAX_RETRIES           limite de tentativas para internamento
```

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
