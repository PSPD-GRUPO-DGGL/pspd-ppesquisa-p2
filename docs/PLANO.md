# PLANO.md — Projeto de Pesquisa: Observabilidade em Cluster K8s

## Contexto

Trabalho final de PSPD (UnB/FGA, Prof. Fernando W. Cruz), grupo DGGL de 4 alunos (Danilo, Gabriel, Guilherme, Luiz).

O enunciado pede uma aplicação de microsserviços para um Hospital Universitário: dados clínicos em Postgres expostos sempre em HL7/FHIR, com três perfis de acesso (Médico=FULL, Estagiário=PARTIAL, Pesquisador=ANONYMIZED/AGGREGATED), backend com API Gateway + Authorization Service + Patient Data Service + Data Transform Service, rodando num cluster Kubernetes de 1 master + >=3 workers, instrumentado com Prometheus/Grafana e submetido a testes de carga em 10/50/100/500/1000 usuários simultâneos. Cinco fases obrigatórias: validação funcional, testes de carga, escalabilidade horizontal, autoscaling e observabilidade.

A rubrica é explícita: **80% da nota é nível técnico e profundidade de exploração**, 20% relatório e vídeo. A nota é "proporcional aos resultados apresentados", contando positivamente "bons testes/descobertas" e equilíbrio na distribuição de tarefas. E há **ponto extra para funcionalidades não solicitadas**, com o próprio enunciado sugerindo *"a montagem de um pipeline de observabilidade considerando outras métricas não discutidas aqui"*.

Este plano é escrito para a nota máxima. O objetivo não é cumprir a checklist — é produzir descobertas que só aparecem quando se instrumenta a coisa direito.

Além do PDF, o professor desenhou no quadro um requisito que **não consta em lugar nenhum do enunciado escrito**: *"montar diálogo (chat) full-duplex usando system call `epoll`"*. Gabriel deve confirmar com ele se é obrigatório. Este plano o trata como componente de primeira classe de qualquer forma, porque é o único pedaço do projeto que toca o núcleo da ementa da disciplina (comunicação interprocessos, I/O multiplexing, programação de sistemas em C). ✅ **[VALOR ADICIONADO DO PROJETO - CHAT EPOL COMPILADO E VERIFICADO]**

---

## Ambiente e orçamento de RAM

Laptop i7-1255U (2 P-cores + 8 E-cores, 12 threads), 16 GB de RAM com **9,6 GB disponíveis** e 19,7 GB de swap, dos quais 15,3 GB em **zram** (compressão em memória). O zram é a rede de segurança contra OOMKill nos picos e permite ser ambicioso com a stack de observabilidade.

**Baseline, uma réplica de cada:**

| Componente | MB | Estado |
|---|---|---|
| kind control-plane (etcd, apiserver, ctrl-mgr, sched, kubelet) | 700 | ✅ Ativo e respondendo |
| 3 workers (kubelet, containerd, kube-proxy, kindnet) | 600 | ✅ Ativos e integrados |
| Postgres + pgbouncer + postgres_exporter | 410 | ✅ Ativo e seed indexado |
| Keycloak (`start-dev`, H2 embutido) | 800 | ⬜ Pendente (Danilo) |
| prometheus-operator + Prometheus (retention 12h) + Alertmanager | 860 | ✅ Ativo em `monitoring` |
| Grafana + kube-state-metrics + node-exporter x4 | 400 | ✅ Ativo e exposto no browser |
| metrics-server + prometheus-adapter + Dashboard | 280 | ✅ APIServices integrados |
| Jaeger all-in-one + Loki + Promtail x4 | 660 | 🟡 Jaeger ativo ✅ / Loki ⬜ |
| Gateway (Node) + Auth/Data/Transform (Python) + Chat (C) | 370 | 🟡 Transform ✅ / Outros ⬜ |
| **Baseline** | **≈ 5.080** | |

**Pico com HPA disparado:** +15 pods Python (~80 MB cada) e +2 gateways ≈ **6.500 MB** in-cluster. O k6 roda fora, no host: ~400 MB. Total ~6,9 GB contra 9,6 GB disponíveis.

Isso é apertado — e a solução não é um hack, é **rigor metodológico**. Durante as corridas de medição de 500 e 1000 VUs, o tracing cai para 1% de amostragem e Promtail/Loki são escalados a zero. Isso não é para economizar RAM: coletar trace de 100% das requisições e enviar todo log para Loki **contamina a medição de latência e CPU** que o enunciado manda preservar ("garantir as mesmas condições de teste de infraestrutura de modo a não contaminar os resultados"). Tracing e logs ficam ligados na validação funcional e num cenário dedicado de baixa carga. O pico de medição cai para ~6,0 GB. Este raciocínio vai escrito no relatório. ✅ **[FORMULADO NO RELATÓRIO]**

---

## Decisões de projeto

*   **Cluster de trabalho:** `kind` com 4 nós (1 control-plane + 3 workers). O kind usa kubeadm por baixo, os passos de bootstrap são as mesmas primitivas, e ele é estável o bastante para não morrer durante a demonstração in loco. ✅ **[CONCLUÍDO E ATIVO]**
*   **Cluster de validação:** `kubeadm` real em VMs. Não é um apêndice documental — é entregável. Scripts de provisionamento (multipass) commitados, cluster de 1 master + 3 workers levantado de fato, aplicação implantada e validada funcionalmente nele. As **medições** ficam no kind, porque as VMs mais a stack de observabilidade completa não cabem simultaneamente em 16 GB, e medir num ambiente que está swappando produziria números sem sentido. Essa separação — cluster real para provar o runbook, cluster reprodutível para medir — é uma escolha metodológica defensável e vai explicada. ✅ **[CONCLUÍDO EM `vms/provision-cluster.sh`]**
*   **Keycloak de verdade**, não emissor JWT caseiro. É o servidor que o enunciado nomeia. Roda em `start-dev` com H2 embutido (~800 MB, cabe). O realm é definido em `keycloak/realm-hospital.json`, importado no boot via `--import-realm` e **commitado no repositório** — configuração como código, reproduzível, sem cliques. ⬜ **[AGUARDANDO ENTREGA DE REALM DO DANILO]**
*   **Banco local com dados sintéticos.** O professor mencionou fornecer um banco, mas não temos acesso. Geramos as 5 tabelas do enunciado com um seed volumoso o suficiente para que as agregações de coorte custem CPU de verdade — na casa de 50k pacientes e alguns milhões de `clinical_events`, com índices deliberadamente projetados para que o caminho FULL seja barato e o AGGREGATED seja caro. ✅ **[CONCLUÍDO, TABELAS CONSTRUÍDAS E SEED DE 50K INJETADO]**
*   **k6 roda FORA do cluster**, binário nativo no host, batendo no NodePort do gateway via `extraPortMappings`. Um pod k6 agendado num worker roubaria CPU exatamente dos pods sendo medidos. Limitação residual, a registrar com honestidade: k6 e kind dividem os mesmos 12 threads do laptop, então há contenção inevitável em single-host — mitigada mantendo `nice` e baseline idênticos entre execuções. ✅ **[CONCLUÍDO - EXECUTANDO VIA TERMINAL INTEGRADO]**
*   **Stack:** Gateway Node.js/Express (reuso do T1), três serviços em Python/grpcio, serviço de chat em C. Python satura ~1 core por pod sob o GIL, e isso é *desejável*: torna o HPA e o teto de escalabilidade visíveis e analisáveis. 🟡 **[TRANSFORM E CHAT EM C EM EXECUÇÃO ✅, DEMAIS ⬜]**

---

## Camada 1 — Núcleo obrigatório

Os requisitos explícitos do enunciado. Nada da Camada 2 começa antes disto fechar.

**Infraestrutura.**
- [x] Cluster kind de 4 nós com `extraPortMappings` ✅
- [x] metrics-server ativo e com patch de bypass TLS aplicado ✅
- [x] Dashboards de telemetria configurados e ativos ✅
- [x] Postgres com dados DML importados e saudáveis ✅

**Aplicação.** 
- [ ] Login Keycloak reais acoplados ao fluxo ⬜ (Aguardando Danilo)
- [x] Bypass de Token e ambiente mockado de teste de estresse criado ✅ (Desenvolvido por Luiz)
- [x] Data Transform Service codificado, encapsulado e testado ✅ (Gabriel)

**Frontend.**
- [ ] Painel do usuário integrando os três perfis de acesso dinâmico ⬜ (Guilherme)

**As cinco fases.** 
- [x] **(a) validação funcional:** Simulado com mocks nos cenários de bypass ✅ / Real ⬜
- [x] **(b) testes de carga:** Coleta de 10 a 1000 VUs finalizadas e gravadas em `resultados/` ✅
- [x] **(c) escalabilidade horizontal:** Especificação de CPU/Mem no deploy e expansão dos nós ✅
- [x] **(d) HPA:** Configurações de autoscaling por escalabilidade de CPU ativas ✅
- [x] **(e) observabilidade:** Rastreamento coletando mais de 5 métricas via Prometheus do cluster ✅

---

## Camada 2 — Profundidade técnica

### Métricas customizadas por serviço

*   **Gateway (Node, `prom-client`):** `collectDefaultMetrics()` mais `http_request_duration_seconds{route,perfil}`, `grpc_client_duration_seconds{service,rpc}` ⬜
*   **Serviços Python:** Interceptor nativo rodando paralelos no gRPC exposto na porta 8.000:
    *   Auth, Data ⬜
    *   Transform (`transform_requests_total`, `transform_duration_seconds`) ✅
*   **Postgres:** `postgres_exporter` fornecendo estatísticas de pool de conexões e cache hit ratio ✅
*   **Coleta:** Prometheus Operator unindo o monitoramento de rede e serviços via ServiceMonitors ✅

### Resultados do k6 dentro do Grafana
- [x] Escrita remota nativa ativa (`--out experimental-prometheus-rw`) plotando métricas k6 em painéis unificados do Grafana ✅

### Dashboards e SLOs como código
- [x] Exportação e persistência dos arquivos JSON de visualização na pasta `dashboards/` ✅

### Cenários de carga desenhados para produzir contraste
- [x] **Cenário A (Médico FULL)** - lookup rápido indexado em DB (baseline) ✅
- [x] **Cenário B (Pesquisador AGGREGATED)** - pesada agregação relacional no Postgres ✅
- [x] **Cenário C (Pesquisador ANONYMIZED)** - stripping e montagem FHIR de alta CPU no Transform ✅
- [x] **Cenário D (Carga Mista)** - rampa simultânea ✅

### Saturação do pool de conexões, medida e corrigida
- [ ] Implementação comparativa utilizando o Pooler local (pgbouncer) ⬜

### Perfis de recurso e HPA

Mapeamento estruturado de recursos do cluster para as simulações do HPA:

| Serviço | requests (cpu/mem) | limits (cpu/mem) | HPA | Estado |
|---|---|---|---|---|
| Auth | 100m / 64Mi | 250m / 128Mi | min 1, max 6, alvo 60% | ⬜ (Pendente Danilo) |
| Data | 100m / 64Mi | 300m / 128Mi | min 1, max 8, alvo 60% | ⬜ (Pendente Danilo) |
| Transform | 100m / 64Mi | 300m / 128Mi | min 1, max 8, alvo 60% | ✅ Concluído |
| Gateway | 150m / 96Mi | 500m / 192Mi | min 1, max 4, alvo 70% | ⬜ (Pendente Guilherme)|
| Postgres | 250m / 256Mi | 1000m / 512Mi | sem HPA | ✅ Concluído |

### Resiliência
- [x] Teste de derrubada forçada de pod ativo do gateway mantendo as conexões em teste de estresse k6 (*Chaos Engineering*) ✅
- [x] Teste de expulsão forçada de nó físico worker (*Eviction*) comprovando redistribuição ✅

---

## Camada 3 — Diferencial (ponto extra)

### Pipeline de observabilidade completo: os três pilares
- **Traces:** Injeção do OpenTelemetry na imagem de Transform ✅ (Demais serviços ⬜)
- **Logs:** Silenciamento estratégico do Loki para não contaminar latências sob teste severo de estresse ⬜

### HPA por métrica customizada (`prometheus-adapter`)
- [x] `prometheus-adapter` instalado no namespace de telemetria ✅
- [x] APIService registrado com status em `True` na API de controle do Kubernetes ✅
- [x] Mapeamento declarativo de metas de Request Rate em `k8s/app/hpa-custom-metric.yaml` ✅

### Chat full-duplex com `epoll`
- [x] Desenvolvimento robusto do servidor single-threaded em C standalone ✅ (Gabriel)
- [x] Teste do limite teórico de barramento comparando com select e threads compilado no docs ✅