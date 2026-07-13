# PSPD 2026.1 · Projeto de Pesquisa: Observabilidade de microsserviços em cluster K8s

Aplicação de microsserviços para o Hospital Universitário, com dados clínicos expostos em HL7/FHIR sob três perfis de acesso, instrumentada com Prometheus/Grafana e submetida a testes de carga num cluster Kubernetes multi-nó.

Disciplina PSPD (T02), Prof. Fernando William Cruz, UnB/FGA. Grupo DGGL.

> **Estado atual (2026-07-13): entregue e validado no cluster real.** A aplicação está deployada em `kiriland.unb.br`, namespace `grupo-9`, contra o banco `pseudopep_g09` e o Keycloak real (realm `grupo09`, client `pseudopep-frontend`), acessível em `https://kiriland.unb.br/grupo9`. Os quatro níveis de acesso (FULL, PARTIAL, ANONYMIZED, AGGREGATED, mais DENY) foram validados pela URL pública. A matriz de experimentos de carga (E0 a E5: baseline, escala do Transform, escala do Data, escala de tudo, autoscaling por HPA) rodou por completo. Resultados em `resultados/matriz-final/`, análise em `docs/relatorio-final.md`. A observabilidade usa Prometheus próprio no namespace (`k8s/app/prometheus.yaml`), com Grafana lido fora do cluster via `port-forward`. Duas pendências: login via browser depende do professor liberar o redirect do Keycloak para `/grupo9`, e o experimento pgbouncer está planejado mas não implementado no `grupo-9`.

## Ambiente final da entrega

As orientações novas do professor sobre cluster, banco, Keycloak e Grafana prevalecem sobre instruções antigas deste repositório quando houver conflito.

| Item | Valor |
|---|---|
| Cluster | K8S da disciplina em `kiriland.unb.br` |
| Namespace | `grupo-9` |
| Kubeconfig | `../kubeconfig-grupo-9.yaml` fora do git |
| URL pública | `https://kiriland.unb.br/grupo9` |
| Banco | `pseudopep_g09` |
| Keycloak | `https://kiriland.unb.br/keycloak`, realm `grupo09` |
| Grafana | Prometheus próprio no namespace (`k8s/app/prometheus.yaml`), lido via `kubectl port-forward svc/prometheus 9090` + Grafana local. Integração com `https://grafana.kiriland.unb.br` (institucional) não confirmada. |
| Registry de imagens | `docker.io/sanjos3` (`pspd-auth`, `pspd-data`, `pspd-transform`, `pspd-gateway`, tag `0.1.0`) |

Segredos não devem ser versionados. Senhas de banco, tokens, kubeconfig, senha SSH e `ANON_SALT` devem entrar via `Secret` ou variável local.

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

O Gateway valida o JWT contra o JWKS do Keycloak e orquestra um pipeline sequencial com ramo condicional, não um fan-out paralelo. O Authorization Service devolve o nível de acesso antes de o Transform aplicá-lo, e o Patient Data devolve linhas antes do Transform. Uma negação corta o pipeline no primeiro estágio, sem tocar em banco.

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
| **Authorization Service** | `servicos/auth/` | validado nos 4 fluxos contra o banco real |
| **Patient Data Service** | `servicos/data/` | validado contra `pseudopep_g09`, tradução inglês→PT |
| **API Gateway** (Node/Express) | `gateway/` | JWKS RS256, pipeline sequencial, deployado |
| **Frontend** (Keycloak-js) | `frontend/` | UI por perfil, servido pelo próprio Gateway |
| **Chat `epoll` + experimento C10K** | `chat/` | 3 servidores em C, medidos até 10k conexões |
| **Cenários de carga k6** | `k6/` | 4 cenários, executados no cluster real |
| **Manifests do `grupo-9`** | `k8s/app/` | deployados; 4 serviços `Running` |
| **Prometheus próprio** | `k8s/app/prometheus.yaml` | 4 targets `up`, coletando |
| **Matriz de experimentos E0–E5** | `scripts/exp_runner.sh`, `resultados/` | executada por completo no cluster real |

## Resultados finais no cluster real

Validação funcional (fase a): os quatro níveis de acesso, testados pela URL pública.

| Nível | Usuário | Resultado |
|---|---|---|
| FULL | `med.cardoso` → `P090000002` | `200`, Bundle FHIR |
| DENY | `med.cardoso` → `P090000001` (sem vínculo) | `403`, `sem_vinculo_ativo` |
| PARTIAL | `est.ferreira` → `P090000030` | `200`, Bundle FHIR |
| AGGREGATED | `pes.mendes` → `PRJ01_G09`/DIABETES | `200`, `MeasureReport` FHIR |

Matriz de carga (fases b a d): throughput e erro real a 1000 VUs sustentados, por configuração de réplicas.

| Config. | Throughput | p95 | Erro real |
|---|---|---|---|
| E0 (1 réplica cada, baseline) | 35,95 rps | 21.715 ms | 10,44% |
| E2 (Transform×3) | 40,73 rps | 19.266 ms | 9,62% |
| E3 (Data×3) | 38,25 rps | 21.272 ms | 9,87% |
| E4 (todos×3) | **48,69 rps** | **12.511 ms** | **6,73%** |

A CPU nunca satura em nenhum experimento, sempre abaixo de 15% da cota. O gargalo está distribuído pela cadeia de chamadas sequenciais (Gateway, Auth, Data, Transform) e no PostgreSQL compartilhado entre os 10 grupos da disciplina, não concentrado num serviço. Escalar Transform ou Data isoladamente ajuda pouco; só escalar todos os serviços juntos (E4) produz ganho substancial. O HPA (E5) escalou de 1 para 12 pods em cerca de 3 minutos e parou, com o motivo explícito `"All metrics below target"`, sinal de que a métrica que ele observa já estava satisfeita, não de falta de capacidade do cluster. Análise completa em `docs/relatorio-final.md`.

### O contraste que sustenta o experimento

Os índices são projetados para que os dois caminhos custem coisas diferentes. Medido em Postgres 16, 50k pacientes:

| Caminho | Tempo | Plano |
|---|---|---|
| FULL (prontuário de 1 paciente) | **0,25 ms** | index scan puro |
| AGGREGATED (coorte Diabetes) | **154,6 ms** | parallel seq scan de 961k linhas + sort externo em disco |

Fator de ~620×. A coorte em si é resolvida por índice, barato de propósito. O custo está na agregação, e esse contraste permite testar a hipótese central do trabalho: escala horizontal ajuda serviço stateless compute-bound, mas não resolve um banco compartilhado.

### C10K: o custo de uma conexão ociosa

Três servidores de chat com o mesmo protocolo, 10 mil conexões e 1% ativas (`docs/experimento-c10k.md`):

| | memória por conexão | msgs por segundo de CPU | conexões aceitas |
|---|---|---|---|
| `epoll` | **4,2 KB** | **273.238** | 10.000 |
| thread-por-conexão | 12,4 KB | 75.603 | 10.000 |
| `select()` | — | — | **1.020** (teto do `FD_SETSIZE`) |

O `epoll` mantém a mesma eficiência com mil ou dez mil conexões, a propriedade O(1) medida. O `select()` não é lento, é impossível: `fd_set` tem 1024 bits, e o limite é da libc, não do programa.

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

## Como rodar no ambiente real (`grupo-9`)

Runbook que coloca a aplicação no ar em `https://kiriland.unb.br/grupo9`. Pré-requisitos: `kubectl`, `docker` autenticado num registry público (`docker login`), e o `kubeconfig-grupo-9.yaml` fornecido pelo professor.

```bash
# 1. Build + push das 4 imagens para um registry público
REGISTRY=docker.io/<seu_usuario> TAG=0.1.0 ./scripts/build_push.sh

# 2. Secret com as credenciais reais do banco (fora do git)
export KUBECONFIG=<caminho-do-kubeconfig>
kubectl -n grupo-9 create secret generic pspd-db \
  --from-literal=DB_HOST=192.168.122.1 \
  --from-literal=DB_PORT=5432 \
  --from-literal=DB_NAME=pseudopep_g09 \
  --from-literal=DB_USER=grupo09_user \
  --from-literal=DB_PASSWORD='<senha-do-professor>' \
  --from-literal=ANON_SALT="$(openssl rand -hex 16)"

# 3. Aplica os manifests (auth/data/transform/gateway/hpa/pdb/servicemonitors/ingress)
REGISTRY=docker.io/<seu_usuario> TAG=0.1.0 KUBECONFIG="$KUBECONFIG" ./scripts/deploy.sh

# 4. Prometheus próprio (observabilidade, ver Seção 2.4 do relatório)
kubectl apply -f k8s/app/prometheus.yaml

# 5. Verificar
kubectl -n grupo-9 get pods,svc,ingress,hpa
curl -s https://kiriland.unb.br/grupo9/healthz
```

Grafana local lendo o Prometheus do cluster, sem custo de cota:

```bash
kubectl -n grupo-9 port-forward svc/prometheus 9090
# aponte um Grafana local (ex.: container docker) para http://localhost:9090
```

### Matriz de experimentos (fases b–e)

Executada a partir da VM da disciplina, para não competir por CPU com os pods sob teste. `KUBECONFIG` e `PATH` precisam ser passados explicitamente se rodando via `systemd-run --user` (a VM acadêmica mata processos de sessões SSH encerradas; ver comentários em `scripts/exp_runner.sh`):

```bash
export KUBECONFIG=~/kubeconfig-grupo-9.yaml
export K6_PASSWORD_MEDICO=... K6_PASSWORD_ESTAGIARIO=... K6_PASSWORD_PESQUISADOR=...
export OUT=~/pspd-ppesquisa-p2/resultados/matriz-final

./scripts/exp_runner.sh E0   # baseline, 1 réplica cada
./scripts/exp_runner.sh E2   # Transform×3
./scripts/exp_runner.sh E3   # Data×3
./scripts/exp_runner.sh E4   # todos×3
./scripts/exp_runner.sh E5   # HPA por CPU, rampa 10→1000 VUs

cat "$OUT/matriz.csv"        # throughput/latência/erro/CPU/mem/pods por experimento e nível
```

Resultados consolidados e a análise completa estão em `docs/relatorio-final.md`, Seções 2.1–2.4.

## Como rodar a Infraestrutura e Observabilidade (laboratório local)

Esta seção descreve o laboratório local (Kind), útil para desenvolvimento e para a seção "montagem do Kubernetes" do relatório. Não é o ambiente da entrega: a validação e as medições finais foram feitas no cluster institucional (seção anterior). O HPA por métricas customizadas (`prometheus-adapter`, passo 5 abaixo) foi explorado só aqui, porque exige Helm e CRDs fora do escopo de RBAC do namespace `grupo-9` real.

### Pré-requisitos de Infraestrutura
- **Windows Subsystem for Linux (WSL2)** com Docker Desktop ativo.
- **Git Bash** (ou terminal compatível com Unix).
- **Controlador de pacotes kubectl** e **Helm v3** instalados.
- **k6** (executável nativo mapeado no PATH do host).
- **Multipass** (necessário apenas para a fase de testes em VMs reais).

---

### 1. Inicializando o Cluster Kind Multi-Nó

O desenvolvimento local pode usar um cluster Kind configurado com 1 nó de Control Plane e 3 nós Workers. A porta `30080` do host é exposta para receber tráfego do k6. Para resultados finais, usar `https://kiriland.unb.br/grupo9`.

Crie o cluster executando:
```bash
kind create cluster --config k8s/infra/kind-config.yaml --name pspd-cluster
```

Valide se todos os nós estão saudáveis (`Ready`):
```bash
kubectl get nodes -o wide
```

---

### 2. Implantando a Stack de Observabilidade Completa

Utilizamos a `kube-prometheus-stack` via Helm com o receptor de escrita remota ativo para que o k6 envie estatísticas de conexões diretamente ao banco do Prometheus do cluster.

**1. Instale o Helm Chart da stack de monitoramento:**
```bash
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f helm-values/kube-prometheus-stack.yaml
```

**2. Exponha o Metrics Server (essencial para o funcionamento do HPA):**
```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--kubelet-insecure-tls"}]'
```

**3. Instale o Prometheus Adapter de métricas customizadas:**
```bash
helm upgrade --install prometheus-adapter prometheus-community/prometheus-adapter \
  --namespace monitoring \
  -f helm-values/prometheus-adapter.yaml
```

---

### 3. Banco de Dados Postgres local

Este Postgres é apenas para desenvolvimento local. No cluster final, usar o banco institucional `pseudopep_g09` fornecido pelo professor, com credenciais em `Secret`.

**1. Crie o Postgres:**
```bash
kubectl apply -f k8s/infra/postgres.yaml
```

**2. Copie e aplique as tabelas DDL e os dados DML:**
```bash
export DB_POD=$(kubectl get pods -l app=postgres -o jsonpath="{.items[0].metadata.name}")
kubectl cp db/ "$DB_POD":/tmp/db/
kubectl exec -it "$DB_POD" -- psql -U pspd_user -d hospital -f /tmp/db/schema/01_schema.sql
kubectl exec -it "$DB_POD" -- psql -U pspd_user -d hospital -v n_pacientes=50000 -f /tmp/db/seed/02_seed.sql
kubectl exec -it "$DB_POD" -- psql -U pspd_user -d hospital -f /tmp/db/schema/03_indices.sql
```

---

### 4. Simulação de Testes de Carga com Bypass de Autenticação

Como Auth, Data, Gateway e Frontend reais ainda estão pendentes, os mocks servem só para ensaiar HPA/infra. Eles não contam como validação funcional final.

**1. Injete os declarativos Dummy e HPA na rede interna:**
```bash
kubectl apply -f k8s/app/mocks.yaml
kubectl apply -f k8s/app/hpa.yaml
```

**2. Faça o redirecionamento provisório do API Gateway local:**
```bash
kubectl port-forward svc/api-gateway 30080:80
```

**3. Execute as corridas k6 de fora do cluster:**
A execução coletará as estatísticas e as enviará direto ao Prometheus:
```bash
# Executando o cenário de 10 VUs
k6 run --vus 10 --duration 30s --out json=resultados/cenario_a_10_vus.json k6/cenarios/a_medico_full.js

# Executando a carga limite de 1000 VUs
k6 run --vus 1000 --duration 1m --out json=resultados/cenario_a_1000_vus.json k6/cenarios/a_medico_full.js
```

---

### 5. Validando a Descoberta de Métricas Customizadas (Fase d)

O cálculo de escala do HPA baseado em Request Rate segue a relação:

\( replicas = \lceil replicasAtual \times (usoAtual / target) \rceil \)

Para validar que o `prometheus-adapter` está lendo a taxa por segundo da rede e disponibilizando na API de extensões do Kubernetes, execute:

```bash
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1"
```

> Nota: Este endpoint pode expirar por *timeout* se não houver tráfego computado no cluster. Certifique-se de disparar uma carga simulável do k6 antes de rodar a chamada.

---

### 6. Instalação e provisionamento em VMs Reais (Kubeadm)

A prova de conceito no ambiente nativo simulando múltiplos servidores virtuais é provisionada pelo nosso script declarativo em Bash local.

Prepare as infraestruturas de rede nas instâncias rodando:
```bash
chmod +x vms/provision-cluster.sh
./vms/provision-cluster.sh
```

Esse script prepara as VMs via Multipass, configura o container runtime `containerd` unificado com cgroups do systemd, desativa swap e deixa o nó principal pronto para o comando `kubeadm init`.

## Divisão de tarefas

A alocação segue afinidade com o T1 e **grau de dependência**: quem depende de menos gente fica com o que pode ser terminado primeiro.

| Integrante | Responsabilidade | Estado |
|---|---|---|
| **Gabriel Soares dos Anjos** | Base do projeto (contratos, banco, especificações) · **Data Transform Service** · **chat `epoll` + experimento C10K** · **cenários k6** · **API Gateway + frontend** (reescrita) · **manifests do `grupo-9`, deploy, Prometheus** · **matriz de experimentos E0–E5** · estrutura do relatório | ✅ entregue e validado no cluster real |
| **Danilo Carvalho Antunes** | Introspecção do banco institucional · **Authorization Service** · **Patient Data Service**, validados nos 4 fluxos contra o banco real · configuração segura de banco | ✅ entregue; experimento pgbouncer planejado (não implementado no `grupo-9`) |
| **Guilherme Brito de Souza** | Gateway/frontend iniciais (contratos não batiam com os serviços reais; substituídos pela reescrita) | 🟡 ver comentário pessoal no relatório |
| **Luiz Gustavo Lopes Campos** | Infra de laboratório local (`mocks.yaml`, `kind-config`, `run_load_tests.sh`) · manifests iniciais no `grupo-9` (reconciliados) | 🟡 ver comentário pessoal no relatório |

O plano completo, com a atualização normativa do cluster institucional, está em `docs/PLANO.md`. O plano da parte do Danilo está em `docs/plano-implementacao-danilo.md`. Autoavaliação individual de cada membro em `docs/relatorio-final.md`, Seção 5.

### Para quem vai implementar um serviço

Os contratos em `proto/` são a fonte de verdade e já compilam. Gere seus stubs com `./scripts/gen_protos.sh` e code contra eles. Três coisas que o contrato já decide por você:

1. **O Patient Data Service nunca devolve FHIR nem dado anonimizado.** Devolve `comum.ConjuntoDadosClinicos` cru. Um único componente decide o que sai, e é o único que precisa ser auditado.
2. **O Authorization Service não devolve dado clínico.** Devolve uma decisão e a lista de `ids_autorizados`. O Gateway não pode pedir ao Data mais do que o Auth autorizou.
3. **O Transform ecoa `nivel_aplicado` de volta.** Redundante de propósito: permite ao Gateway assertar que o nível pedido foi o honrado, e vira teste.

Para pesquisador, há dois caminhos diferentes no `PatientDataService`: `AgregarCoorte` produz `ResultadoAgregado` para `AGGREGATED`; `BuscarCoorte` produz dados crus da coorte para o Transform aplicar `ANONYMIZED`.

Convenções herdadas do T1: proto3 com `keepCase`, nomes em pt-BR, Conventional Commits em português, stubs `*_pb2*.py` fora do git, fim de linha LF.

## Ambiente

O laboratório local assume um único host: Intel i7-1255U (12 threads), 16 GB de RAM. A medição final deve priorizar o cluster institucional do professor, que já possui 4 nós, Prometheus/Grafana e quotas por grupo.

## Referências

- Arundel, J. e Domingus, J. *Cloud Native DevOps with Kubernetes*. O'Reilly, 2019. Capítulos 15 e 16, monitoramento e observabilidade.
- HL7 FHIR R4: https://www.hl7.org/fhir/
- Kubernetes: https://kubernetes.io
- Prometheus: https://prometheus.io/
