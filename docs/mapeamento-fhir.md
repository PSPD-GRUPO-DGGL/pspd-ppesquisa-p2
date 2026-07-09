# Mapeamento relacional → HL7/FHIR

Especificação do `DataTransformService`. Define como cada linha das cinco tabelas vira um Resource FHIR, e como o nível de acesso altera o Resource emitido.

Referência normativa: HL7 FHIR R4 (https://www.hl7.org/fhir/). O enunciado (seção 2.1) fixa o mapeamento de alto nível; este documento resolve os detalhes que ele deixa em aberto.

## 1. Tabela → Resource

| Tabela | Discriminante | Resource FHIR |
|---|---|---|
| `patients` | — | `Patient` |
| `encounters` | — | `Encounter` |
| `clinical_events` | `tipo_evento = 'Condicao'` | `Condition` |
| `clinical_events` | `tipo_evento = 'Observacao'` | `Observation` |
| `clinical_events` | `tipo_evento = 'Medicacao'` | `MedicationRequest` |
| `projects` | — | *(não é Resource clínico; devolvido como JSON simples)* |
| agregações | — | `MeasureReport` |

Uma tabela vira três Resources. O discriminante é `tipo_evento`, e é a única coisa que decide — `valor` e `unidade` estarem preenchidos é consequência, não causa.

## 2. Envelope: `Bundle`

Toda resposta é um `Bundle` de tipo `collection`. Um `searchset` seria mais correto para resultado de busca, mas exige `Bundle.total` e semântica de paginação que não implementamos; `collection` é honesto sobre o que estamos entregando.

```json
{
  "resourceType": "Bundle",
  "type": "collection",
  "timestamp": "2026-07-09T19:20:00Z",
  "entry": [
    { "resource": { "resourceType": "Patient", "...": "..." } },
    { "resource": { "resourceType": "Encounter", "...": "..." } }
  ]
}
```

`Bundle.entry.fullUrl` é omitido: só faz sentido com um servidor FHIR de verdade servindo URLs resolvíveis, e inventar `urn:uuid:` para cada recurso daria uma falsa aparência de conformidade.

## 3. `Patient`

O Resource mais afetado pelo nível de acesso. É aqui que a anonimização acontece de fato.

**FULL** — tudo. `cpf` e `cns` viram `identifier` com `system` distinto, que é como FHIR representa identificadores nacionais.

```json
{
  "resourceType": "Patient",
  "id": "P000001",
  "identifier": [
    { "system": "urn:oid:2.16.76.1.3.1", "value": "12345678901" },
    { "system": "https://fhir.saude.gov.br/sid/cns", "value": "700000000000001" }
  ],
  "name": [{ "text": "João da Silva Cardoso" }],
  "birthDate": "1970-05-10",
  "gender": "male",
  "address": [{ "city": "Brasília", "state": "DF" }]
}
```

O OID `2.16.76.1.3.1` é o identificador oficial do CPF no registro brasileiro de OIDs. Usar `system: "cpf"` funcionaria e ninguém reclamaria, mas o OID é o que um servidor FHIR real espera.

**PARTIAL** — sem `identifier`. Nome vira iniciais. `birthDate` perde mês e dia.

```json
{
  "resourceType": "Patient",
  "id": "P000001",
  "name": [{ "text": "J.S.C." }],
  "birthDate": "1970",
  "gender": "male",
  "address": [{ "city": "Brasília", "state": "DF" }]
}
```

FHIR aceita `birthDate` parcial (`YYYY` ou `YYYY-MM`) — é `date`, não `dateTime`. Truncar o ano é conforme, não gambiarra.

**ANONYMIZED** — `id` vira pseudônimo, `city` some, idade vira faixa via extensão.

```json
{
  "resourceType": "Patient",
  "id": "hash4f2a91",
  "gender": "female",
  "address": [{ "state": "DF" }],
  "extension": [{
    "url": "http://hl7.org/fhir/StructureDefinition/patient-ageRange",
    "valueString": "60-79"
  }]
}
```

FHIR não tem campo nativo para faixa etária — `birthDate` é uma data ou nada. A saída correta é uma `extension`. A URL acima é ilustrativa: extensões próprias deveriam ser publicadas num `StructureDefinition` do domínio. Registrado como limitação.

**AGGREGATED** — nenhum `Patient` é emitido. Nem pseudonimizado. Ver seção 7.

## 4. `Encounter`

```json
{
  "resourceType": "Encounter",
  "id": "E00000001",
  "status": "finished",
  "class": { "code": "AMB", "display": "ambulatory" },
  "subject": { "reference": "Patient/P000001" },
  "period": { "start": "2023-02-10T08:00:00", "end": "2023-02-10T11:00:00" },
  "serviceType": { "text": "Cardiologia" }
}
```

`tipo_atendimento` mapeia para o `ActEncounterCode` do HL7 v3:

| `tipo_atendimento` | `class.code` | display |
|---|---|---|
| Ambulatorial | `AMB` | ambulatory |
| Emergencia | `EMER` | emergency |
| Internacao | `IMP` | inpatient encounter |
| Retorno | `AMB` | ambulatory |

Retorno colapsa em `AMB` porque o vocabulário HL7 não distingue primeira consulta de retorno nessa dimensão. A informação não se perde: fica em `serviceType`/`type`.

`status` é sempre `finished` — o seed só gera atendimentos com `data_fim`. Um atendimento em curso seria `in-progress`.

Em `ANONYMIZED`, `subject.reference` aponta para o pseudônimo (`Patient/hash4f2a91`). É por isso que o pseudônimo precisa ser estável dentro da resposta: sem isso as referências do Bundle apontam para o nada.

## 5. `Condition`

```json
{
  "resourceType": "Condition",
  "id": "12345",
  "clinicalStatus": { "coding": [{ "code": "active" }] },
  "code": { "coding": [{ "code": "Diabetes" }], "text": "Diabetes Mellitus Tipo 2" },
  "subject": { "reference": "Patient/P000001" },
  "encounter": { "reference": "Encounter/E00000001" },
  "onsetDateTime": "2023-02-10"
}
```

`code.coding.system` fica **ausente de propósito**. O correto seria SNOMED CT ou CID-10 (`http://hl7.org/fhir/sid/icd-10`), com Diabetes Tipo 2 = `E11`. Nosso `codigo_tipo_evento` é um vocabulário local inventado pelo enunciado. Emitir `system: "http://hl7.org/fhir/sid/icd-10"` com valor `Diabetes` seria uma mentira: afirmaria conformidade com um code system onde aquele código não existe. Um `coding` sem `system` é ambíguo mas honesto. Vale um parágrafo no relatório: **terminologia é metade do problema de interoperabilidade em saúde**, e um sistema real precisaria de uma tabela de-para para CID-10/SNOMED.

## 6. `Observation` e `MedicationRequest`

`Observation` (exames):

```json
{
  "resourceType": "Observation",
  "id": "12346",
  "status": "final",
  "code": { "coding": [{ "code": "HbA1c" }], "text": "Hemoglobina Glicada" },
  "subject": { "reference": "Patient/P000001" },
  "encounter": { "reference": "Encounter/E00000001" },
  "effectiveDateTime": "2023-02-10",
  "valueQuantity": { "value": 8.1, "unit": "%" }
}
```

`valueQuantity` deveria trazer `system: "http://unitsofmeasure.org"` e um `code` UCUM (`%`, `mg/dL`, `mm[Hg]`). Nossas unidades são strings livres. Mesma decisão do `Condition`: emitir só `unit`, sem alegar UCUM.

`MedicationRequest` (medicações) — nota importante: o Resource FHIR modela uma **prescrição**, não uma administração. `clinical_events` não distingue as duas, e o enunciado manda mapear para `MedicationRequest`. Seguimos o enunciado, registrando que uma modelagem clínica correta usaria `MedicationAdministration` quando o evento representa a droga efetivamente dada.

```json
{
  "resourceType": "MedicationRequest",
  "id": "12347",
  "status": "active",
  "intent": "order",
  "medicationCodeableConcept": { "coding": [{ "code": "Metformina" }], "text": "Metformina 850 mg" },
  "subject": { "reference": "Patient/P000001" },
  "authoredOn": "2023-02-10",
  "dosageInstruction": [{ "doseAndRate": [{ "doseQuantity": { "value": 850, "unit": "mg" } }] }]
}
```

`status` e `intent` são campos obrigatórios em FHIR R4 e não existem no banco. Fixamos `active`/`order`. Um valor inventado num campo obrigatório é preferível a um Bundle inválido, mas é invenção — e o relatório diz isso.

## 7. `MeasureReport` — o caminho AGGREGATED

O enunciado não diz que Resource usar para agregação. `MeasureReport` é a escolha certa: é o Resource que FHIR define para resultado de medida populacional, tem `type: "summary"` e grupos com `population.count` e `stratifier`.

Nenhum `Patient` é emitido. Nenhum identificador, nem pseudonimizado. É a diferença categórica entre `ANONYMIZED` (dado por indivíduo, sem nome) e `AGGREGATED` (nenhum indivíduo).

```json
{
  "resourceType": "MeasureReport",
  "status": "complete",
  "type": "summary",
  "measure": "Coorte/Diabetes",
  "date": "2026-07-09T19:20:00Z",
  "group": [{
    "population": [{ "code": { "text": "total-pacientes" }, "count": 14012 }],
    "stratifier": [
      { "code": [{ "text": "genero" }], "stratum": [
          { "value": { "text": "female" }, "population": [{ "count": 9808 }] },
          { "value": { "text": "male" },   "population": [{ "count": 4204 }] } ] },
      { "code": [{ "text": "faixa-etaria" }], "stratum": [
          { "value": { "text": "18-39" }, "population": [{ "count": 1681 }] },
          { "value": { "text": "40-59" }, "population": [{ "count": 6165 }] } ] }
    ]
  }],
  "extension": [{
    "url": "urn:pspd:estatisticas-exames",
    "extension": [
      { "url": "codigo",  "valueString": "HbA1c" },
      { "url": "media",   "valueDecimal": 8.41 },
      { "url": "mediana", "valueDecimal": 8.38 },
      { "url": "n",       "valueInteger": 41230 }
    ]
  }]
}
```

`MeasureReport.stratifier` cobre contagens e percentuais. Não cobre **médias e medianas** — o Resource foi desenhado para medidas de qualidade (proporção, razão), não para estatística descritiva contínua. Média de HbA1c não cabe em `population.count`.

Duas saídas: forçar tudo em `extension` (feito acima), ou emitir `Observation` com `category: "survey"` e valor agregado. Escolhemos a extensão porque manter tudo num `MeasureReport` preserva a semântica de "isto é um relatório populacional, não um dado de paciente" — e essa distinção é exatamente o que o nível `AGGREGATED` precisa garantir. É uma limitação real do FHIR para o caso de uso, e é um bom achado para o relatório.

## 8. Ordem das operações

Inegociável, e é a razão de o `DataTransformService` existir separado do `PatientDataService`:

```
dados crus  →  aplicar nível de acesso  →  montar Bundle FHIR
```

Nunca o contrário. Converter primeiro e limpar depois significa construir, em memória, um `Patient` completo com CPF, e então removê-lo. Um `return` no lugar errado, uma exceção capturada acima, um log de debug do objeto inteiro — e o dado vaza. Aplicar o nível primeiro garante que o identificador direto **nunca chega a existir** na representação de saída.

O mesmo raciocínio vale para o `PatientDataService`: ele devolve linha crua, e não sabe o que é FULL ou ANONYMIZED. Um único componente decide o que sai, e é esse o único componente que precisa ser auditado.

## 9. Métricas que este serviço expõe

O custo da conversão é a variável que o cenário C do teste de carga isola.

| métrica | tipo | rótulos |
|---|---|---|
| `transform_requests_total` | counter | `nivel` |
| `transform_duration_seconds` | histogram | `nivel` |
| `transform_fhir_resources_total` | counter | `tipo` |
| `transform_bundle_bytes` | histogram | `nivel` |

`transform_duration_seconds{nivel}` é o que permite dizer, com número, quanto custa anonimizar comparado a não anonimizar — e se o custo está no *field-stripping* ou na serialização JSON. Espera-se que `AGGREGATED` seja o mais barato por requisição (poucos recursos) e `ANONYMIZED` o mais caro (muitos pacientes, hash por paciente, muitos recursos).
