# Relatório de Pesquisa: Observabilidade e Monitoramento em Clusters K8S

**Curso:** Engenharia de Software, Faculdade UnB Gama
**Disciplina:** FGA, Programação para Sistemas Paralelos e Distribuídos (T02), 2026.1
**Professor:** Fernando William Cruz
**Grupo:** DGGL (Grupo 9): Gabriel Soares dos Anjos, Danilo Carvalho Antunes, Luiz Gustavo Lopes Campos, Guilherme Brito de Souza
**Data:** 13 julho de 2026



## Introdução

Este relatório documenta o Projeto de Pesquisa 2 da disciplina PSPD: uma aplicação de microsserviços para um Hospital Universitário, expondo dados clínicos em formato HL7/FHIR sob quatro níveis de acesso (FULL, PARTIAL, ANONYMIZED, AGGREGATED), com foco em observabilidade e desempenho num cluster Kubernetes real. A aplicação, um API Gateway em Node.js, três microsserviços em Python/gRPC (Authorization, Patient Data, Data Transform) e um servidor de chat em C, foi implantada no cluster institucional da disciplina (`kiriland.unb.br`, namespace `grupo-9`), validada funcionalmente contra o banco de dados e o servidor de identidade reais fornecidos pelo professor, e submetida a uma matriz de experimentos de carga isolando o efeito de diferentes configurações de réplicas e autoscaling.

O relatório segue a estrutura pedida pela especificação: a experiência de montagem do Kubernetes (Seção 1), a metodologia de trabalho do grupo (Seção 2), o desenho experimental e os resultados de cada uma das cinco fases (Seções 3 e 4), e a conclusão com autoavaliação individual (Seção 5). As cinco fases são validação funcional, testes de carga, escalabilidade horizontal, autoscaling e observabilidade.

## Metodologia de trabalho do grupo

O grupo trabalhou majoritariamente de forma assíncrona ao longo do período, coordenando o desenvolvimento por mensagens em um grupo de WhatsApp. Encontros presenciais foram poucos, concentrados no horário logo após as aulas da disciplina, quando a agenda dos quatro integrantes permitia coincidir. A baixa frequência de reuniões presenciais se deveu principalmente à sobreposição de compromissos de cada um ao longo do semestre, não à falta de acompanhamento do projeto.

Para compensar o baixo número de encontros presenciais, o grupo se apoiou em comunicação assíncrona disciplinada: cada integrante compartilhava o planejamento do que ia implementar antes de começar e o resultado depois de concluir, o que permitiu que decisões de contrato (proto3, schema do banco, matriz de acesso) fossem tomadas cedo e resistissem a mudanças de escopo posteriores. Essa mesma disciplina de compartilhar cedo expôs um ponto de atrito real do trabalho assíncrono: em mais de um momento, dois integrantes desenvolveram manifests de Kubernetes em paralelo, sem saber que o outro fazia o mesmo, o que gerou conflitos de configuração em variáveis de ambiente, portas e nomes de Secret, reconciliados manualmente já perto da entrega. A lição prática foi que comunicação assíncrona funciona bem para dividir trabalho independente, mas exige um ponto de sincronização explícito antes de qualquer um alterar um artefato compartilhado, como os manifests do cluster. O grupo só formalizou essa regra depois de sentir o custo de não a ter.

O trabalho seguiu, ainda assim, marcos claros: definição da aplicação e dos contratos gRPC no início do projeto; implementação paralela dos quatro serviços e do frontend, cada um sob responsabilidade de um integrante; descoberta e adaptação ao ambiente real fornecido pelo professor (schema do banco em inglês, Keycloak institucional, cota do cluster) já na reta final; reconciliação dos manifests conflitantes; e, por último, o deploy no cluster `grupo-9` e a execução da matriz completa de experimentos de carga.

## 1. Experiência de Montagem do Kubernetes em Cluster

### 1.1 Cluster de Alta Fidelidade Local (Kind)
O Kind foi estruturado em arquitetura multi-node contendo 1 nó de Control Plane e 3 nós Workers. A mapeamento de portas do barramento de host foi configurado por meio da diretiva `extraPortMappings` conectada à porta local `30080` de modo que a ferramenta k6 possa se manter no host local e não roubar ciclos de processamento computacional dos containers do cluster durante as simulações, evitando contaminação de latências percentílicas.

### 1.2 Cluster de VMs de Produção Físico (Multipass / Kubeadm)
Para a validação estrutural em instâncias virtuais nativas de produção de acordo com as ementas da disciplina, desenvolveu-se o runbook IaC em `vms/provision-cluster.sh` automatizando:
- Alocação do hypervisor em jammy images.
- Ajuste dos parâmetros do subsistema de rede do Linux Kernel: `net.bridge.bridge-nf-call-iptables`.
- Setup do runtime `containerd` configurando o Systemd de forma a tratar os cgroups unificados.

## 2. Metodologia de Coleta e Fases do Projeto

### 2.0 Desenho experimental: matriz de configurações

Em vez de submeter um único arranjo à carga, a aplicação é medida sob uma matriz de configurações, isolando uma variável por experimento, de modo a evidenciar as vantagens e limites de cada arranjo. A especificação aponta que nem todo arranjo escala igualmente:

| Exp | Configuração                                                        | Variável isolada                                                                   |
| --- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| E0  | 1 réplica por serviço, sem HPA                                      | baseline de latência/throughput                                                    |
| E1  | E0 sob rampa de 10/50/100/500/1000 VUs                              | curva de saturação do baseline                                                     |
| E2  | 3 réplicas do Transform (stateless), demais com 1                   | ganho de escala em serviço compute-bound                                           |
| E3  | 3 réplicas do Data, PostgreSQL único                                | teto imposto pelo estado compartilhado                                             |
| E4  | 3 réplicas em todos os serviços                                     | ganho global e distribuição de pods entre nós                                      |
| E5  | HPA por CPU (min 1 / max 10) sob rampa                              | criação automática de pods, redistribuição, redução de latência e limite de escala |
| E6  | Colocação: um serviço por worker (anti-afinidade) versus co-locados | efeito de vizinhança/colocação                                                     |

As métricas coletadas em cada experimento (mínimo de cinco): throughput (req/s), latência média e p95/p99, utilização de CPU e de memória, taxa de erro, número de pods, número de consultas ao banco e erros gRPC. A hipótese central sob teste é o contraste entre E2 e E3: o Transform, por ser stateless e compute-bound, ganha com réplicas; o Data, limitado por uma única instância de PostgreSQL, encontra um teto de estado compartilhado que a escala horizontal por si só não remove.

### 2.1 Fase (b): Testes de Desempenho e Coleta de Métricas

A matriz E0–E4 foi executada a partir da VM da disciplina (`kiriland.unb.br`, via SSH), contra a URL pública `https://kiriland.unb.br/grupo9`, com carga mista realista: 60% médico FULL, 20% estagiário PARTIAL, 15% pesquisador AGGREGATED, 5% médico sem vínculo (DENY). Cada nível de VU (10/50/100/500/1000) foi sustentado por 60s com carga constante, entre uma reconfiguração de réplicas e a próxima, sempre com HPA desligado, exceto em E5. O gerador rodou fora do cluster, na VM da disciplina, para não competir por CPU com os pods sob teste, conforme exigido pela especificação.

**Resultado bruto por experimento e nível de VU:**

| Exp | Config. (auth/data/transform/gw) | VUs  | Throughput (rps) | Lat. média (ms) | p95 (ms)   | p99 (ms) | Erro real  | CPU total (m) | Mem total (Mi) | Pods |
| --- | -------------------------------- | ---- | ---------------- | --------------- | ---------- | -------- | ---------- | ------------- | -------------- | ---- |
| E0  | 1/1/1/1 (baseline)               | 10   | 21,95            | 249             | 1.504      | 1.605    | 0,00%      | 362           | 137            | 4    |
| E0  | 1/1/1/1                          | 50   | 33,40            | 1.243           | 2.771      | 3.387    | 0,00%      | 439           | 142            | 4    |
| E0  | 1/1/1/1                          | 100  | 34,51            | 2.580           | 4.105      | 4.717    | 0,00%      | 530           | 145            | 4    |
| E0  | 1/1/1/1                          | 500  | 35,34            | 5.673           | 16.628     | 17.937   | 0,00%      | 479           | 147            | 4    |
| E0  | 1/1/1/1                          | 1000 | 35,95            | 6.139           | 21.715     | 25.675   | **10,44%** | 532           | 147            | 4    |
| E2  | 1/1/3/1 (Transform×3)            | 10   | 21,89            | 248             | 1.516      | 1.586    | 0,00%      | 374           | 180            | 6    |
| E2  | 1/1/3/1                          | 100  | 35,07            | 2.544           | 4.167      | 4.911    | 0,00%      | 437           | 185            | 6    |
| E2  | 1/1/3/1                          | 1000 | 40,73            | 5.327           | 19.266     | 21.163   | 9,62%      | 558           | 188            | 6    |
| E3  | 1/3/1/1 (Data×3)                 | 10   | 20,99            | 268             | 1.516      | 1.580    | 0,00%      | 359           | 196            | 6    |
| E3  | 1/3/1/1                          | 100  | 33,68            | 2.652           | 4.213      | 5.106    | 0,00%      | 540           | 202            | 6    |
| E3  | 1/3/1/1                          | 1000 | 38,25            | 5.786           | 21.272     | 23.508   | 9,87%      | 488           | 207            | 6    |
| E4  | 3/3/3/3 (tudo×3)                 | 10   | 21,38            | 260             | 1.513      | 1.603    | 0,00%      | 487           | 367            | 12   |
| E4  | 3/3/3/3                          | 100  | **53,91**        | **1.575**       | **3.510**  | 4.121    | 0,00%      | 896           | 384            | 12   |
| E4  | 3/3/3/3                          | 1000 | **48,69**        | **3.387**       | **12.511** | 17.934   | **6,73%**  | 706           | 390            | 12   |

*(tabela completa, todos os 5 níveis por experimento, em `resultados/matriz-final/matriz.csv`)*

**Leitura dos dados.** O baseline (E0) satura cedo. O throughput sobe 52% de 10 para 50 VUs, mas só 6% de 50 para 1000 VUs: o sistema com 1 réplica por serviço já está no teto de capacidade a partir de 50 VUs concorrentes, e o excesso de carga vira fila (latência) em vez de trabalho útil. A 1000 VUs sustentados, 10,44% das requisições falham de verdade (5xx ou timeout; os 403 de DENY intencionais contam como sucesso, não como erro).

**Detalhe metodológico.** Os `403` do cenário DENY (5% da carga mista) são uma decisão de autorização correta, não uma falha do sistema. O script de carga foi ajustado (`http.expectedStatuses(200, 403)`) para não contaminar a métrica de erro com decisões de negócio esperadas. Sem esse ajuste, todo experimento reportaria falsamente cerca de 5% de "erro" fixo, mascarando o sinal real de saturação.

### 2.2 Fase (c): Escalabilidade Horizontal

A hipótese de partida era um contraste forte entre escalar o Transform, stateless e compute-bound, e escalar o Data, single-writer contra um PostgreSQL único. Os dados mostram um contraste mais fraco do que o previsto entre E2 e E3 isoladamente, e um achado mais importante por trás disso:

| Config. a 1000 VUs      | Throughput | Ganho vs. baseline | p95           | Erro real |
| ----------------------- | ---------- | ------------------ | ------------- | --------- |
| E0 (baseline, 1/1/1/1)  | 35,95 rps  | n/a                 | 21.715 ms     | 10,44%    |
| E2 (Transform×3)        | 40,73 rps  | +13%               | 19.266 ms     | 9,62%     |
| E3 (Data×3)             | 38,25 rps  | +6%                | 21.272 ms     | 9,87%     |
| E4 (tudo×3)             | 48,69 rps  | **+35%**           | **12.511 ms** | **6,73%** |

E2 ganha um pouco mais que E3, na direção prevista, mas nenhum dos dois isoladamente resolve o problema. Só escalar os quatro serviços juntos (E4) produz ganho substancial: 35% mais throughput, 42% menos latência de cauda, 35% menos erro real. Isso reformula a hipótese original. O gargalo do sistema não está concentrado num único serviço, nem Data nem Transform, e sim distribuído pela cadeia inteira, porque o Gateway orquestra as chamadas em pipeline sequencial (Auth, Data, Transform, cada hop um round-trip de rede). Replicar um único elo da corrente não remove a espera nos outros elos.

A evidência mais forte para essa reformulação está na coluna de CPU. Em nenhum experimento, em nenhum nível de carga, o consumo total de CPU passou de ~900m, menos de 15% da cota de `limits.cpu` (6000m) do namespace. O sistema nunca fica CPU-bound. Isso descarta a hipótese de que o estado compartilhado esgota CPU do Postgres, e aponta dois fatores limitantes reais: a latência de rede dos round-trips do pipeline sequencial, e o fato de o PostgreSQL do professor ser compartilhado entre os 10 grupos da disciplina, não exclusivo do grupo 9. Nenhum dos dois se resolve multiplicando réplicas de um serviço só.

### 2.3 Fase (d): Autoscaling (HPA)

O experimento E5 configurou os quatro HPAs por utilização de CPU (`auth` min1/max4 a 60%, `data` min1/max5 a 60%, `transform` min1/max5 a 60%, `gateway` min1/max3 a 70%) e submeteu o sistema à mesma rampa de carga usada nos demais experimentos (10→50→100→500→1000 VUs), partindo de 1 réplica por serviço.

**Criação automática de pods e redistribuição de carga.** Reconstruída a partir dos eventos do Kubernetes (`kubectl get events`), a escala aconteceu em cerca de 3 minutos, no início da rampa:

| Momento relativo   | Evento                                   | Motivo (reportado pelo HPA)  |
| ------------------ | ---------------------------------------- | ---------------------------- |
| t+0                | 4 pods (1 réplica cada)                  | baseline                     |
| t+~1min            | gateway→2, data→2                        | CPU acima do alvo            |
| t+~2min            | gateway→3, data→3, auth→2, transform→2   | CPU acima do alvo            |
| t+~3min            | data→4, auth→3                           | CPU acima do alvo            |
| t+~3min a t+~11min | **12 pods, sem novos eventos de escala** | —                            |
| fim da carga       | pods reduzidos de volta a 1 cada         | `"All metrics below target"` |

**Limites de escalabilidade.** Item explicitamente pedido pela especificação. O HPA parou em 12 réplicas, não nas 17 permitidas pelos máximos configurados. A causa não foi falta de capacidade do cluster: entre o último evento de escala (t+~3min) e o início do scale-down, o autoscaler ficou 8 minutos sem emitir um único evento de "CPU acima do alvo", mesmo com a carga simulada ainda subindo rumo a 500 e 1000 VUs. Ao reduzir, o motivo registrado foi explicitamente `"All metrics below target"`. Essa é a evidência de que 12 réplicas já bastavam para manter a CPU sob controle, coerente com o achado da Seção 2.2 de que o sistema nunca é CPU-bound. O HPA tomou a decisão correta de não escalar mais, porque a métrica que ele observa já estava satisfeita, ainda que o gargalo real de latência de rede continuasse presente.

Uma limitação de observabilidade honesta permanece: não foi possível confirmar de forma independente se houve alguma tentativa de escalar além de 12 bloqueada por falta de capacidade física do cluster, compartilhado por 10 grupos em 4 nós. O RBAC namespace-scoped do ambiente (`SA aluno-grupo-9`) impede listar `nodes`/`nodes.metrics.k8s.io` em escopo de cluster, e o histórico de eventos `FailedScheduling` já havia expirado (TTL padrão) quando a verificação foi feita. A ausência de eventos de escala continuados aponta para satisfação do alvo, não para bloqueio, mas essa limitação de RBAC é ela mesma um achado relevante sobre observabilidade em clusters multi-tenant.

**Redução de latência sob autoscaling comparada ao baseline estático.** O agregado da rampa completa (E5, todos os níveis de VU misturados ao longo do tempo) fechou com 1,19% de erro real (237 falhas em 19.981 requisições), contra 10,44% do E0 estático no mesmo nível de carga: quase 9× menos erros. A comparação não é perfeitamente equivalente, já que o E5 é uma rampa que passa a maior parte do tempo em VUs menores que 1000 e o E0 sustenta 1000 VUs os 60s inteiros, mas o contraste é consistente com o esperado: mais réplicas absorvem a mesma chegada de carga, com menos fila e menos timeout.

O próprio teste expôs o custo de esperar a reação do autoscaler. Durante a rampa, `http_req_duration` atingiu o teto de 60s do timeout do cliente k6 (`max: 60002ms`): algumas requisições travaram por até um minuto na janela em que a carga já subia mas o HPA ainda não tinha terminado de escalar. Esse número mede o custo do tempo de reação do autoscaling: entre detectar CPU alta, decidir escalar, criar o pod e esperar o *readiness probe*, existe uma janela real em que os clientes esperam.

### 2.4 Fase (e): Observabilidade

Um Prometheus próprio foi provisionado dentro do namespace `grupo-9` (`k8s/app/prometheus.yaml`), com descoberta de serviço via `kubernetes_sd_configs` restrita ao namespace. Essa escolha é compatível com o RBAC namespace-scoped do ambiente, que impede o uso do Prometheus/ServiceMonitor centralizado do professor sem o label do `serviceMonitorSelector`, nunca obtido. O footprint foi mantido pequeno de propósito (`requests: 100m/256Mi`, `limits: 300m/512Mi`) para não competir pela cota com os experimentos de escala.

Métricas coletadas (mínimo de cinco exigido pela especificação):

| Métrica                                                       | Fonte                                                        | O que mede                                                                          |
| ------------------------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `http_reqs` (throughput)                                      | `prom-client` no Gateway                                     | requisições por segundo                                                             |
| `http_req_duration`                                           | k6 (client-side) + `http_request_duration_seconds` (Gateway) | latência ponta a ponta e por rota                                                   |
| `grpc_client_duration_seconds`                                | Gateway                                                      | latência de cada hop gRPC (Auth/Data/Transform)                                     |
| `process_cpu_seconds_total` / `process_resident_memory_bytes` | todos os serviços                                            | CPU e memória por processo (sem depender de cAdvisor, que exige RBAC cluster-scope) |
| contagem de pods `Running`                                    | `kubectl get pods` amostrado a cada 10s                      | criação/remoção de réplicas sob HPA                                                 |
| `autorizacao_negada_total`                                    | Gateway                                                      | decisões DENY por motivo                                                            |
| `jwt_validacao_duration_seconds`                              | Gateway                                                      | custo da validação de assinatura via JWKS                                           |

A visualização foi feita com Grafana fora do cluster, na máquina de desenvolvimento, lendo o Prometheus do namespace via `kubectl port-forward svc/prometheus 9090`, sem custo de cota adicional. A integração com o Grafana institucional do professor (`grafana.kiriland.unb.br`) não foi confirmada até o fechamento deste relatório.

## 3. Deploy e Validação Funcional no Cluster Real (`grupo-9`)

Esta seção documenta a fase (a), validação funcional, executada não em laboratório, mas no cluster real e compartilhado da disciplina (`kiriland.unb.br`, namespace `grupo-9`), contra o banco institucional `pseudopep_g09` e o Keycloak da disciplina (realm `grupo09`). Todos os resultados abaixo foram observados no ambiente de entrega.

### 3.1 Topologia e provisionamento

As quatro imagens (`pspd-auth`, `pspd-data`, `pspd-transform`, `pspd-gateway`, tag `0.1.0`) foram publicadas em um registry público (`docker.io/sanjos3`), de onde o cluster as puxa. O namespace não recebe imagens diretamente, apenas referências; cada nó resolve o `pull` por conta própria. As credenciais do banco vivem em um único Secret `pspd-db`, injetado por `envFrom` nos serviços Auth e Data e por `secretKeyRef` (`ANON_SALT`) no Transform. Nenhuma credencial trafega em manifesto versionado. Após `kubectl apply`, os quatro Deployments estabilizaram em `Running 1/1`.

O consumo sob o cluster ocioso ficou muito abaixo do teto do `ResourceQuota`, deixando folga deliberada para a fase de escala horizontal:

| Recurso           | Em uso | Teto (cota) |
| ----------------- | ------ | ----------- |
| `requests.cpu`    | 500m   | 3           |
| `limits.cpu`      | 1400m  | 6           |
| `requests.memory` | 320Mi  | 4Gi         |
| `limits.memory`   | 640Mi  | 7Gi         |

Os quatro HPAs (Auth/Data/Transform `min 1`, `max 4–5`; Gateway `min 1`, `max 3`) já leem CPU via metrics-server. Quatro ServiceMonitors também foram provisionados, mas o caminho de observabilidade efetivamente usado nas fases (b) a (e) foi um Prometheus próprio no namespace, ver Seção 2.4.

### 3.2 Autenticação e autorização

O Gateway valida o token offline, verificando a assinatura RS256 contra o JWKS do realm (`/protocol/openid-connect/certs`), sem round-trip por requisição ao Keycloak. Essa decisão evita que o servidor de identidade vire gargalo nas corridas de carga. O `client_id` correto da aplicação é `pseudopep-frontend`, um client público cujo token carrega `preferred_username` e `realm_access.roles` (`MEDICO`, `ESTAGIARIO`, `PESQUISADOR`). O perfil é extraído dessas roles, com o prefixo do username (`med.`/`est.`/`pes.`) como caminho de defesa.

Um achado de configuração vale registro: ao depurar com o client interno `admin-cli`, o mesmo usuário recebe um token sem claims de identidade, e o `/userinfo` não devolve roles, o que sugeriria, de forma incorreta, ser necessário consultar `/userinfo` a cada requisição. O conteúdo do token depende do client OIDC utilizado. Com o client da aplicação, o token é autocontido e a validação permanece stateless.

A decisão de acesso não é feita apenas pela role: o Authorization Service cruza o usuário com os vínculos ativos no banco (`user_patient_assignments`), de modo que um médico sem vínculo com um paciente é negado.

### 3.3 Matriz de validação dos quatro níveis de acesso

Requisições reais ao Gateway deployado, com tokens obtidos por password grant no client `pseudopep-frontend`:

| Nível      | Usuário        | Requisição                                                          | Resultado observado                        |
| ---------- | -------------- | ------------------------------------------------------------------- | ------------------------------------------- |
| FULL       | `med.cardoso`  | `GET /api/pacientes/P090000002/resumo-clinico`                      | `200`, Bundle FHIR (`collection`), 4 entries |
| DENY       | `med.cardoso`  | `GET /api/pacientes/P090000001/resumo-clinico`                      | `403`, motivo `sem_vinculo_ativo`           |
| PARTIAL    | `est.ferreira` | `GET /api/pacientes/P090000030/resumo-clinico`                      | `200`, Bundle FHIR, 5 entries               |
| AGGREGATED | `pes.mendes`   | `GET /api/coortes/estatisticas?projeto=PRJ01_G09&condicao=DIABETES` | `200`, `MeasureReport` FHIR                 |

A negação por falta de vínculo, linha DENY, confirma que a autorização não se resume à posse de um perfil válido: o mesmo médico que obtém acesso FULL a um paciente é barrado em outro com o qual não tem vínculo ativo. As saídas em recursos FHIR distintos, Bundle para dados individuais e MeasureReport para coorte agregada, confirmam o mapeamento HL7/FHIR do Transform sob os níveis de acesso.

## 4. Ponto extra: funcionalidades além do solicitado

- **Chat full-duplex em C/epoll com experimento C10K** (Seção "O contraste que sustenta o experimento" do README, `docs/experimento-c10k.md`): comparação medida entre `epoll` edge-triggered, `select()` e thread-por-conexão sob 10 mil conexões, 1% ativas. Não fazia parte do escopo pedido pela especificação.
- **Prometheus próprio provisionado no namespace**, compatível com RBAC namespace-scoped, sem depender de infraestrutura centralizada de terceiros. Ver Seção 2.4.
- **Reconstrução de linha do tempo de autoscaling a partir de eventos do Kubernetes** (Seção 2.3), evidenciando o motivo do platô de réplicas, não só o resultado agregado.

## 5. Conclusão

Este projeto colocou o grupo diante de um tipo de dificuldade que o desenvolvimento local não expõe: a diferença entre um sistema distribuído que "funciona no meu computador" e um que funciona quando a rede, o banco de dados e o servidor de identidade pertencem a outra parte, compartilhada por dez grupos ao mesmo tempo. Boa parte do esforço da reta final não foi escrever código novo, mas descobrir coisas que nenhuma documentação prévia explicava: qual era o `client_id` correto do Keycloak institucional (o time chegou a uma conclusão errada sobre o motivo de o token não trazer papéis de usuário, até isolar a variável certa e descobrir que era o client testado, não uma limitação do Keycloak), como reconciliar manifests de Kubernetes escritos em paralelo por integrantes diferentes sem que um sobrescrevesse o trabalho do outro, e como operar dentro de um RBAC restrito a um único namespace, que impede até inspecionar a capacidade dos nós do cluster.

Do ponto de vista técnico, o resultado mais valioso do projeto não foi confirmar a hipótese inicial, mas ser corrigido por ela. A expectativa de que escalar o serviço de dados, contra um PostgreSQL único, ajudaria pouco, e escalar o serviço de transformação, sem estado, ajudaria muito, só se confirmou parcialmente: os dois, isolados, ajudaram pouco, e a métrica de CPU nunca chegou perto de saturar em experimento nenhum. Isso obrigou o grupo a revisar a explicação em cima dos dados, não da intuição. O gargalo real estava na cadeia de chamadas sequenciais entre os serviços e possivelmente na natureza compartilhada do banco de dados, não em um único componente "culpado". A implementação desse sistema mostrou ao grupo como estimativas prévias podem se revelar imprecisas diante dos resultados reais.

A organização do grupo, majoritariamente assíncrona, permitiu avançar em paralelo em quatro frentes de implementação. As poucas reuniões presenciais aconteceram antes de iniciar a implementação do projeto, focadas mais em planejamento. A dificuldade em encontrar horários para reuniões síncronas cobrou seu preço na integração final: decisões tomadas isoladamente (nomes de variáveis, portas, convenções de manifest) só se revelaram incompatíveis no momento de juntar tudo, o que exigiu uma reconciliação manual sob pressão de prazo.

### Comentários pessoais e autoavaliação


**Gabriel Soares dos Anjos**

> Na base do projeto, fiquei responsável pelos contratos gRPC, pelo schema e seed do banco, pela matriz de níveis de acesso e pelo mapeamento para HL7/FHIR: decisões de que o resto do grupo dependeu para implementar seus serviços. Tratei isso como prioridade, pois antes do professor disponibilizar o cluster, essa implementação era a base do projeto. Implementei o Data Transform Service (com testes), o servidor de chat em C com `epoll` e o experimento C10K comparando `epoll`, `select()` e thread-por-conexão, e escrevi os cenários de carga em k6.
>
> Na reta final, quando ficou claro que o ambiente real do professor (banco, Keycloak, cluster) trazia detalhes que nenhuma especificação prévia cobria, reescrevi o API Gateway e o frontend para bater com os contratos reais dos serviços. O que existia antes tinha sido escrito contra uma API imaginada, que não correspondia ao que os outros serviços realmente expunham. Fiz o deploy da aplicação no cluster, montei a observabilidade (Prometheus próprio, dentro das restrições de RBAC do ambiente) e executei a matriz completa de experimentos de carga (E0 a E5) que sustenta os resultados deste relatório.
>
> O maior aprendizado técnico foi perceber a diferença entre uma hipótese plausível e uma hipótese medida. Com ajuda de Inteligência Artificial no planejamento, eu esperava que o gargalo estivesse concentrado num serviço; os dados mostraram um quadro mais interessante e mais correto, com a CPU nunca saturando e o problema real na cadeia de chamadas entre serviços e possivelmente no banco compartilhado entre todos os grupos da disciplina. Foi interessante pensar sobre a escalabilidade de um sistema e sobre o processo de pressionar o sistema para capturar medidas.
>
> Autoavaliação: 10.

**Danilo Carvalho Antunes**
> [preencher]

**Luiz Gustavo Lopes Campos**
> [preencher]

**Guilherme Brito de Souza**
> [preencher]

## 6. Referências

1. Arundel, J. e Domingus, J. *Cloud Native DevOps with Kubernetes: Building, Deploying and Scaling Modern Applications in the Cloud*. O'Reilly, 2019. Capítulos 15 e 16, referência normativa da especificação.
2. HL7 FHIR R4: https://www.hl7.org/fhir/
3. Kubernetes: https://kubernetes.io
4. Prometheus: https://prometheus.io/
5. Grafana: https://grafana.com/
6. k6 (Grafana Labs): https://k6.io/
7. Documentação OpenID Connect / OAuth 2.0: https://oauth.net/2/. Keycloak: https://www.keycloak.org/
8. `docs/mapeamento-fhir.md`, `docs/matriz-acesso.md`, `docs/experimento-c10k.md`: documentação normativa produzida pelo próprio grupo, referenciada ao longo deste relatório. `docs/ambiente-real.md` também documenta o ambiente, mas é propositalmente não versionado (`.gitignore`) por conter coordenadas de acesso ao cluster e ao banco do grupo; não estará disponível a quem clonar o repositório.