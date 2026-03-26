# Sistema Multiagente — Gestão Hospitalar Descentralizada

> Framework SPADE | Protocolo FIPA-Contract-Net | Python 3.8+

Um sistema multiagente autónomo desenhado para simular fluxos hospitalares críticos, incluindo consultas de rotina, cascatas de cuidados (Consultas → Exames → Cirurgias), e protocolos de preemption dinâmica para emergências.

## Arquitetura Modular

O projeto segue standard Python Enterprise:

```text
├── src/
│   ├── config.py              # Central de configurações e ambiente
│   └── agents/
│       ├── resources.py       # AgenteDoente, AgenteTriagem, AgenteMedico, AgenteSala
│       ├── coordinators.py    # Coordenadores (Consultas, Urgências, Exames, Cirurgias)
│       └── supervisor.py      # Agente Supervisor (Dashboard e Orquestração)
├── main.py                    # Entry-point executável da simulação
├── requirements.txt           # Dependências
├── .env                       # Variáveis de ambiente locais
└── data/                      # Logs persistentes gerados em execução
```

## Pré-requisitos & Instalação

### 1. Ambiente Virtual e Dependências
Crie um ambiente Python e instale os pacotes necessários:
```bash
pip install -r requirements.txt
```

### 2. Configuração do Servidor XMPP
O sistema baseia-se na framework SPADE para troca de mensagens FIPA-ACL. Irá necessitar de ter acesso a um servidor XMPP local ou remoto configurado para testes de agentes em desenvolvimento.
Copie o ficheiro `.env.example` para `.env` e introduza o IP do seu servidor XMPP:
```bash
cp .env.example .env
```
Edite o `.env` (o IP standard para testes locais costuma ser `127.0.0.1`):
```text
XMPP_SERVER=127.0.0.1
XMPP_PASSWORD=sua_password_aqui
```

## Execução da Simulação

Execute o motor central do sistema:
```bash
python3 main.py
```

### O que esperar no output
O Supervisor mantém um fluxo de *Audit Logging* contínuo no terminal e grava diretamente no ficheiro `data/log_supervisor.txt`. O fluxo divide-se em:

1. **Fase 1 (Rotina):** Adjudicação FIPA-Contract-Net bem sucedida de um doente regular.
2. **Fase 2 (Congestionamento):** Rejeição por falta de capacidade num sistema fixo.
3. **Fase 3 (Urgência & Preemption):** Entrada na triagem gera interrupção assíncrona. O Supervisor ordena o cancelamento (`cancel`) de rotinas ativas para atender a urgência imediata.
4. **Fase 4 (Cascata de Cuidados):** Avaliação clínica autónoma despoleta negociações sequenciais para Diagnóstico (Equipamentos) e Cirurgia (Blocos Operatórios e Cirurgiões), encapsulando o processo final de alta e libertação global de recursos.
