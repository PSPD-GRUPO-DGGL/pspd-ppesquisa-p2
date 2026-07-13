# Relatório de Pesquisa: Observabilidade e Monitoramento em Clusters K8S

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

Em vez de submeter um único arranjo à carga, a aplicação é medida sob uma matriz de configurações, isolando uma variável por experimento, de modo a evidenciar as vantagens e limites de cada arranjo — como aponta a especificação, nem todo arranjo escala igualmente:

| Exp | Configuração | Variável isolada |
|---|---|---|
| E0 | 1 réplica por serviço, sem HPA | baseline de latência/throughput |
| E1 | E0 sob rampa de 10/50/100/500/1000 VUs | curva de saturação do baseline |
| E2 | 3 réplicas do Transform (stateless), demais com 1 | ganho de escala em serviço compute-bound |
| E3 | 3 réplicas do Data, PostgreSQL único | teto imposto pelo estado compartilhado |
| E4 | 3 réplicas em todos os serviços | ganho global e distribuição de pods entre nós |
| E5 | HPA por CPU (min 1 / max 10) sob rampa | criação automática de pods, redistribuição, redução de latência e limite de escala |
| E6 | Colocação: um serviço por worker (anti-afinidade) versus co-locados | efeito de vizinhança/colocação |

As métricas coletadas em cada experimento (mínimo de cinco): throughput (req/s), latência média e p95/p99, utilização de CPU e de memória, taxa de erro, número de pods, número de consultas ao banco e erros gRPC. A hipótese central sob teste é o contraste entre E2 e E3: o Transform, por ser stateless e compute-bound, ganha com réplicas; o Data, limitado por uma única instância de PostgreSQL, encontra um teto de estado compartilhado que a escala horizontal por si só não remove.

### 2.1 Fase (b): Testes de Desempenho e Coleta de Métricas
[Preencher com as tabelas comparativas das corridas k6 (E0–E6) após execução no cluster]

### 2.2 Fase (c) / (d): Resiliência e Autoscaling Dinâmico por CPU e Métricas Customizadas
O comportamento do Horizontal Pod Autoscaler (HPA) foi testado sob duas abordagens complementares:
1. **HPA por CPU:** Escalonamento horizontal acionado ao atingir média de concorrência computacional de target especificado em \( 60\% \).
2. **HPA por Métricas Customizadas (Request Rate):** Configuração de escalonamento baseado em requisições através do `prometheus-adapter` e endpoints do APIService, mapeado em `k8s/app/hpa-custom-metric.yaml`.

## 3. Deploy e Validação Funcional no Cluster Real (`grupo-9`)

Esta seção documenta a fase (a) — validação funcional — executada não em laboratório, mas no cluster real e compartilhado da disciplina (`kiriland.unb.br`, namespace `grupo-9`), contra o banco institucional `pseudopep_g09` e o Keycloak da disciplina (realm `grupo09`). Todos os resultados abaixo foram observados no ambiente de entrega.

### 3.1 Topologia e provisionamento

As quatro imagens (`pspd-auth`, `pspd-data`, `pspd-transform`, `pspd-gateway`, tag `0.1.0`) foram publicadas em um registry público (`docker.io/sanjos3`), de onde o cluster as puxa — o namespace não recebe imagens diretamente, apenas referências, e cada nó resolve o `pull` por conta própria. As credenciais do banco vivem em um único Secret `pspd-db`, injetado por `envFrom` nos serviços Auth e Data e por `secretKeyRef` (`ANON_SALT`) no Transform; nenhuma credencial trafega em manifesto versionado. Após `kubectl apply`, os quatro Deployments estabilizaram em `Running 1/1`.

O consumo sob o cluster ocioso ficou muito abaixo do teto do `ResourceQuota`, deixando folga deliberada para a fase de escala horizontal:

| Recurso | Em uso | Teto (cota) |
|---|---|---|
| `requests.cpu` | 500m | 3 |
| `limits.cpu` | 1400m | 6 |
| `requests.memory` | 320Mi | 4Gi |
| `limits.memory` | 640Mi | 7Gi |

Os quatro HPAs (Auth/Data/Transform `min 1`, `max 4–5`; Gateway `min 1`, `max 3`) já leem CPU via metrics-server, e os quatro ServiceMonitors estão provisionados para exposição das métricas — base para as fases (b)–(e).

### 3.2 Autenticação e autorização

O Gateway valida o token **offline**, verificando a assinatura RS256 contra o JWKS do realm (`/protocol/openid-connect/certs`), sem round-trip por requisição ao Keycloak — decisão relevante para não introduzir o servidor de identidade como gargalo nas corridas de carga. O `client_id` correto da aplicação é `pseudopep-frontend`, um client público cujo token carrega `preferred_username` e `realm_access.roles` (`MEDICO`, `ESTAGIARIO`, `PESQUISADOR`); o perfil é extraído dessas roles, com o prefixo do username (`med.`/`est.`/`pes.`) como caminho de defesa.

Registra-se aqui um achado de configuração: ao depurar com o client interno `admin-cli`, o mesmo usuário recebe um token sem claims de identidade e o `/userinfo` não devolve roles — o que sugeriria, incorretamente, ser necessário consultar `/userinfo` a cada requisição. Confirmou-se que o conteúdo do token depende do client OIDC utilizado: com o client da aplicação, o token é autocontido e a validação permanece stateless.

A decisão de acesso não é feita apenas pela role: o Authorization Service cruza o usuário com os vínculos ativos no banco (`user_patient_assignments`), de modo que um médico sem vínculo com um paciente é negado.

### 3.3 Matriz de validação dos quatro níveis de acesso

Requisições reais ao Gateway deployado, com tokens obtidos por password grant no client `pseudopep-frontend`:

| Nível | Usuário | Requisição | Resultado observado |
|---|---|---|---|
| FULL | `med.cardoso` | `GET /api/pacientes/P090000002/resumo-clinico` | `200` — Bundle FHIR (`collection`), 4 entries |
| DENY | `med.cardoso` | `GET /api/pacientes/P090000001/resumo-clinico` | `403` — motivo `sem_vinculo_ativo` |
| PARTIAL | `est.ferreira` | `GET /api/pacientes/P090000030/resumo-clinico` | `200` — Bundle FHIR, 5 entries |
| AGGREGATED | `pes.mendes` | `GET /api/coortes/estatisticas?projeto=PRJ01_G09&condicao=DIABETES` | `200` — `MeasureReport` FHIR |

A negação por falta de vínculo (linha DENY) confirma que a autorização não se resume à posse de um perfil válido: o mesmo médico que obtém acesso FULL a um paciente é barrado em outro com o qual não tem vínculo ativo. As saídas em recursos FHIR distintos (Bundle para dados individuais, MeasureReport para coorte agregada) confirmam o mapeamento HL7/FHIR do Transform sob os níveis de acesso.

...