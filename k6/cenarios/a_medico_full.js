// Cenário A — Médico, nível FULL. Baseline.
//
// Lookup de um paciente vinculado: index scan em patients, encounters e
// clinical_events. Medido em 0,25 ms no banco. Se este caminho ficar lento sob
// carga, o culpado é a aplicação, não o Postgres.

import { sleep } from 'k6';
import http from 'k6/http';
import { Trend } from 'k6/metrics';
import { GATEWAY, DEGRAUS, LIMIARES, PACIENTE_MEDICO, cabecalhos, conferirBundle, obterToken } from '../comum.js';

export const options = { scenarios: { a_medico_full: DEGRAUS }, thresholds: LIMIARES };

const duracaoFull = new Trend('cenario_a_duracao_ms', true);

// Pacientes 1..2000 têm vínculo com med.cardoso ou med.silva (ver db/seed).
// med.cardoso fica com os pares.
function pacienteDoCardoso() {
  if (PACIENTE_MEDICO) return PACIENTE_MEDICO;
  const i = 2 * (1 + Math.floor(Math.random() * 999));
  return 'P' + String(i).padStart(6, '0');
}

export function setup() {
  return { token: obterToken('medico') };
}

export default function (dados) {
  const url = `${GATEWAY}/api/pacientes/${pacienteDoCardoso()}/resumo-clinico`;
  const r = http.get(url, cabecalhos(dados.token, 'A_medico_full'));

  conferirBundle(r, 'Bundle');
  duracaoFull.add(r.timings.duration);

  sleep(0.1);
}
