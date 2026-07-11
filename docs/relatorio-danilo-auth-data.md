# Relatório técnico — Auth Service e Patient Data Service

Responsável: Danilo Carvalho Antunes
Escopo: introspecção do banco institucional, Authorization Service, Patient Data Service, métricas e validação gRPC antes do Gateway.

## 1. Objetivo

A parte do Danilo fecha o caminho de autorização e acesso aos dados clínicos:

```text
Gateway -> Auth Service -> Patient Data Service -> Data Transform Service
```

O Gateway ainda será responsável por validar o JWT do Keycloak institucional e extrair `username` e `role`. O Auth Service recebe esses campos já validados e decide o nível de acesso. O Patient Data Service consulta o Postgres institucional e devolve dados crus, sem anonimizar e sem montar FHIR. A anonimização e a transformação HL7/FHIR ficam no Transform Service.

## 2. Banco institucional

Ambiente validado:

| Item | Valor |
|---|---|
| Banco | `pseudopep_g09` |
| Host via túnel SSH | `127.0.0.1:15432` apontando para `192.168.122.1:5432` |
| Usuário | `grupo09_user` |
| Fonte de introspecção | `scripts/introspect_db.sql` |
| Evidência salva | `resultados/introspect_pseudopep_g09_v2.txt` |

O banco real tem as cinco tabelas previstas pelo enunciado, mas com nomes de colunas em inglês. Isso exigiu adaptar as queries dos serviços em vez de usar diretamente os nomes do seed local.

### 2.1 Cardinalidades

| Tabela | Linhas |
|---|---:|
| `patients` | 150000 |
| `encounters` | 374790 |
| `clinical_events` | 1405274 |
| `user_patient_assignments` | 187792 |
| `projects` | 5 |

### 2.2 Schema real usado

`patients`:

| Coluna | Tipo | Uso no serviço |
|---|---|---|
| `patient_id` | varchar(20) | `Paciente.id_paciente` |
| `full_name` | varchar(120) | `Paciente.nome` |
| `birth_date` | date | `Paciente.data_nascimento` |
| `gender` | varchar(20) | `Paciente.genero` |
| `city` | varchar(80) | `Paciente.cidade` |
| `state` | char(2) | `Paciente.estado` |
| `cpf` | varchar(14) | `Paciente.cpf` |
| `cns` | varchar(20) | `Paciente.cns` |

`encounters`:

| Coluna | Tipo | Uso no serviço |
|---|---|---|
| `encounter_id` | varchar(20) | `Atendimento.id_atendimento` |
| `patient_id` | varchar(20) | `Atendimento.id_paciente` |
| `start_date` | timestamp | `Atendimento.data_inicio` |
| `end_date` | timestamp | `Atendimento.data_fim` |
| `encounter_type` | varchar(40) | `Atendimento.tipo_atendimento` |
| `department` | varchar(80) | `Atendimento.setor` |

`clinical_events`:

| Coluna | Tipo | Uso no serviço |
|---|---|---|
| `event_id` | varchar(20) | `EventoClinico.id_evento` |
| `patient_id` | varchar(20) | `EventoClinico.id_paciente` |
| `encounter_id` | varchar(20) | `EventoClinico.id_atendimento` |
| `event_type` | varchar(30) | mapeado para `Condicao`, `Observacao`, `Medicacao` |
| `code` | varchar(40) | `EventoClinico.codigo_tipo_evento` |
| `description` | varchar(200) | `EventoClinico.descricao` |
| `value` | varchar(80) | convertido para número quando aplicável |
| `unit` | varchar(40) | `EventoClinico.unidade` |
| `event_date` | timestamp | `EventoClinico.data_evento` |

`user_patient_assignments`:

| Coluna | Tipo | Uso no serviço |
|---|---|---|
| `assignment_id` | varchar(20) | identificador interno |
| `username` | varchar(80) | usuário médico/estagiário |
| `patient_id` | varchar(20) | paciente vinculado |
| `assignment_type` | varchar(20) | `ATTENDING` ou `TRAINEE` |
| `supervisor_username` | varchar(80) | supervisor do estagiário |
| `active` | boolean | vínculo ativo |

`projects`:

| Coluna | Tipo | Uso no serviço |
|---|---|---|
| `project_id` | varchar(20) | projeto informado pelo pesquisador |
| `title` | varchar(200) | título do projeto |
| `researcher_username` | varchar(80) | dono do projeto |
| `target_condition_code` | varchar(40) | condição autorizada |
| `status` | varchar(40) | `APPROVED`, `PENDING`, `EXPIRED`, etc. |
| `valid_until` | date | validade do projeto |

### 2.3 Índices observados

Índices relevantes encontrados:

- `patients_pkey` em `patients(patient_id)`.
- `idx_encounters_patient` em `encounters(patient_id)`.
- `idx_events_patient` em `clinical_events(patient_id)`.
- `idx_events_patient_type` em `clinical_events(patient_id, event_type)`.
- `idx_events_type_code` em `clinical_events(event_type, code)`.
- `idx_assign_user_patient` em `user_patient_assignments(username, patient_id)`.
- `idx_assign_username` em `user_patient_assignments(username)`.
- `idx_projects_condition` em `projects(target_condition_code)`.
- `idx_projects_researcher` em `projects(researcher_username)`.

Esses índices sustentam os caminhos principais: consulta por paciente, vínculos por usuário, coorte por condição e projetos por pesquisador.

## 3. Adaptação em relação ao schema local

O schema local do repositório usava nomes em português, por exemplo `id_paciente`, `nome`, `data_nascimento`, `tipo_evento` e `codigo_tipo_evento`. O banco institucional usa `patient_id`, `full_name`, `birth_date`, `event_type` e `code`.

A solução foi manter os contratos gRPC em português e fazer alias nas queries SQL:

```sql
SELECT patient_id AS id_paciente,
       full_name AS nome,
       birth_date::text AS data_nascimento
FROM patients
```

Também foi necessário mapear os tipos de evento:

| Banco institucional | Contrato interno |
|---|---|
| `CONDITION` | `Condicao` |
| `OBSERVATION` | `Observacao` |
| `MEDICATION` | `Medicacao` |

O campo `clinical_events.value` é texto no banco real. O Data Service extrai o número quando existe, trocando vírgula por ponto quando necessário.

## 4. Authorization Service

Arquivos principais:

- `servicos/auth/server.py`
- `servicos/auth/repositorio.py`
- `servicos/auth/regras.py`
- `proto/auth.proto`

Portas:

| Porta | Uso |
|---|---|
| `50051` | gRPC |
| `8000` | `/metrics` em container |

No smoke local, a porta de métricas foi deslocada para `18051`.

### 4.1 Regras implementadas

| Perfil | Regra SQL | Resultado |
|---|---|---|
| MEDICO | `assignment_type = 'ATTENDING'` e `active is true` | `ALLOW + FULL` |
| ESTAGIARIO | `assignment_type = 'TRAINEE'`, `active is true` e `supervisor_username is not null` | `ALLOW + PARTIAL` |
| PESQUISADOR | projeto do usuário, `status = 'APPROVED'`, `valid_until >= current_date`, condição compatível | `ALLOW + AGGREGATED` ou `ALLOW + ANONYMIZED` |

Motivos de negação implementados:

- `username_ausente`
- `sem_vinculo_ativo`
- `sem_supervisao_ativa`
- `escopo_invalido`
- `projeto_inexistente`
- `projeto_de_outro_pesquisador`
- `projeto_expirado`
- `projeto_nao_aprovado`
- `condicao_fora_do_projeto`
- `role_desconhecida`

### 4.2 Métricas do Auth

| Métrica | Tipo | Labels |
|---|---|---|
| `auth_decisoes_total` | counter | `decisao`, `nivel`, `role`, `motivo` |
| `auth_db_query_duration_seconds` | histogram | `consulta` |
| `grpc_server_handled_total` | counter | `rpc`, `code` |
| `grpc_server_handling_seconds` | histogram | `rpc` |

## 5. Patient Data Service

Arquivos principais:

- `servicos/data/server.py`
- `servicos/data/repositorio.py`
- `servicos/data/conversao.py`
- `proto/data.proto`

Portas:

| Porta | Uso |
|---|---|
| `50052` | gRPC |
| `8000` | `/metrics` em container |

No smoke local, a porta de métricas foi deslocada para `18052`.

### 5.1 RPCs

| RPC | Uso |
|---|---|
| `BuscarPacientes(FiltroPacientes)` | dados crus por lista de pacientes autorizados |
| `BuscarCoorte(FiltroCoorte)` | dados crus da coorte para o fluxo `ANONYMIZED` |
| `AgregarCoorte(FiltroCoorte)` | estatísticas agregadas para o fluxo `AGGREGATED` |
| `ListarProjetos(FiltroPesquisador)` | lista de projetos do pesquisador |

`BuscarCoorte` foi acrescentado ao contrato porque o contrato original só tinha `AgregarCoorte`; sem esse RPC, o caminho `ExamesCoorte -> ANONYMIZED` não conseguiria buscar linhas individuais da coorte antes da anonimização.

### 5.2 Métricas do Data

| Métrica | Tipo | Labels |
|---|---|---|
| `data_queries_total` | counter | `tipo` |
| `data_query_duration_seconds` | histogram | `tipo` |
| `data_db_pool_em_uso` | gauge | - |
| `data_linhas_retornadas` | histogram | `tipo` |
| `grpc_server_handled_total` | counter | `rpc`, `code` |
| `grpc_server_handling_seconds` | histogram | `rpc` |

## 6. Contrato para o Gateway

Endereços internos esperados no cluster:

| Serviço | DNS/porta |
|---|---|
| Auth | `auth-service:50051` |
| Data | `data-service:50052` |
| Transform | `transform-service:50053` |

O Gateway deve validar o JWT do Keycloak institucional e extrair:

- `username`
- `role`: `MEDICO`, `ESTAGIARIO` ou `PESQUISADOR`

### 6.1 Pipeline por escopo

FULL/PARTIAL:

```text
Gateway -> Auth.AutorizarConsulta
se permitido:
  Data.BuscarPacientes(ids_autorizados, incluir_atendimentos, incluir_eventos, tipo_evento, limite)
  Transform.TransformarParaFHIR(nivel=FULL ou PARTIAL, dados=...)
senão:
  HTTP 403
```

AGGREGATED:

```text
Gateway -> Auth.AutorizarConsulta(escopo=EstatisticasCoorte ou ResumoCoorte)
se permitido:
  Data.AgregarCoorte(codigo_condicao)
  Transform.TransformarParaFHIR(nivel=AGGREGATED, agregado=...)
senão:
  HTTP 403
```

ANONYMIZED:

```text
Gateway -> Auth.AutorizarConsulta(escopo=ExamesCoorte)
se permitido:
  Data.BuscarCoorte(codigo_condicao, limite_pacientes)
  Transform.TransformarParaFHIR(nivel=ANONYMIZED, dados=...)
senão:
  HTTP 403
```

DENY:

```text
Gateway -> Auth.AutorizarConsulta
se permitido=false:
  responder HTTP 403 com motivo_negacao
  não chamar Data nem Transform
```

## 7. Contrato para Kubernetes

Arquivos criados:

- `servicos/auth/Dockerfile`
- `servicos/data/Dockerfile`
- `k8s/app/auth-data.yaml`
- `k8s/app/secret-db.example.yaml`

Variáveis obrigatórias:

| Variável | Origem esperada |
|---|---|
| `DB_HOST` | `Secret`/ConfigMap |
| `DB_PORT` | `Secret`/ConfigMap |
| `DB_NAME` | `Secret`/ConfigMap |
| `DB_USER` | `Secret` |
| `DB_PASSWORD` | `Secret` |
| `ANON_SALT` | `Secret`, usado pelo Transform |

Recursos definidos inicialmente:

| Serviço | requests | limits |
|---|---|---|
| Auth | `100m / 64Mi` | `250m / 128Mi` |
| Data | `100m / 64Mi` | `300m / 128Mi` |

## 8. Validações executadas

### 8.1 Testes unitários

Comando:

```bash
./scripts/test_python_services.sh
```

Resultado:

```text
Auth tests:      9 passed
Data tests:      4 passed
Transform tests: 52 passed
```

### 8.2 Smoke Auth/Data contra o banco institucional

Comando:

```bash
./scripts/smoke_auth_data.sh
```

Resultado observado:

```text
== smoke Auth ==
[OK] medico vinculado: permitido=True nivel=FULL motivo=
[OK] medico sem vinculo: permitido=False nivel=DENY motivo=sem_vinculo_ativo
[OK] pesquisador agregado: permitido=True nivel=AGGREGATED motivo=

== smoke Data ==
[BuscarPacientes] pacientes=1 atendimentos=1 eventos=4
[BuscarCoorte] pacientes=5 eventos=29
[AgregarCoorte] total=30231 sexo=2 exames=7

== metrics Auth ==
auth /metrics OK
== metrics Data ==
data /metrics OK
OK
```

Casos descobertos automaticamente no banco:

| Caso | Valor |
|---|---|
| Médico | `med.almeida` |
| Paciente autorizado | `P090000001` |
| Paciente negado | `P090000002` |
| Pesquisador | `pes.araujo` |
| Projeto | `PRJ02_G09` |
| Condição | `HYPERTENSION` |

### 8.3 Smoke gRPC ponta a ponta

Comando:

```bash
export ANON_SALT=smoke-local-nao-usar-em-producao
./scripts/smoke_pipeline_grpc.sh
```

Resultado observado:

```text
== pipeline Auth -> Data -> Transform ==
[OK] FULL medico: resourceType=Bundle recursos=6 nivel=FULL
[OK] DENY medico: motivo=sem_vinculo_ativo
[OK] AGGREGATED pesquisador: resourceType=MeasureReport recursos=1 nivel=AGGREGATED
[OK] ANONYMIZED pesquisador: resourceType=Bundle recursos=51 nivel=ANONYMIZED
OK
== metrics Transform ==
transform /metrics OK
OK
```

Esse smoke prova que Auth, Data e Transform já funcionam juntos antes da entrada do Gateway.

## 9. Estado final da parte do Danilo

Concluído:

- introspecção do banco institucional;
- adaptação ao schema real;
- Auth Service real;
- Patient Data Service real;
- métricas Prometheus em Auth/Data;
- Dockerfiles de Auth/Data;
- manifests base de Auth/Data;
- smoke Auth/Data contra banco real;
- smoke gRPC `Auth -> Data -> Transform` contra banco real.

Ainda depende de outros integrantes:

- Gateway validar JWT do Keycloak e chamar os RPCs;
- Frontend autenticar no Keycloak institucional;
- deploy final no namespace `grupo-9`;
- validação funcional HTTP dos 15 casos;
- testes k6 contra `https://kiriland.unb.br/grupo9`;
- experimento pgbouncer, se houver tempo após o caminho obrigatório.
