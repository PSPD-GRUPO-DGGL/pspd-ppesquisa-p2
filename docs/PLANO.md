# PSPD — Projeto de Pesquisa: Observabilidade de microsserviços em cluster K8s

## Contexto

Trabalho final de PSPD (UnB/FGA, Prof. Fernando W. Cruz), grupo DGGL de 4 alunos (Danilo, Gabriel, Guilherme, Luiz). Entrega em 11/07/2026.

O enunciado pede uma aplicação de microsserviços para um Hospital Universitário: dados clínicos em Postgres expostos sempre em HL7/FHIR, com três perfis de acesso (Médico=FULL, Estagiário=PARTIAL, Pesquisador=ANONYMIZED/AGGREGATED), backend com API Gateway + Authorization Service + Patient Data Service + Data Transform Service, rodando num cluster Kubernetes de 1 master + ≥3 workers, instrumentado com Prometheus/Grafana e submetido a testes de carga em 10/50/100/500/1000 usuários simultâneos. Cinco fases obrigatórias: validação funcional, testes de carga, escalabilidade horizontal, autoscaling e observabilidade.

A rubrica é explícita: **80% da nota é nível técnico e profundidade de exploração**, 20% relatório e vídeo. A nota é "proporcional aos resultados apresentados", contando positivamente "bons testes/descobertas" e equilíbrio na distribuição de tarefas. E há **ponto extra para funcionalidades não solicitadas**, com o próprio enunciado sugerindo *"a montagem de um pipeline de observabilidade considerando outras métricas não discutidas aqui"*.

Este plano é escrito para a nota máxima. O objetivo não é cumprir a checklist — é produzir descobertas que só aparecem quando se instrumenta a coisa direito.

Além do PDF, o professor desenhou no quadro um requisito que **não consta em lugar nenhum do enunciado escrito**: *"montar diálogo (chat) full-duplex usando system call `epoll`"*. Gabriel deve confirmar com ele se é obrigatório. Este plano o trata como componente de primeira classe de qualquer forma, porque é o único pedaço do projeto que toca o núcleo da ementa da disciplina (comunicação interprocessos, I/O multiplexing, programação de sistemas em C).

O grupo já entregou o T1 com o mesmo professor: gateway Node/Express + dois serviços gRPC Python + minikube. Dá reuso de padrão de gateway, Dockerfiles, manifests e formato de relatório já validado. Auth, Postgres, Prometheus, k6 e FHIR são todos novos.

Repositório: `git@github.com:PSPD-GRUPO-DGGL/pspd-ppesquisa-p2.git` (local em `~/github/pspd_ppesquisa_p2`), reaproveitando arquivos do T1 por cópia.

---

## Ambiente e orçamento de RAM

Laptop i7-1255U (2 P-cores + 8 E-cores, 12 threads), 16 GB de RAM com **9,6 GB disponíveis** e 19,7 GB de swap, dos quais 15,3 GB em **zram** (compressão em memória). O zram é a rede de segurança contra OOMKill nos picos e permite ser ambicioso com a stack de observabilidade.

**Baseline, uma réplica de cada:**

| Componente | MB |
|---|---|
| kind control-plane (etcd, apiserver, ctrl-mgr, sched, kubelet) | 700 |
| 3 workers (kubelet, containerd, kube-proxy, kindnet) | 600 |
| Postgres + pgbouncer + postgres_exporter | 410 |
| Keycloak (`start-dev`, H2 embutido) | 800 |
| prometheus-operator + Prometheus (retention 12h) + Alertmanager | 860 |
| Grafana + kube-state-metrics + node-exporter ×4 | 400 |
| metrics-server + prometheus-adapter + Dashboard | 280 |
| Jaeger all-in-one + Loki + Promtail ×4 | 660 |
| Gateway (Node) + Auth/Data/Transform (Python) + Chat (C) | 370 |
| **Baseline** | **≈ 5.080** |

**Pico com HPA disparado:** +15 pods Python (~80 MB cada) e +2 gateways ≈ **6.500 MB** in-cluster. O k6 roda fora, no host: ~400 MB. Total ~6,9 GB contra 9,6 GB disponíveis.

Isso é apertado — e a solução não é um hack, é **rigor metodológico**. Durante as corridas de medição de 500 e 1000 VUs, o tracing cai para 1% de amostragem e Promtail/Loki são escalados a zero. Isso não é para economizar RAM: coletar trace de 100% das requisições e enviar todo log para Loki **contamina a medição de latência e CPU** que o enunciado manda preservar ("garantir as mesmas condições de teste de infraestrutura de modo a não contaminar os resultados"). Tracing e logs ficam ligados na validação funcional e num cenário dedicado de baixa carga. O pico de medição cai para ~6,0 GB. Este raciocínio vai escrito no relatório.

---

## Decisões de projeto

**Cluster de trabalho: `kind` com 4 nós** (1 control-plane + 3 workers). O kind usa kubeadm por baixo, os passos de bootstrap são as mesmas primitivas, e ele é estável o bastante para não morrer durante a demonstração in loco.

**Cluster de validação: `kubeadm` real em VMs.** Não é um apêndice documental — é entregável. Scripts de provisionamento (multipass) commitados, cluster de 1 master + 3 workers levantado de fato, aplicação implantada e validada funcionalmente nele. As **medições** ficam no kind, porque as VMs mais a stack de observabilidade completa não cabem simultaneamente em 16 GB, e medir num ambiente que está swappando produziria números sem sentido. Essa separação — cluster real para provar o runbook, cluster reprodutível para medir — é uma escolha metodológica defensável e vai explicada.

**Keycloak de verdade**, não emissor JWT caseiro. É o servidor que o enunciado nomeia. Roda em `start-dev` com H2 embutido (~800 MB, cabe). O realm é definido em `keycloak/realm-hospital.json`, importado no boot via `--import-realm` e **commitado no repositório** — configuração como código, reproduzível, sem cliques. Três roles (`MEDICO`, `ESTAGIARIO`, `PESQUISADOR`), usuários de teste por role, tokens RS256. O Gateway valida a assinatura contra o **JWKS** exposto pelo Keycloak (`/realms/hospital/protocol/openid-connect/certs`), com cache das chaves — não com segredo compartilhado. Isso é o fluxo OIDC correto e é o que distingue um trabalho que entendeu OAuth2 de um que fingiu.

**Banco local com dados sintéticos.** O professor mencionou fornecer um banco, mas não temos acesso. Geramos as 5 tabelas do enunciado com um seed volumoso o suficiente para que as agregações de coorte custem CPU de verdade — na casa de 50k pacientes e alguns milhões de `clinical_events`, com índices deliberadamente projetados para que o caminho FULL seja barato e o AGGREGATED seja caro.

**k6 roda FORA do cluster**, binário nativo no host, batendo no NodePort do gateway via `extraPortMappings`. Um pod k6 agendado num worker roubaria CPU exatamente dos pods sendo medidos. Limitação residual, a registrar com honestidade: k6 e kind dividem os mesmos 12 threads do laptop, então há contenção inevitável em single-host — mitigada mantendo `nice` e baseline idênticos entre execuções.

**Stack:** Gateway Node.js/Express (reuso do T1), três serviços em Python/grpcio, serviço de chat em C. Python satura ~1 core por pod sob o GIL, e isso é *desejável*: torna o HPA e o teto de escalabilidade visíveis e analisáveis.

---

## Camada 1 — Núcleo obrigatório

Os requisitos explícitos do enunciado. Nada da Camada 2 começa antes disto fechar.

**Infraestrutura.** Cluster kind de 4 nós com `extraPortMappings`; metrics-server; Kubernetes Dashboard (o "interface web de monitoramento do cluster" pedido). Postgres com schema e seed.

**Aplicação.** Os quatro componentes, fluxo ponta a ponta: login no Keycloak → JWT → Gateway valida via JWKS → Auth decide ALLOW/DENY + nível → Data consulta → Transform anonimiza e converte → Bundle FHIR. Todos os três perfis, todos os quatro níveis, e **todos os caminhos DENY** (médico pedindo paciente não vinculado; estagiário sem vínculo supervisionado; pesquisador com projeto expirado ou suspenso).

**Frontend.** Página que faz o login OIDC, guarda o token e monta a tela de consulta conforme o perfil. Não precisa ser bonito, precisa ser real — o enunciado pede frontend e o vídeo vai mostrá-lo.

**As cinco fases.** (a) validação funcional com 1 réplica; (b) testes de carga k6 em 10/50/100/500/1000 VUs com ≥4 métricas; (c) escalabilidade horizontal 1→3 réplicas com análise de ganho, utilização dos nós, distribuição dos pods e impacto no banco; (d) HPA demonstrando criação automática de pods, redistribuição de carga, redução de latência e limite de escalabilidade; (e) observabilidade com ≥5 métricas em Prometheus e Grafana.

**Entregáveis.** Relatório com todas as seções exigidas, incluindo a subseção individual de cada membro com autoavaliação. Vídeo de 4–6 minutos por aluno.

---

## Camada 2 — Profundidade técnica

É aqui que mora a diferença entre "cumpriu o enunciado" e a nota máxima. A rubrica premia "bons testes/descobertas", e descoberta não sai de instrumentação genérica.

### Métricas customizadas por serviço

Métricas de CPU e memória vindas do cAdvisor todo mundo vai ter. As de domínio, não.

**Gateway (Node, `prom-client`):** `collectDefaultMetrics()` mais `http_request_duration_seconds{route,perfil}` (histogram), `grpc_client_duration_seconds{service,rpc}` (histogram — cronometra cada hop e é o que dá "tempo de resposta por serviço"), `autorizacao_negada_total{role,motivo}` (counter), `jwt_validacao_duration_seconds` (histogram).

**Serviços Python:** grpcio não expõe `/metrics` de graça. `prometheus_client.start_http_server(8000)` em thread separada dentro do mesmo processo, e um **`grpc.ServerInterceptor` escrito à mão** cronometrando todo RPC — mais seguro e offline do que depender de `py-grpc-prometheus`. Cada pod fica com gRPC em 50051 e métricas em 8000.

- **Auth:** `auth_decisoes_total{decisao,nivel,role}`, `auth_db_query_duration_seconds`.
- **Data:** `data_queries_total{tipo}`, `data_query_duration_seconds{tipo}`, `data_db_pool_em_uso` (gauge), `data_linhas_retornadas` (histogram).
- **Transform:** `transform_requests_total{nivel}`, `transform_duration_seconds{nivel}` — esta expõe o custo real da conversão FHIR por nível de acesso —, `transform_fhir_resources_total{tipo}`.
- Todos: `grpc_server_handled_total{rpc,code}` e `grpc_server_handling_seconds{rpc}` via interceptor.

**Postgres:** `postgres_exporter` entrega consultas por segundo, conexões ativas versus `max_connections`, cache hit ratio e tempo de query — cobre "número de consultas ao banco", que o enunciado lista.

**Coleta:** `kube-prometheus-stack` via Helm, com `retention=12h`, `resources.limits` explícitos e Alertmanager **ligado** (ver SLOs abaixo). Cada serviço ganha um `Service` com porta `metrics` nomeada e um `ServiceMonitor`.

### Resultados do k6 dentro do Grafana

O k6 exporta via `--out experimental-prometheus-rw` para o Prometheus. Consequência: throughput e latência **medidos pelo cliente** aparecem no mesmo painel que CPU, memória e contagem de pods **medidos pelo cluster**, no mesmo eixo temporal. É isso que permite dizer, com um gráfico só, "no segundo 47 o HPA criou o terceiro pod e o p95 caiu de 800ms para 210ms". Sem isso, o relatório vira duas tabelas desconexas.

### Dashboards e SLOs como código

Dashboards Grafana provisionados por JSON commitado, não montados na mão. Quatro: visão do cluster, visão da aplicação (RED por serviço), visão do HPA (réplicas × carga × latência) e visão do banco.

Os capítulos 15 e 16 do Arundel & Domingus — que o enunciado manda ler — tratam de SLO e error budget. Definimos um SLO explícito (p95 < 500ms no caminho FULL, taxa de erro < 1%), escrevemos as recording rules e uma alerting rule de *burn rate* no Alertmanager, e mostramos o alerta **disparando durante o teste de 1000 VUs**. Poucos grupos vão fazer isso, e é literalmente o conteúdo do livro-texto.

### Cenários de carga desenhados para produzir contraste

O objetivo não é confirmar que "mais réplicas = mais rápido".

- **A — Médico FULL:** lookup de um paciente, SQL indexado, bundle pequeno. Baseline.
- **B — Pesquisador AGGREGATED:** agregação de coorte com `GROUP BY`, medianas e percentis sobre milhões de `clinical_events`. Latência dominada pelo Postgres.
- **C — Pesquisador ANONYMIZED:** muitas linhas pseudonimizadas e stripadas. CPU no Transform.
- **D — carga mista** com `ramping-vus` em 10/50/100/500/1000.

**A descoberta-ouro é o contraste B versus C.** No cenário C, o HPA no Transform funciona: é trabalho stateless e CPU-bound, escala horizontalmente, o p95 cai. No cenário B, o HPA no Data **não ajuda em nada** — o gargalo é o Postgres único, e adicionar réplicas de Data só multiplica conexões contra o mesmo banco. A conclusão que fecha o relatório: *escala horizontal resolve serviço stateless compute-bound; não resolve estado compartilhado.*

### Saturação do pool de conexões, medida e corrigida

Previsão: ao escalar Data para muitos pods, o total de conexões estoura o `max_connections` do Postgres e o throughput **degrada** em vez de crescer — escalar piora. Isso se mede com `data_db_pool_em_uso` e as métricas do postgres_exporter, se demonstra com um gráfico de throughput versus número de réplicas de Data que sobe e depois desce, e se corrige colocando **pgbouncer** na frente do banco. Rodar o mesmo teste antes e depois do pgbouncer, com o gráfico dos dois, é um resultado de pesquisa de verdade — hipótese, medição, intervenção, nova medição.

### Perfis de recurso e HPA

O HPA calcula `utilização = uso / requests`. Com `requests.cpu=100m` e `limits.cpu=300m`, um pod Python sob carga é throttled em 300m, lendo ~300% contra o alvo de 60% — o HPA escala agressivamente e a criação de pods fica visível no vídeo.

| Serviço | requests (cpu/mem) | limits (cpu/mem) | HPA |
|---|---|---|---|
| Auth | 100m / 64Mi | 250m / 128Mi | min 1, max 6, alvo 60% |
| Data | 100m / 64Mi | 300m / 128Mi | min 1, max 8, alvo 60% |
| Transform | 100m / 64Mi | 300m / 128Mi | min 1, max 8, alvo 60% |
| Gateway | 150m / 96Mi | 500m / 192Mi | min 1, max 4, alvo 70% |
| Postgres | 250m / 256Mi | 1000m / 512Mi | sem HPA |

O Gateway fica folgado de propósito, para que os serviços Python sejam a estrela do gargalo. O Postgres recebe CPU suficiente para o caminho leve não travar por DB — assim controlamos *quando* o banco vira gargalo, em vez de ele mascarar tudo.

Sobre o "limite de escalabilidade" (fase d.iv): não forçar um teto artificial. O kind anuncia os 12 threads por nó, então pods não vão a `Pending`. O teto real e mais interessante é físico: ao chegar a ~8–10 pods Python disputando CPU, o host satura, o throttling generaliza, e **adicionar réplicas para de reduzir o p95 — ele plateia e depois sobe**. Reporta-se como teto compute-bound do host, com o gráfico de p95 versus réplicas mostrando a virada.

### Resiliência

Dois experimentos baratos e de altíssimo impacto no vídeo. Durante um teste de carga: `kubectl delete pod` num pod de Data e observar o k8s recriá-lo, com o efeito no p95 e na taxa de erro visível no Grafana (e as `readinessProbe` evitando que tráfego vá para o pod ainda não pronto). Depois, `kubectl drain` de um worker inteiro, observando a redistribuição dos pods pelos nós restantes. O segundo experimento alimenta diretamente a análise de "distribuição dos pods" da fase (c).

Isso exige `readinessProbe` e `livenessProbe` bem definidas e um `PodDisruptionBudget` — que também rendem um parágrafo sobre classes de QoS (Guaranteed, Burstable, BestEffort) e como nossos `requests`/`limits` colocam cada pod numa delas.

---

## Camada 3 — Diferencial (ponto extra)

O enunciado diz onde está o ponto extra. Vamos exatamente lá.

### Pipeline de observabilidade completo: os três pilares

Métricas sozinhas respondem "o quê". Traces respondem "onde". Logs respondem "por quê". O enunciado sugere "montagem de um pipeline de observabilidade considerando outras métricas não discutidas aqui" — a leitura mais forte disso são os três pilares.

**Traces: OpenTelemetry + Jaeger.** Instrumentar Gateway e os três serviços Python com OTel, propagando contexto pelos metadados gRPC. O resultado é uma *flame graph* de uma requisição atravessando Gateway → Auth → Data → Transform, com o tempo de cada hop e cada query SQL. Isso responde visualmente uma pergunta que as métricas não respondem: *num pedido AGGREGATED de 900ms, quanto é SQL, quanto é conversão FHIR, quanto é serialização gRPC?* Correlacionamos trace e métrica via `exemplars` do Prometheus, que permitem pular do ponto no histograma direto para o trace daquela requisição.

**Logs: Loki + Promtail.** Log estruturado em JSON com `trace_id` em cada linha. No Grafana, clicar num span do Jaeger leva às linhas de log daquela requisição exata. Um DENY de autorização vira rastreável ponta a ponta.

Ligados na validação funcional e num cenário dedicado de baixa carga; amostrados a 1% ou desligados nas corridas de 500 e 1000 VUs, pelo motivo metodológico já explicado.

### HPA por métrica customizada (`prometheus-adapter`)

Escalar por CPU é o exemplo do enunciado. Escalar por **requisições por segundo** ou por **p95 de latência** é o que se faz de verdade, e é um argumento técnico forte.

Instalar `prometheus-adapter`, expor `transform_duration_seconds` e a taxa de RPS como *custom metrics* na API do Kubernetes, e configurar um segundo HPA para o Transform escalando por latência p95 em vez de CPU. Rodar o **mesmo cenário C com os dois HPAs** e comparar: qual reage mais rápido, qual overshoota, qual estabiliza melhor. Isso é um experimento controlado com uma variável independente, e é exatamente o tipo de "descoberta" que a rubrica recompensa.

### Chat full-duplex com `epoll` — ✅ ENTREGUE (Gabriel)

Requisito do quadro. Também o único componente que toca o coração da ementa de PSPD: comunicação interprocessos, I/O multiplexing, chamadas de sistema.

Implementado em `chat/`: servidor `epoll` *edge-triggered* single-threaded com buffer de saída por conexão e métricas Prometheus (`chat_conexoes_ativas`, `chat_mensagens_total`, `chat_bytes_enviados_total`, `chat_epoll_wait_duration_seconds`); mais duas variantes do mesmo protocolo para comparação, `select()` e thread-por-conexão; um cliente que multiplexa `stdin` e socket; e um gerador de carga de conexões.

**Resultados medidos** (10k conexões, 1% ativas — análise completa em `docs/experimento-c10k.md`):

| | memória por conexão | msgs por segundo de CPU | conexões aceitas |
|---|---|---|---|
| `epoll` | 4,2 KB | 273.238 | 10.000 |
| thread-por-conexão | 12,4 KB | 75.603 | 10.000 |
| `select()` | — | — | 1.020 (teto do `FD_SETSIZE`) |

O `epoll` mantém a mesma eficiência com mil ou dez mil conexões: a propriedade O(1) medida. O `select()` não é lento — é impossível: `fd_set` tem 1024 bits, fixados na compilação da libc.

Achado que contraria a narrativa fácil: em p95 o servidor de threads foi competitivo, porque usa 2,4 núcleos enquanto nosso `epoll` usa um. Ele gastou 2,4× mais CPU para entregar 34% menos mensagens. A comparação justa seria `epoll` com `SO_REUSEPORT`, um processo por núcleo. Registrado como limitação em vez de escondido.

**Pendente (Guilherme):** integração no cluster atrás do Gateway, exposto por WebSocket, com o contexto de autorização injetado. O servidor é autônomo; a integração é um adaptador.

---

## Arquitetura dos serviços

Contratos proto3, nomes em pt-BR, `keepCase` — casa com o loader já usado no T1. Enum compartilhado `NivelAcesso { FULL, PARTIAL, ANONYMIZED, AGGREGATED, DENY }`.

**`auth.proto` — AuthService.** `AutorizarConsulta(RequisicaoAutorizacao) → RespostaAutorizacao`. A requisição carrega `username`, `role`, `escopo`, `ids_pacientes`, `codigo_condicao`, `id_projeto`; a resposta devolve `permitido`, `nivel`, `ids_autorizados`, `motivo_negacao`. As regras consultam `user_patient_assignments` (médico e estagiário) e `projects` (pesquisador — status aprovado e data de validade vigente).

**`data.proto` — PatientDataService.** Devolve forma interna crua, nunca FHIR. `BuscarPacientes(FiltroPacientes) → ConjuntoDadosClinicos` faz o join `patients`+`encounters`+`clinical_events` sobre os ids autorizados (caminhos FULL, PARTIAL, ANONYMIZED). `AgregarCoorte(FiltroCoorte) → ResultadoAgregado` roda o SQL pesado: contagens, médias, medianas, distribuições por condição, estado e faixa etária (caminho AGGREGATED).

**`transform.proto` — DataTransformService.** `TransformarParaFHIR(RequisicaoTransformacao) → RespostaFHIR`. Recebe o `nivel` e os dados, aplica o *field-stripping* correspondente e emite um Bundle FHIR (Patient, Encounter, Condition, Observation, MedicationRequest). AGGREGATED vira um `MeasureReport`. A pseudonimização usa hash com salt, e o salt fica fora do código — comentar no relatório que ANONYMIZED sem salt secreto é reversível por força bruta sobre um espaço de CPFs pequeno.

**`chat.proto` / WebSocket — ChatService.** Full-duplex, servidor C com `epoll`.

### Orquestração no Gateway — muda em relação ao T1

Há **dependência de dados real**: o Auth precisa devolver o nível antes de o Transform poder aplicá-lo, e o Data precisa devolver linhas antes do Transform. Logo o fan-out `Promise.all` de `modulo-p/src/grpcClient.js` **não se aplica entre os estágios**. É um pipeline sequencial com ramo condicional:

1. Gateway valida o JWT localmente contra o JWKS do Keycloak (com cache de chaves) → 401 rápido, sem tocar em nenhum serviço.
2. `await Auth.AutorizarConsulta(...)`. Se `!permitido` → **403 imediato**, sem chamar Data nem Transform. Esse gate é uma economia mensurável: vale um gráfico comparando o custo de uma requisição negada contra uma permitida.
3. Ramo por nível. FULL, PARTIAL e ANONYMIZED chamam `Data.BuscarPacientes` e depois `Transform`; AGGREGATED chama `Data.AgregarCoorte` e depois `Transform`.
4. Gateway consolida e devolve o Bundle.

O `Promise.all` do T1 **ainda se aplica, mas um nível abaixo**: quando a autorização libera vários pacientes, o estágio Data faz fan-out paralelo por paciente, e só então um único Transform roda. Ou seja, *sequencial entre estágios, paralelo dentro do estágio Data*. Vale uma subseção — ecoa a descoberta de 4,36ms→2,66ms do T1, aplicada cirurgicamente onde faz sentido. Bônus metodológico: o pipeline sequencial dá latência atribuível por hop, o que é justamente o que torna a métrica "tempo de resposta por serviço" da fase (e) significativa, e o que o trace do Jaeger vai mostrar visualmente.

---

## Sprint 0 — CONCLUÍDO

O caminho crítico passava pelos `.proto`. Os quatro itens abaixo destravavam o grupo inteiro e **já estão entregues e verificados** (commit inicial em `git@github.com:PSPD-GRUPO-DGGL/pspd-ppesquisa-p2.git`).

1. ✅ **Contratos `.proto`** — `comum.proto`, `auth.proto`, `data.proto`, `transform.proto`. Compilam com `grpc_tools.protoc`. `comum.proto` foi acrescentado ao escopo original: concentra o enum `NivelAcesso` e as mensagens de domínio, evitando que os três serviços redefinissem `Paciente` cada um do seu jeito.
2. ✅ **Schema das 5 tabelas + seed sintético** — `db/`. 50k pacientes, 174k atendimentos, 1,27M eventos clínicos, carga em 27s. Determinístico via `hashtext` da chave da linha.
3. ✅ **Matriz de nível de acesso** — `docs/matriz-acesso.md`. Normativo. Inclui os 15 casos da matriz de teste, com todos os caminhos DENY.
4. ⬜ **kind de pé com pipeline "hello"** — pendente, com **Luiz**. `kind`, `kubectl`, `helm` e `k6` já estão instalados na máquina do Gabriel; falta `multipass`.

Acrescentado ao Sprint 0 e também entregue: `docs/mapeamento-fhir.md` (normativo, especifica o Data Transform Service).

### Três achados do Sprint 0 que vão para o relatório

Nenhum destes apareceria sem executar de fato. Todos são material de seção de "dificuldades e soluções".

**Seed com variância zero.** A primeira versão gerava exatamente 1 atendimento por paciente e todas as 16 mil observações com o código `HbA1c`. Causa: um `CROSS JOIN LATERAL generate_series(1, 1 + floor(random()*6))` que não referencia a linha externa. Sem correlação, o planner trata o LATERAL como subconsulta não-correlacionada e avalia `random()` **uma vez para a consulta inteira**. Correção: derivar toda a aleatoriedade de `hashtext()` sobre a chave da própria linha, o que força a correlação e torna o seed reprodutível sem `setseed`.

**Seed travado por índice ausente.** O bloco de condições rodou 3,5 minutos sem inserir uma linha, e foi abortado. Causa: um `JOIN LATERAL (... ORDER BY ... LIMIT 1)` sobre `encounters` num ponto do seed onde o índice `idx_enc_paciente` ainda não existe — os índices são criados **depois** da carga, de propósito, porque criá-los antes de um bulk insert custa caro e produz árvores piores. Resultado: seq scan de 175 mil linhas, 50 mil vezes. Correção: `DISTINCT ON`, que resolve em uma única ordenação.

**Contraste FULL × AGGREGATED medido.** `EXPLAIN ANALYZE` confirma o desenho dos índices: o caminho do médico custa **0,25 ms** (index scan puro) e o do pesquisador custa **154,6 ms** (parallel seq scan de 961k linhas, `percentile_cont` derramando 3,2 MB em sort externo no disco). Fator de ~620×. A coorte em si é resolvida por índice — o custo está na agregação, que é onde precisa estar. Este número é a premissa quantitativa da hipótese central do trabalho.

---

## Divisão de tarefas

Alocada por afinidade com o T1 e por **grau de dependência**. A rubrica premia equilíbrio visível na distribuição, e isso precisa aparecer no relatório e no vídeo.

O critério que organiza a lista: quem depende de menos gente fica com o que pode ser terminado primeiro. O chat `epoll` é a única entrega grande do projeto com **zero dependências** — não fala com Gateway, Auth, Data, banco nem Kubernetes —, então vai para quem precisa fechar sua parte cedo.

**Gabriel** (Módulo B e relatório no T1) — quatro a cinco frentes, todas independentes do resto do grupo:
1. **Base do projeto**: contratos `.proto`, schema, seed, índices, matriz de acesso, mapeamento FHIR. ✅ entregue
2. **Data Transform Service**: projeção por nível, Bundle FHIR, `MeasureReport`, pseudonimização, métricas de domínio, 52 testes. ✅ entregue
3. **Chat `epoll` + experimento C10K**: três servidores em C (`epoll` edge-triggered, thread-por-conexão, `select`), gerador de carga de conexões, medição de RSS, CPU e latência até cada um quebrar.
4. **Scripts k6 dos cenários A/B/C/D**: escritos contra os contratos; o Luiz executa quando o cluster estiver de pé.
5. **Estrutura do relatório** e todas as seções que não dependem de resultado (introdução, metodologia, arquitetura, Transform, FHIR/anonimização, chat/C10K, referências), com as tabelas de resultado como esqueleto a preencher.

**Danilo** (protos e teoria gRPC no T1) — **Keycloak** (realm como código em `keycloak/realm-hospital.json`, três roles, usuários de teste, RS256, JWKS), **Authorization Service** (regras de `docs/matriz-acesso.md` §1 sobre `user_patient_assignments` e `projects`), **Patient Data Service** (SQL e agregações) e o **experimento pgbouncer** (medir a saturação do pool, instalar o pgbouncer, medir de novo).
> Auth e Data são os dois serviços que falam SQL e leem as mesmas cinco tabelas — quem escreve as regras já tem o schema na cabeça. Contratos em `proto/auth.proto` e `proto/data.proto`. Escopo→filtro em `docs/matriz-acesso.md` §3. Consultas de referência validadas com `EXPLAIN ANALYZE`.

**Guilherme** (Gateway P no T1) — **API Gateway** (validação de JWT contra o JWKS, orquestração do pipeline sequencial, `prom-client`), **frontend** (login OIDC e tela de consulta por perfil), **validação funcional ponta a ponta** (`scripts/validacao_funcional.sh` contra as 15 linhas da matriz de teste, que é a fase *a*) e **OpenTelemetry** (propagação de contexto pelos metadados gRPC).
> Frontend e Gateway são os dois lados da mesma conversa REST — a fronteira HTTP inteira num dono só.

**Luiz** (Docker/K8s no T1) — **cluster kind** de 4 nós e **cluster kubeadm em VMs**, `kube-prometheus-stack` com Grafana provisionado, SLO e alerta, **HPA** (por CPU e customizado via `prometheus-adapter`), metrics-server, Dashboard, Jaeger e Loki, **execução das corridas de carga** e experimentos de **resiliência**, mais a **consolidação final do relatório e do vídeo**.
> `servicos/transform/Dockerfile` serve de molde: build a partir da raiz, stubs gerados no build, imagem não-root. Perfis de `requests`/`limits` já definidos neste plano.

**Transversal, de todos:** instrumentar OpenTelemetry no próprio serviço, e gravar o próprio trecho de vídeo.

Relatório e vídeo correm em paralelo desde que o pipeline local esteja de pé, não no fim.

---

## Ordem de execução

1. ✅ **Sprint 0.** Contratos, schema, seed, matriz de acesso, mapeamento FHIR — entregues por Gabriel. Falta o kind de pé (Luiz).
2. **Serviços restantes contra os stubs.** Danilo faz Keycloak + Auth + Data; Guilherme faz Gateway + frontend. O Transform já responde.
3. **Pipeline local** via docker-compose, ponta a ponta com os três perfis, os quatro níveis e os DENY. Aqui a fase (a) está cumprida. Validar com `scripts/validacao_funcional.sh` contra as 15 linhas da matriz de teste.
4. **Migrar para o kind.** Build → `kind load` → `apply`, já com `requests`/`limits` e probes desde o primeiro manifesto.
5. **Instrumentação.** `prom-client` no gateway, interceptor nos serviços Python (molde em `servicos/transform/metricas.py`), postgres_exporter, ServiceMonitors, `kube-prometheus-stack`, dashboards provisionados, SLO e alerta.
6. **Fases b → c → d.** k6 de fora, 10→1000; escala manual 1→3; HPA por CPU. Os cenários A/B/C/D já estão escritos em `k6/cenarios/`; Luiz os executa.
7. **Camada 3.** OTel + Jaeger + Loki; `prometheus-adapter` e o HPA por latência com o comparativo; pgbouncer com medição antes/depois; experimentos de resiliência.
8. ✅ **Chat epoll e experimento C10K** — entregues por Gabriel, independentes do resto. Resta a Guilherme integrá-lo atrás do Gateway.
9. **Cluster kubeadm em VMs**, validação funcional da aplicação nele.
10. **Cauda paralela.** Relatório e vídeos desde o passo 3.

---

## Riscos concretos

Estes são erros que vão acontecer, não hipóteses:

- **HPA sem `requests.cpu` reporta `<unknown>` e nunca escala.** Todo Deployment precisa de `requests.cpu`. É o erro número um.
- **metrics-server no kind falha por TLS do kubelet.** Adicionar `--kubelet-insecure-tls` e `--kubelet-preferred-address-types=InternalIP`.
- **kind não enxerga imagens locais do Docker do host.** `kind load docker-image <img>:<tag>` após cada build — substitui o `eval $(minikube docker-env)` do T1 — com `imagePullPolicy: IfNotPresent` e tags explícitas, nunca `:latest`.
- **ServiceMonitor não é raspado** se não carregar o label que o `serviceMonitorSelector` do operator espera (tipicamente `release: <nome-do-release-helm>`). Sem isso, zero métricas e horas perdidas.
- **NodePort inacessível do host no kind** sem `extraPortMappings` no config do cluster. Sem isso o k6 não alcança o gateway.
- **PVC `Pending`** se Prometheus/Grafana pedirem storage e o provisioner não estiver certo. Para a demo, `emptyDir` ou persistência desabilitada.
- **`exp` curto no JWT** derruba a carga com 401 no meio do teste de 1000 VUs. Expiração generosa nos tokens de teste, e o k6 renovando token quando necessário.
- **Scale-down do HPA demora ~5 minutos** por padrão (janela de estabilização). Ajustar `behavior.scaleDown` ou avisar na narração do vídeo.
- **`epoll` edge-triggered com socket bloqueante é um bug clássico**: é obrigatório `O_NONBLOCK` e drenar o `read()` até `EAGAIN`, senão eventos se perdem silenciosamente e o chat trava sob carga.
- **Keycloak em `start-dev` com H2** perde estado ao reiniciar o pod. Com `--import-realm` e realm commitado isso é irrelevante, mas os usuários criados na mão somem — daí a insistência em configuração como código.

---

## Documentar o caminho VMs/kubeadm

Seção "Da máquina única ao cluster real": provisionar 1 control-plane + 3 workers com multipass, IPs fixos, swap off, containerd, sysctl `br_netfilter` e `ip_forward`, `kubeadm init --pod-network-cidr`, CNI (Calico), `kubeadm join` com token. Scripts commitados e executados de fato, com a aplicação validada funcionalmente. As medições ficam no kind, e o motivo vai escrito.

Tabela de equivalência, que também explica por que o kind é um proxy honesto:

| kind | kubeadm/VM |
|---|---|
| container-nó | VM |
| kindnet | Calico/Flannel |
| `kind load docker-image` | registry privado ou `ctr images import` |
| `extraPortMappings` | MetalLB, ou NodePort + IP externo |
| bootstrap automático | `kubeadm init` + `join` manuais |

---

## Arquivos do T1 a reaproveitar

Todos em `/home/anjos/github/pspsd_ppesquisa_p1/`:

- `modulo-p/src/grpcClient.js` — padrão de `protoLoader.loadSync`, stubs criados uma vez na init, `Promise.all`. Base do orquestrador, **mas o `Promise.all` migra de entre-estágios para dentro do estágio Data**.
- `proto/produto.proto` — molde de estilo (proto3, pt-BR, `keepCase`) para os novos protos.
- `modulo-a/Dockerfile` (Python slim gerando stubs no build via `grpc_tools.protoc`) e `modulo-p/Dockerfile` (Node multi-stage).
- `k8s/p-deployment.yaml` e `k8s/p-service.yaml` — molde de Deployment+Service. Adicionar `resources` e probes; trocar a nota sobre `minikube docker-env` por `kind load docker-image`.
- `docker-compose.yml` — base do ambiente local do passo 2; acrescentar Postgres, pgbouncer e Keycloak.
- `docs/relatorio/relatorio-final.md` — o formato de relatório já validado por este mesmo professor.

---

## Verificação

**Funcional (fase a).** Com o docker-compose de pé, um script `scripts/validacao_funcional.sh` que vira anexo do relatório: obter token de médico no Keycloak, pedir o resumo clínico de um paciente vinculado, conferir que o Bundle FHIR sai com CPF e nome completo; repetir com paciente não vinculado e conferir 403 com `motivo_negacao`; token de estagiário e conferir que o nome vem só com iniciais e o CPF sumiu; token de pesquisador contra projeto aprovado (espera-se `MeasureReport` agregado, sem identificador direto) e contra projeto expirado (espera-se DENY). Validar o JSON de saída contra o schema FHIR.

**Cluster.** `kubectl get nodes` mostra 4 nós `Ready`; `kubectl get pods -o wide` mostra pods espalhados pelos 3 workers; o Dashboard abre.

**Observabilidade.** `port-forward` no Prometheus e conferir em `/targets` que todos os serviços aparecem `UP` — se um ServiceMonitor estiver sem o label do release, é aqui que aparece. Confirmar amostras em `transform_duration_seconds` e `grpc_client_duration_seconds`. No Jaeger, achar um trace de requisição AGGREGATED e conferir que os quatro spans aparecem encadeados. No Grafana, clicar num exemplar do histograma e cair no trace.

**HPA.** `kubectl get hpa -w` durante um teste k6: a coluna `TARGETS` precisa mostrar percentual, não `<unknown>` — `<unknown>` significa `requests.cpu` faltando. `kubectl get pods -w` deve mostrar réplicas nascendo.

**Chat.** ✅ Verificado. Dois clientes trocando mensagens simultaneamente na mesma conexão (full-duplex, não request/response), e o experimento de carga até 10k conexões contra as três variantes. Reproduzir com `cd chat && make todos && ./scripts/experimento_c10k.sh 8 1000 5000 10000`. Resultados em `chat/resultados/c10k.csv`, análise em `docs/experimento-c10k.md`.

**Carga.** Cada cenário roda pelo k6 no host contra `localhost:30080`, com saída simultânea para JSON em `resultados/` e para o Prometheus via remote-write. O relatório compara throughput, latência média e p95, CPU, memória e taxa de erro entre 10/50/100/500/1000 VUs, para quatro configurações: 1 réplica, 3 réplicas fixas, HPA por CPU e HPA por métrica customizada.
