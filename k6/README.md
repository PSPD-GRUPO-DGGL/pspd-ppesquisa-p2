# Testes de carga

Quatro cenários k6, desenhados para produzir **contraste** em vez de confirmar que mais réplicas deixam tudo mais rápido.

O k6 roda **fora do cluster**, como binário nativo no host, batendo no NodePort do Gateway. Um pod k6 agendado num worker roubaria CPU exatamente dos pods sob medição, e o enunciado exige "garantir as mesmas condições de teste de infraestrutura de modo a não contaminar os resultados".

## Rodar

```bash
export GATEWAY=http://localhost:30080
export KEYCLOAK=http://localhost:8080

k6 run k6/cenarios/a_medico_full.js

# com exportacao para o Prometheus, que e o que faz o relatorio funcionar
k6 run --out experimental-prometheus-rw \
       -e GATEWAY=$GATEWAY \
       k6/cenarios/d_carga_mista.js
```

Exportar as métricas do k6 para o Prometheus coloca throughput e latência **medidos pelo cliente** no mesmo eixo temporal que CPU, memória e contagem de pods **medidos pelo cluster**. É o que permite afirmar, com um gráfico só, que no segundo 47 o HPA criou o terceiro pod e o p95 caiu de 800 ms para 210 ms.

Todos os cenários usam os degraus exigidos pelo enunciado: **10, 50, 100, 500 e 1000** usuários simultâneos, com rampas curtas e patamares de um minuto. Os primeiros segundos de cada patamar são warm-up e devem ser descartados na análise.

## Os cenários

**A — Médico, FULL.** Prontuário de um paciente vinculado. Index scan puro, medido em 0,25 ms no banco. Estabelece o baseline e o SLO (p95 < 500 ms, erro < 1%). Se este caminho degrada, o culpado é a aplicação, não o Postgres.

**B — Pesquisador, AGGREGATED.** Agregação da coorte de Diabetes: `GROUP BY` e `percentile_cont` sobre ~961 mil observações, medido em 154,6 ms com sort externo em disco. *Hipótese: a latência é dominada pelo Postgres, que é único; escalar réplicas do Patient Data Service não melhora nada — só multiplica conexões contra o mesmo banco.*

**C — Pesquisador, ANONYMIZED.** Exames por paciente da coorte, pseudonimizados. Um HMAC-SHA256 e vários Resources FHIR por paciente. Trabalho de CPU puro, sem estado. *Hipótese: escalar réplicas do Data Transform Service reduz a latência proporcionalmente.*

**D — Carga mista.** Os três perfis simultâneos, nas proporções de um hospital real: 60% médicos, 20% estagiários, 15% pesquisadores, 5% requisições negadas. Exercita o HPA com mistura de caminhos leve e pesado, e expõe o efeito de vizinhança — as consultas baratas do médico degradam quando o pesquisador satura o banco, mesmo sem compartilhar serviço com ele.

O caminho **DENY** do cenário D também é medida: o Gateway corta em 403 antes de tocar no banco, e o custo dessa requisição é o piso do sistema. Comparar 403 com 200 quantifica quanto do tempo é autorização e quanto é dado.

## A descoberta que os cenários existem para produzir

O contraste **B versus C** é a conclusão central do trabalho.

Os dois são do mesmo usuário, com o mesmo token, sob a mesma carga. O que muda é onde o trabalho acontece. No cenário C o gargalo é CPU num serviço *stateless*, e o HPA resolve. No cenário B o gargalo é um banco compartilhado, e o HPA não resolve — pode até piorar, quando o total de conexões estoura o `max_connections` do Postgres.

*Escala horizontal resolve serviço stateless compute-bound; não resolve estado compartilhado.*

## Pré-requisitos

Os cenários assumem o realm `hospital` no Keycloak, com os usuários `med.cardoso`, `est.pereira` e `pes.souza`, e as rotas do Gateway listadas em `comum.js`. Enquanto Auth, Data e Gateway não estiverem de pé, os scripts servem de especificação executável do contrato REST esperado.

Validar sintaxe sem subir nada:

```bash
k6 inspect k6/cenarios/a_medico_full.js
```
