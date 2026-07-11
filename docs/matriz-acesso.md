# Matriz de nível de acesso

Documento normativo. O `AuthService` decide **qual** nível se aplica; o `DataTransformService` decide **o que** cada nível deixa passar. Os dois lêem esta tabela. Divergência entre eles é bug.

Base: enunciado, seção 2.1 e descrição do Authorization Service.

## 0. Ambiente final e usuários

Na versão final, o login não usa o realm local antigo `hospital`. A autenticação deve usar o Keycloak institucional:

```text
https://kiriland.unb.br/keycloak/realms/grupo09
```

Usuários informados pelo professor:

| Perfil | Usuários |
|---|---|
| MEDICO | `med.cardoso`, `med.lima`, `med.almeida`, `med.rocha`, `med.monteiro` |
| ESTAGIARIO | `est.ferreira`, `est.gomes`, `est.costa`, `est.melo`, `est.dias` |
| PESQUISADOR | `pes.mendes`, `pes.araujo`, `pes.silveira` |

As regras abaixo são normativas. Os casos concretos com `id_paciente` e `id_projeto` precisam ser recalibrados depois da introspecção do banco institucional `pseudopep_g09`, porque os exemplos do seed local usam alguns usuários de desenvolvimento que podem não existir no Keycloak final.

## 1. Decisão: quem recebe qual nível

O `AuthService` recebe `username`, `role` e `escopo` do JWT já validado, e devolve `ALLOW + nível` ou `DENY + motivo`.

### MEDICO

Consulta `user_patient_assignments`. Para cada `id_paciente` pedido, existe linha com `username_cuidador = username`, `tipo_vinculo = 'medico'` e `status = 'Ativo'`?

- Todos os ids têm vínculo → `ALLOW` + `FULL`, `ids_autorizados` = todos.
- Alguns têm → `ALLOW` + `FULL`, `ids_autorizados` = apenas os vinculados. **Decisão parcial, não negação total.** Vale registrar no relatório: negar a consulta inteira porque um id de 50 não tem vínculo transforma um erro de digitação numa falha de sistema. Filtrar é o comportamento correto e é o que sistemas de prontuário reais fazem.
- Nenhum tem → `DENY`, motivo `sem_vinculo_ativo`.

Um vínculo com `status = 'Inativo'` **não** autoriza. O seed inclui um paciente nessa condição justamente para que o teste pegue a implementação que esqueceu do `AND status = 'Ativo'`.

### ESTAGIARIO

Consulta `user_patient_assignments` com `tipo_vinculo = 'estagiario'`, `status = 'Ativo'` **e** `username_supervisor IS NOT NULL`. O supervisor precisa existir: é isso que "paciente ligado ao médico supervisor" significa. Um vínculo de estagiário sem supervisor é dado inconsistente e deve negar.

- Vínculo supervisionado existe → `ALLOW` + `PARTIAL`.
- Não existe → `DENY`, motivo `sem_supervisao_ativa`.

### PESQUISADOR

Consulta `projects` por `id_projeto`. Exige, cumulativamente:

1. `username_pesquisador = username` — o projeto é dele. Senão `DENY`, motivo `projeto_de_outro_pesquisador`.
2. `status = 'Aprovado'` — senão `DENY`, motivo `projeto_nao_aprovado` (cobre Suspenso e qualquer outro status).
3. `data_validade >= CURRENT_DATE` — senão `DENY`, motivo `projeto_expirado`.
4. `codigo_condicao_clinica = codigo_condicao` pedido — o pesquisador não pode consultar uma coorte fora do escopo do seu projeto aprovado. Senão `DENY`, motivo `condicao_fora_do_projeto`.

Passando os quatro, o nível depende do escopo:

| escopo | nível |
|---|---|
| `EstatisticasCoorte`, `ResumoCoorte` | `AGGREGATED` |
| `ExamesCoorte` | `ANONYMIZED` |
| `MeusProjetos` | `ALLOW` sem dado clínico (lista de projetos do próprio usuário) |

O seed local tem os quatro desfechos: `PRJ01` aprovado e vigente (ALLOW), `PRJ02` expirado, `PRJ03` suspenso, `PRJ04` aprovado mas de outro pesquisador (DENY por dono). No banco institucional, Danilo deve identificar projetos equivalentes para os usuários finais (`pes.mendes`, `pes.araujo`, `pes.silveira`) e atualizar a matriz de teste.

## 2. Projeção: o que cada nível deixa passar

Aplicada pelo `DataTransformService`, **antes** da montagem do Bundle FHIR. Converter primeiro e limpar depois produziria um Bundle completo em memória com CPF dentro, a um `return` de distância de vazar.

| Campo | FULL | PARTIAL | ANONYMIZED | AGGREGATED |
|---|---|---|---|---|
| `id_paciente` | real | real | **pseudônimo** (`hash001`) | ausente |
| `nome` | completo | **iniciais** (`J.S.C.`) | ausente | ausente |
| `cpf` | presente | **ausente** | ausente | ausente |
| `cns` | presente | **ausente** | ausente | ausente |
| `data_nascimento` | exata | **ano apenas** | **faixa etária** | distribuição |
| `genero` | presente | presente | presente | distribuição |
| `cidade` | presente | presente | **ausente** | ausente |
| `estado` | presente | presente | presente | distribuição |
| `atendimentos` | completos | completos | completos | distribuição por setor |
| `condições` | presentes | presentes | presentes | contagem |
| `exames` | presentes | presentes | presentes | média, mediana, desvio |
| `medicamentos` | presentes | presentes | presentes | frequência |

Notas sobre casos que a tabela não captura:

**Faixa etária** (`ANONYMIZED`) usa as faixas do exemplo do enunciado: `18-39`, `40-59`, `60-79`, `80+`.

**Iniciais** (`PARTIAL`): "João da Silva Cardoso" → `J.S.C.`. Preposições (`da`, `de`, `dos`) são descartadas, não viram inicial.

**Pseudônimo** (`ANONYMIZED`): `hash` + os 6 primeiros dígitos de `HMAC-SHA256(salt, id_paciente)`. Determinístico dentro de uma execução — o mesmo paciente aparece com o mesmo pseudônimo em duas linhas do mesmo resultado, senão o pesquisador não consegue correlacionar exames do mesmo indivíduo, que é metade da utilidade do dataset.

**O salt não fica no código.** Vem da variável de ambiente `ANON_SALT`. Sem salt secreto, a pseudonimização é reversível por força bruta: o espaço de `id_paciente` é conhecido e pequeno (50 mil valores), então um atacante que veja `hash001` computa os 50 mil hashes e inverte a tabela em segundos. É a mesma razão pela qual hashear CPF sem salt não anonimiza nada — há só 10¹¹ CPFs, e menos ainda válidos. Isso vale um parágrafo no relatório: **anonimização não é uma função, é uma propriedade do sistema todo**, e um pseudônimo estável entre requisições ainda permite ataques de ligação (*linkage attacks*) se o pesquisador cruzar com dado externo.

**`AGGREGATED` e o risco de reidentificação por célula pequena.** Uma coorte com 2 pacientes, agregada por sexo e faixa etária, identifica ambos. Sistemas reais aplicam supressão de célula (não reportar grupos com `n < k`, tipicamente `k = 5`). Não implementamos isso, mas registramos a limitação — reconhecer o buraco vale mais do que fingir que ele não existe.

## 3. Mapeamento escopo → dados requisitados

Serve ao `PatientDataService`: qual `FiltroPacientes` cada escopo produz.

| escopo | atendimentos | eventos | tipo_evento | limite |
|---|---|---|---|---|
| `ListaPacientes` | não | não | — | — |
| `ResumoClinico` | sim | sim | todos | 20 mais recentes |
| `HistoricoClinico` | sim | sim | todos | sem limite |
| `Exames` | não | sim | `Observacao` | sem limite |
| `Medicamentos` | não | sim | `Medicacao` | sem limite |
| `ResumoCoorte` | — | — | — | agregação |
| `EstatisticasCoorte` | — | — | — | agregação |
| `ExamesCoorte` | sim | sim | `Observacao` | por paciente da coorte |

No contrato gRPC, `ExamesCoorte` usa `PatientDataService.BuscarCoorte(FiltroCoorte) -> ConjuntoDadosClinicos`; `ResumoCoorte` e `EstatisticasCoorte` usam `AgregarCoorte(FiltroCoorte) -> ResultadoAgregado`.

## 4. Matriz de teste

Cada linha é um caso do `scripts/validacao_funcional.sh` e uma linha da tabela de resultados do relatório.

**Estado atual:** a tabela abaixo ainda é a matriz lógica baseada no seed local. Antes da entrega, substituir os casos que usam usuários/projetos inexistentes no Keycloak institucional por equivalentes encontrados no `pseudopep_g09`. A estrutura esperada dos 15 casos não muda.

| # | usuário | role | escopo | alvo | esperado |
|---|---|---|---|---|---|
| 1 | `med.cardoso` | MEDICO | ResumoClinico | `P000002` (vinculado) | 200, FULL, CPF presente |
| 2 | `med.cardoso` | MEDICO | ResumoClinico | `P049000` (sem vínculo) | 403, `sem_vinculo_ativo` |
| 3 | `med.cardoso` | MEDICO | ResumoClinico | `P050000` (vínculo Inativo) | 403, `sem_vinculo_ativo` |
| 4 | `med.silva` | MEDICO | ResumoClinico | `P000002` (é do cardoso) | 403, `sem_vinculo_ativo` |
| 5 | estagiário institucional a definir | ESTAGIARIO | ResumoClinico | paciente supervisionado | 200, PARTIAL, nome `X.Y.Z.`, sem CPF |
| 6 | estagiário institucional a definir | ESTAGIARIO | ResumoClinico | paciente fora da supervisão | 403, `sem_supervisao_ativa` |
| 7 | pesquisador institucional a definir | PESQUISADOR | EstatisticasCoorte | projeto aprovado / condição do projeto | 200, AGGREGATED, `MeasureReport`, zero identificadores |
| 8 | pesquisador institucional a definir | PESQUISADOR | ExamesCoorte | projeto aprovado / condição do projeto | 200, ANONYMIZED, pseudônimos, sem nome/CPF |
| 9 | pesquisador institucional a definir | PESQUISADOR | EstatisticasCoorte | projeto expirado | 403, `projeto_expirado` |
| 10 | pesquisador institucional a definir | PESQUISADOR | EstatisticasCoorte | projeto suspenso/não aprovado | 403, `projeto_nao_aprovado` |
| 11 | pesquisador institucional a definir | PESQUISADOR | EstatisticasCoorte | projeto de outro pesquisador | 403, `projeto_de_outro_pesquisador` |
| 12 | pesquisador institucional a definir | PESQUISADOR | EstatisticasCoorte | projeto aprovado / condição fora do projeto | 403, `condicao_fora_do_projeto` |
| 13 | — | — | ResumoClinico | token ausente | 401 |
| 14 | — | — | ResumoClinico | token com assinatura inválida | 401 |
| 15 | `med.cardoso` | MEDICO | ResumoClinico | token expirado | 401 |

Os casos 13–15 nunca chegam ao `AuthService`: o Gateway rejeita no `jose.jwtVerify` contra o JWKS. Isso é mensurável e vale gráfico — uma requisição 401 custa uma ordem de grandeza menos que uma 200.
