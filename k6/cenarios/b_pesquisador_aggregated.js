// Cenário B — Pesquisador, nível AGGREGATED. DB-bound.
//
// Agregação da coorte de Diabetes: GROUP BY e percentile_cont sobre ~961k
// observações. Medido em 154,6 ms no banco, com sort externo em disco.
//
// Hipótese a validar: a latência é dominada pelo Postgres, que é único. Escalar
// réplicas do Patient Data Service NÃO melhora este cenário — só multiplica
// conexões contra o mesmo banco. É o contraste com o cenário C.

import { sleep } from 'k6';
import http from 'k6/http';
import { Trend } from 'k6/metrics';
import { GATEWAY, DEGRAUS, PROJETO_COORTE, CONDICAO_COORTE, cabecalhos, conferirBundle, obterToken } from '../comum.js';

// O SLO de p95 < 500ms não se aplica a este caminho: a consulta sozinha custa
// 154ms sem concorrência. O limiar aqui existe para registrar onde ele estoura.
export const options = {
  scenarios: { b_pesquisador_aggregated: DEGRAUS },
  thresholds: {
    http_req_failed: [{ threshold: 'rate<0.05', abortOnFail: false }],
    http_req_duration: [{ threshold: 'p(95)<3000', abortOnFail: false }],
  },
};

const duracaoAgg = new Trend('cenario_b_duracao_ms', true);

export function setup() {
  return { token: obterToken('pesquisador') };
}

export default function (dados) {
  const url = `${GATEWAY}/api/coortes/estatisticas?projeto=${PROJETO_COORTE}&condicao=${CONDICAO_COORTE}`;
  const r = http.get(url, cabecalhos(dados.token, 'B_pesquisador_aggregated'));

  conferirBundle(r, 'MeasureReport');
  duracaoAgg.add(r.timings.duration);

  sleep(0.5);
}
