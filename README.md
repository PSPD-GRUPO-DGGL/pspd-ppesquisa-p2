# PSPD 2026.1 — Projeto de Pesquisa: Observabilidade de microsserviços em cluster K8s

Aplicação de microsserviços para o Hospital Universitário, com dados clínicos expostos em HL7/FHIR sob três perfis de acesso, instrumentada com Prometheus/Grafana e submetida a testes de carga num cluster Kubernetes multi-nó.

Disciplina PSPD (T02), Prof. Fernando William Cruz — UnB/FGA. Grupo DGGL.

> **Estado atual.** Contratos, banco, especificações, Data Transform Service, chat `epoll` com o experimento C10K e os cenários de carga k6 estão implementados e verificados. Authorization Service, Patient Data Service, API Gateway, frontend e a stack de observabilidade estão especificados e aguardando implementação. Ver [Divisão de tarefas](#divisão-de-tarefas).

## Arquitetura

```
                        ┌──────────┐
   Frontend ──REST/HTTP1─▶ Gateway │
      │                  └────┬─────┘
      │ OIDC                  │ gRPC / HTTP2
      ▼                       ├──────────▶ Authorization Service ─┐
  Keycloak                    ├──────────▶ Patient Data Service ──┼─▶ PostgreSQL
  (JWT RS256)                 └──────────▶ Data Transform Service ┘
```

O Gateway valida o JWT contra o JWKS do Keycloak e orquestra um **pipeline sequencial com ramo condicional** — não um fan-out paralelo. O Authorization Service precisa devolver o nível de acesso antes que o Transform possa aplicá-lo, e o Patient Data precisa devolver linhas antes do Transform. Uma negação corta o pipeline no primeiro estágio, sem tocar em banco.

## O que já está pronto

| Artefato | Onde | Verificado por |
|---|---|---|
| Contratos gRPC (4 arquivos proto3) | `proto/` | compilam com `grpc_tools.protoc` |
| Schema das 5 tabelas | `db/schema/01_schema.sql` | carrega em Postgres 16 |
| Seed sintético determinístico | `db/seed/02_seed.sql` | 50k pacientes, 1,27M eventos, 27s |
| Índices e sua justificativa | `db/schema/03_indices.sql` | `EXPLAIN ANALYZE` (ver abaixo) |
| Matriz de nível de acesso | `docs/matriz-acesso.md` | — (normativo) |
| Mapeamento relacional → FHIR | `docs/mapeamento-fhir.md` | — (normativo) |
| **Data Transform Service** | `servicos/transform/` | 52 testes + smoke gRPC + container |
| **Chat `epoll` + experimento C10K** | `chat/` | 3 servidores em C, medidos até 10k conexões |
| **Cenários de carga k6** | `k6/` | 4 cenários, validados com `k6 inspect` |

### O contraste que sustenta o experimento

Os índices são projetados para que os dois caminhos custem coisas diferentes. Medido em Postgres 16, 50k pacientes:

| Caminho | Tempo | Plano |
|---|---|---|
| FULL — prontuário de 1 paciente | **0,25 ms** | index scan puro |
| AGGREGATED — coorte Diabetes | **154,6 ms** | parallel seq scan de 961k linhas + sort externo em disco |

Fator de ~620×. A coorte em si é resolvida por índice (barato, de propósito); o custo está na agregação. É isso que permite testar a hipótese central do trabalho: **escala horizontal ajuda serviço stateless compute-bound, mas não resolve um banco compartilhado.**

### C10K: o custo de uma conexão ociosa

Três servidores de chat com o mesmo protocolo, 10 mil conexões e 1% ativas (`docs/experimento-c10k.md`):

| | memória por conexão | msgs por segundo de CPU | conexões aceitas |
|---|---|---|---|
| `epoll` | **4,2 KB** | **273.238** | 10.000 |
| thread-por-conexão | 12,4 KB | 75.603 | 10.000 |
| `select()` | — | — | **1.020** (teto do `FD_SETSIZE`) |

O `epoll` mantém a mesma eficiência com mil ou dez mil conexões: é a propriedade O(1) medida. O `select()` não é lento, é impossível — `fd_set` tem 1024 bits e o limite é da libc, não do programa.

## Como rodar o que existe

Pré-requisitos: Docker, Python 3.12.

```bash
# 1. Banco com dados
docker run -d --name pspd-pg -e POSTGRES_PASSWORD=pspd -e POSTGRES_DB=hospital \
  -p 5432:5432 postgres:16-alpine
docker exec -i pspd-pg psql -U postgres -d hospital < db/schema/01_schema.sql
docker exec -i pspd-pg psql -U postgres -d hospital -v n_pacientes=50000 < db/seed/02_seed.sql
docker exec -i pspd-pg psql -U postgres -d hospital < db/schema/03_indices.sql

# Para um smoke test rápido, use -v n_pacientes=2000 (leva ~1s)

# 2. Stubs gRPC (não são versionados: são artefato de build)
python3 -m venv .venv && ./.venv/bin/pip install grpcio-tools==1.64.1
./scripts/gen_protos.sh

# 3. Data Transform Service
./.venv/bin/pip install -r servicos/transform/requirements.txt pytest
cd servicos/transform
PYTHONPATH=. ../../.venv/bin/python -m pytest tests/ -q      # 52 testes
ANON_SALT=troque-isto PYTHONPATH=. ../../.venv/bin/python server.py &
PYTHONPATH=. ANON_SALT=troque-isto ../../.venv/bin/python cliente_teste.py
curl -s localhost:8000/metrics | grep '^transform_'
```

Em container:

```bash
docker build -f servicos/transform/Dockerfile -t pspd/transform:0.1.0 .
docker run -d -e ANON_SALT=troque-isto -p 50053:50053 -p 8000:8000 pspd/transform:0.1.0
```

Chat e experimento C10K:

```bash
cd chat && make todos
./bin/servidor_epoll 9100 --metricas 9101 &
./bin/cliente_chat 127.0.0.1 9100 ana          # em outro terminal
./scripts/experimento_c10k.sh 8 1000 5000 10000
```

`ANON_SALT` não tem valor padrão e o serviço **falha alto** sem ele. Isso é intencional: o espaço de `id_paciente` é pequeno e conhecido (50 mil valores), então pseudonimizar com salt público é reversível por força bruta em segundos. Ver `docs/matriz-acesso.md` §2.

## Divisão de tarefas

A alocação segue afinidade com o T1 e **grau de dependência**: quem depende de menos gente fica com o que pode ser terminado primeiro.

| Integrante | Responsabilidade | Estado |
|---|---|---|
| **Gabriel Soares dos Anjos** | Base do projeto (contratos, banco, especificações) · **Data Transform Service** · **chat `epoll` + experimento C10K** · **cenários k6** · estrutura do relatório | ✅ tudo entregue, exceto o relatório |
| **Danilo Carvalho Antunes** | Keycloak (realm como código, JWKS) · **Authorization Service** · **Patient Data Service** · experimento pgbouncer | ⬜ especificado |
| **Guilherme Brito de Souza** | **API Gateway** (validação JWKS, orquestração, `prom-client`) · frontend · validação funcional ponta a ponta · OpenTelemetry | ⬜ especificado |
| **Luiz Gustavo Lopes Campos** | Cluster **kind** de 4 nós + **kubeadm/VM** · `kube-prometheus-stack`, Grafana, SLO · HPA (CPU + customizado) · execução das corridas de carga e resiliência · consolidação do relatório e vídeo | ⬜ especificado |

O plano completo, com orçamento de RAM, cenários de carga, riscos conhecidos e critérios de verificação, está em `docs/PLANO.md`.

### Para quem vai implementar um serviço

Os contratos em `proto/` são a fonte de verdade e já compilam. Gere seus stubs com `./scripts/gen_protos.sh` e code contra eles. Três coisas que o contrato já decide por você:

1. **O Patient Data Service nunca devolve FHIR nem dado anonimizado.** Devolve `comum.ConjuntoDadosClinicos` cru. Um único componente decide o que sai, e é o único que precisa ser auditado.
2. **O Authorization Service não devolve dado clínico.** Devolve uma decisão e a lista de `ids_autorizados`. O Gateway não pode pedir ao Data mais do que o Auth autorizou.
3. **O Transform ecoa `nivel_aplicado` de volta.** Redundante de propósito: permite ao Gateway assertar que o nível pedido foi o honrado, e vira teste.

Convenções herdadas do T1: proto3 com `keepCase`, nomes em pt-BR, Conventional Commits em português, stubs `*_pb2*.py` fora do git, fim de linha LF.

## Ambiente

Todo o desenvolvimento e as medições assumem um único host: Intel i7-1255U (12 threads), 16 GB de RAM. O orçamento de memória do cluster completo está em `docs/PLANO.md` e é a restrição que governa as decisões de infraestrutura — inclusive a de rodar o k6 **fora** do cluster, para não contaminar as métricas dos pods sendo medidos.

## Referências

- Arundel, J. e Domingus, J. *Cloud Native DevOps with Kubernetes*. O'Reilly, 2019. (Capítulos 15 e 16 — monitoramento e observabilidade.)
- HL7 FHIR R4 — https://www.hl7.org/fhir/
- Kubernetes — https://kubernetes.io
- Prometheus — https://prometheus.io/
