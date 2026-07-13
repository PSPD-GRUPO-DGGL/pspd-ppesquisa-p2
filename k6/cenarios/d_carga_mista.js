// Cenário D — carga mista realista.

import { sleep } from 'k6';
import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';
import {
  GATEWAY,
  CARGA,
  PROJETO_COORTE,
  CONDICAO_COORTE,
  PACIENTE_MEDICO,
  PACIENTE_ESTAGIARIO,
  PACIENTE_NEGADO,
  cabecalhos,
  conferirBundle,
  obterToken,
} from '../comum.js';

export const options = {
  scenarios: { d_carga_mista: CARGA },
  thresholds: {
    http_req_failed: [{ threshold: 'rate<0.02', abortOnFail: false }],
    'http_req_duration{name:D_medico_full}': [{ threshold: 'p(95)<500', abortOnFail: false }],
  },
};

const negadas = new Counter('cenario_d_negadas');
const duracaoPorPerfil = new Trend('cenario_d_duracao_ms', true);

function pacienteDoCardoso() {
  if (PACIENTE_MEDICO) return PACIENTE_MEDICO;
  const i = 2 * (1 + Math.floor(Math.random() * 999));
  return 'P' + String(i).padStart(6, '0');
}

function pacienteSemVinculo() {
  if (PACIENTE_NEGADO) return PACIENTE_NEGADO;
  const i = 10000 + Math.floor(Math.random() * 39000);
  return 'P' + String(i).padStart(6, '0');
}

export function setup() {
  return {
    medico: obterToken('medico'),
    estagiario: obterToken('estagiario'),
    pesquisador: obterToken('pesquisador'),
  };
}

export default function (t) {
  const sorteio = Math.random();

  if (sorteio < 0.6) {
    const r = http.get(
      `${GATEWAY}/api/pacientes/${pacienteDoCardoso()}/resumo-clinico`,
      cabecalhos(t.medico, 'D_medico_full'));
    conferirBundle(r, 'Bundle');
    duracaoPorPerfil.add(r.timings.duration, { perfil: 'medico' });

  } else if (sorteio < 0.8) {
    const r = http.get(
      `${GATEWAY}/api/pacientes/${PACIENTE_ESTAGIARIO || pacienteDoCardoso()}/resumo-clinico`,
      cabecalhos(t.estagiario, 'D_estagiario_partial'));
    conferirBundle(r, 'Bundle');
    duracaoPorPerfil.add(r.timings.duration, { perfil: 'estagiario' });

  } else if (sorteio < 0.95) {
    const r = http.get(
      `${GATEWAY}/api/coortes/estatisticas?projeto=${PROJETO_COORTE}&condicao=${CONDICAO_COORTE}`,
      cabecalhos(t.pesquisador, 'D_pesquisador_aggregated'));
    conferirBundle(r, 'MeasureReport');
    duracaoPorPerfil.add(r.timings.duration, { perfil: 'pesquisador' });

  } else {
    const r = http.get(
      `${GATEWAY}/api/pacientes/${pacienteSemVinculo()}/resumo-clinico`,
      cabecalhos(t.medico, 'D_deny'));
    if (r.status === 403) negadas.add(1);
    duracaoPorPerfil.add(r.timings.duration, { perfil: 'deny' });
  }

  sleep(0.2);
}
