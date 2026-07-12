// Cenário C — Pesquisador, nível ANONYMIZED. Transform-bound.
//
// Exames por paciente da coorte, pseudonimizados. Cada paciente custa um
// HMAC-SHA256 e vários Resources FHIR. O trabalho é CPU puro, sem estado.
//
// Hipótese a validar: escalar réplicas do Data Transform Service melhora a
// latência proporcionalmente, ao contrário do cenário B. É a descoberta
// central do trabalho — escala horizontal resolve serviço stateless
// compute-bound, não resolve estado compartilhado.

import { sleep } from 'k6';
import http from 'k6/http';
import { Trend } from 'k6/metrics';
import { GATEWAY, DEGRAUS, PROJETO_COORTE, CONDICAO_COORTE, cabecalhos, conferirBundle, obterToken } from '../comum.js';

export const options = {
  scenarios: { c_pesquisador_anonymized: DEGRAUS },
  thresholds: {
    http_req_failed: [{ threshold: 'rate<0.05', abortOnFail: false }],
    http_req_duration: [{ threshold: 'p(95)<2000', abortOnFail: false }],
  },
};

const duracaoAnon = new Trend('cenario_c_duracao_ms', true);
const recursosPorResposta = new Trend('cenario_c_recursos_fhir');

const LOTES = [50, 100, 200];

export function setup() {
  return { token: obterToken('pesquisador') };
}

export default function (dados) {
  const limite = LOTES[Math.floor(Math.random() * LOTES.length)];
  const url = `${GATEWAY}/api/coortes/exames?projeto=${PROJETO_COORTE}&condicao=${CONDICAO_COORTE}&limite=${limite}`;
  const r = http.get(url, cabecalhos(dados.token, 'C_pesquisador_anonymized'));

  if (conferirBundle(r, 'Bundle')) {
    try {
      recursosPorResposta.add(r.json('entry').length);
    } catch (_) {
      // sem entry: já contabilizado pelo check acima
    }
  }
  duracaoAnon.add(r.timings.duration);

  sleep(0.3);
}
