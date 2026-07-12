# Plano de implementação — Danilo

Este documento é o roteiro da parte do Danilo Carvalho Antunes depois das novas orientações do professor sobre o cluster K8S. As orientações do cluster, o kubeconfig do grupo 09 e a errata do Keycloak prevalecem sobre decisões antigas do repositório.

## 1. Escopo da entrega

Danilo fica responsável pelo caminho de dados e autorização:

- Introspectar o banco institucional `pseudopep_g09`.
- Implementar `servicos/auth` usando `proto/auth.proto`.
- Implementar `servicos/data` usando `proto/data.proto`.
- Expor `/metrics` nos dois serviços.
- Preparar configuração segura de conexão com banco para os manifests finais.
- Apoiar Guilherme/Luiz na validação ponta a ponta.
- Fazer o experimento pgbouncer somente depois do caminho real estar funcionando.

Danilo **não** precisa criar um Keycloak local como entrega final. O Keycloak final é institucional:

```text
https://kiriland.unb.br/keycloak/realms/grupo09
```

O Gateway valida o JWT, extrai `username` e `role`, e chama o Auth Service. O Auth Service não valida assinatura JWT diretamente.

## 2. Ordem obrigatória

### 2.1 Congelar o alvo final

Valores que todos os serviços devem assumir na versão final:

| Item | Valor |
|---|---|
| Namespace K8S | `grupo-9` |
| URL pública | `https://kiriland.unb.br/grupo9` |
| Banco | `pseudopep_g09` |
| Realm Keycloak | `grupo09` |
| Gateway final | REST público, chamando gRPC interno |
| Auth/Data/Transform | gRPC interno + `/metrics` HTTP |

Segredos ficam fora do git. No repositório, usar apenas nomes de variáveis:

```text
DB_HOST
DB_PORT
DB_NAME
DB_USER
DB_PASSWORD
ANON_SALT
```

### 2.2 Introspectar o banco institucional

Objetivo: descobrir se o banco do professor segue exatamente o schema local em `db/schema/01_schema.sql`.

Comandos de referência, usando a VM da disciplina e preenchendo a senha fora do histórico quando possível:

```bash
ssh -p 10200 <matricula>@kiriland.unb.br
psql -h 192.168.122.1 -U grupo09_user -d pseudopep_g09
```

Dentro do `psql`:

```sql
\dt
\d patients
\d encounters
\d clinical_events
\d user_patient_assignments
\d projects
select count(*) from patients;
select count(*) from encounters;
select count(*) from clinical_events;
select count(*) from user_patient_assignments;
select count(*) from projects;
select * from patients limit 5;
select * from user_patient_assignments limit 10;
select * from projects limit 10;
```

Registrar em `docs/relatorio-final.md`:

- nomes reais das tabelas e colunas;
- diferenças em relação ao schema local;
- cardinalidade aproximada das tabelas;
- usuários/projetos que permitem montar os 15 casos da matriz;
- índices existentes ou ausentes que impactam carga.

Se o schema institucional divergir do local, adaptar o SQL dos serviços ao banco real. O schema local continua útil para testes unitários e desenvolvimento offline.

### 2.3 Implementar Auth Service

Fonte de verdade:

- `proto/auth.proto`
- `docs/matriz-acesso.md`
- banco institucional introspectado

Responsabilidade:

- receber `username`, `role`, `escopo`, `ids_pacientes`, `codigo_condicao` e `id_projeto`;
- devolver `permitido`, `nivel`, `ids_autorizados` e `motivo_negacao`;
- nunca devolver dado clínico;
- expor métricas.

Regras mínimas:

| Perfil | Regra | Resultado |
|---|---|---|
| MEDICO | vínculo ativo em `user_patient_assignments` como médico | `ALLOW + FULL` |
| ESTAGIARIO | vínculo ativo como estagiário supervisionado | `ALLOW + PARTIAL` |
| PESQUISADOR | projeto do usuário, aprovado, vigente e da condição pedida | `ALLOW + AGGREGATED` ou `ALLOW + ANONYMIZED` |
| qualquer falha | regra não satisfeita | `DENY + motivo` |

Métricas mínimas:

```text
auth_decisoes_total{decisao,nivel,role,motivo}
auth_db_query_duration_seconds{consulta}
grpc_server_handled_total{rpc,code}
grpc_server_handling_seconds{rpc}
```

Critério de pronto:

- smoke test gRPC cobre ALLOW e DENY dos três perfis;
- casos 1 a 12 da matriz têm decisão correta;
- `/metrics` responde;
- falha de banco retorna erro gRPC controlado, não stack trace bruto.

### 2.4 Implementar Patient Data Service

Fonte de verdade:

- `proto/data.proto`
- `docs/matriz-acesso.md` seção 3
- `docs/mapeamento-fhir.md`

Responsabilidade:

- falar SQL;
- devolver dados crus em `comum.ConjuntoDadosClinicos` ou `comum.ResultadoAgregado`;
- nunca anonimizar;
- nunca montar FHIR;
- assumir que os IDs recebidos já foram autorizados pelo Auth Service.

RPCs:

| RPC | Uso |
|---|---|
| `BuscarPacientes` | FULL, PARTIAL e ANONYMIZED |
| `BuscarCoorte` | ANONYMIZED em `ExamesCoorte` |
| `AgregarCoorte` | AGGREGATED |
| `ListarProjetos` | tela/rota de projetos do pesquisador, se usada pelo Gateway |

Métricas mínimas:

```text
data_queries_total{tipo}
data_query_duration_seconds{tipo}
data_db_pool_em_uso
data_linhas_retornadas{tipo}
grpc_server_handled_total{rpc,code}
grpc_server_handling_seconds{rpc}
```

Critério de pronto:

- `BuscarPacientes` retorna pacientes, atendimentos e eventos coerentes com `FiltroPacientes`;
- `AgregarCoorte` retorna total, distribuições, frequências e estatísticas;
- queries principais têm `EXPLAIN ANALYZE` salvo ou descrito no relatório;
- `/metrics` responde;
- serviço funciona com o banco institucional por variáveis de ambiente.

### 2.5 Configuração segura

Os manifests finais devem consumir dados sensíveis por `Secret`, criado fora do git. O repositório pode ter apenas um template sem valores reais.

Exemplo de nomes esperados:

```yaml
env:
  - name: DB_HOST
    valueFrom:
      secretKeyRef:
        name: pspd-db
        key: host
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: pspd-db
        key: password
```

Não versionar:

- senha SSH;
- senha do banco;
- token do kubeconfig;
- senha dos usuários Keycloak;
- `ANON_SALT`.

### 2.6 Testar antes do Gateway

Antes da integração REST:

1. gerar stubs com `./scripts/gen_protos.sh`;
2. subir Auth e Data localmente contra o banco institucional ou contra o banco local;
3. rodar clientes gRPC pequenos para os principais casos;
4. confirmar `/metrics`;
5. só então integrar com Gateway.

Isso evita depurar JWT, REST, gRPC e SQL ao mesmo tempo.

Validações disponíveis:

```bash
./scripts/test_python_services.sh
./scripts/smoke_auth_data.sh
export ANON_SALT=smoke-local-nao-usar-em-producao
./scripts/smoke_pipeline_grpc.sh
```

`smoke_auth_data.sh` valida Auth/Data contra o banco configurado por `DB_*`. `smoke_pipeline_grpc.sh` valida `Auth -> Data -> Transform` sem Gateway, cobrindo FULL, DENY, AGGREGATED e ANONYMIZED. O salt do exemplo é apenas para teste local; em Kubernetes, `ANON_SALT` deve vir de `Secret`.

Relatório técnico da execução: `docs/relatorio-danilo-auth-data.md`.

### 2.7 Pgbouncer por último

O experimento pgbouncer só entra depois de:

- Auth real funcionando;
- Data real funcionando;
- Gateway chamando o pipeline;
- k6 conseguindo gerar carga real;
- métricas de conexão/latência disponíveis.

Hipótese do experimento:

> Escalar horizontalmente o Data Service aumenta a pressão de conexões sobre um Postgres compartilhado; pgbouncer reduz churn de conexão e pode recuperar throughput até o gargalo voltar a ser CPU/SQL.

Comparar:

- Data Service direto no Postgres;
- Data Service via pgbouncer;
- 1, 3 e HPA de réplicas;
- throughput, p95, erros, conexões ativas e tempo de query.

## 3. Contrato com os outros integrantes

Danilo entrega a Guilherme:

- endereço gRPC do Auth;
- endereço gRPC do Data;
- lista de motivos de negação;
- mapeamento escopo -> filtro;
- exemplos de requisição/resposta para os três perfis.

Danilo entrega a Luiz:

- portas gRPC e `/metrics`;
- variáveis de ambiente necessárias;
- requests/limits sugeridos;
- health/readiness checks;
- nomes de métricas para Grafana/HPA.

Danilo entrega ao relatório:

- introspecção do banco;
- regras de autorização;
- queries principais;
- resultados de `EXPLAIN ANALYZE`;
- limitações encontradas;
- resultados do experimento pgbouncer, se houver tempo.

## 4. Definição de pronto

A parte do Danilo está pronta quando:

- Auth e Data rodam em container;
- ambos expõem `/metrics`;
- o smoke gRPC local completa FULL, ANONYMIZED, AGGREGATED e DENY contra o banco institucional;
- o Gateway consegue completar pelo menos um fluxo FULL, um PARTIAL, um ANONYMIZED, um AGGREGATED e um DENY;
- a validação funcional registra os casos correspondentes no relatório.

Estado atual: código, testes locais e smokes gRPC contra `pseudopep_g09` concluídos. Deploy em `grupo-9`, integração HTTP pelo Gateway e validação funcional final dependem das frentes de Luiz/Guilherme.
