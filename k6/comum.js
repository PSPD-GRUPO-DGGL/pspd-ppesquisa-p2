import http from 'k6/http';
import { check } from 'k6';

export const GATEWAY = __ENV.GATEWAY || 'https://kiriland.unb.br/grupo9';
export const KEYCLOAK = __ENV.KEYCLOAK || 'https://kiriland.unb.br/keycloak';
export const REALM = __ENV.REALM || 'grupo09';
export const CLIENT_ID = __ENV.CLIENT_ID || 'frontend';
export const PROJETO_COORTE = __ENV.K6_PROJECT || 'PRJ01';
export const CONDICAO_COORTE = __ENV.K6_CONDITION || 'DIABETES';
export const PACIENTE_MEDICO = __ENV.K6_MED_PATIENT || '';
export const PACIENTE_ESTAGIARIO = __ENV.K6_TRAINEE_PATIENT || PACIENTE_MEDICO;
export const PACIENTE_NEGADO = __ENV.K6_DENIED_PATIENT || '';

function senhaObrigatoria(nomeEnv) {
  const valor = __ENV[nomeEnv];
  if (!valor) {
    throw new Error(`${nomeEnv} não definido; informe a senha por variável de ambiente`);
  }
  return valor;
}

export const USUARIOS = {
  medico: {
    username: __ENV.K6_USER_MEDICO || 'med.cardoso',
    passwordEnv: 'K6_PASSWORD_MEDICO',
  },
  estagiario: {
    username: __ENV.K6_USER_ESTAGIARIO || 'est.ferreira',
    passwordEnv: 'K6_PASSWORD_ESTAGIARIO',
  },
  pesquisador: {
    username: __ENV.K6_USER_PESQUISADOR || 'pes.mendes',
    passwordEnv: 'K6_PASSWORD_PESQUISADOR',
  },
};

// Token no setup, não por iteração: senão a latência mediria o Keycloak, não a app.
export function obterToken(perfil) {
  const u = USUARIOS[perfil];
  const url = `${KEYCLOAK}/realms/${REALM}/protocol/openid-connect/token`;
  const corpo = {
    grant_type: 'password',
    client_id: CLIENT_ID,
    username: u.username,
    password: senhaObrigatoria(u.passwordEnv),
  };
  const r = http.post(url, corpo, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    tags: { name: 'keycloak_token' },
  });
  if (r.status !== 200) {
    throw new Error(`token de ${perfil} falhou: ${r.status} ${r.body}`);
  }
  return r.json('access_token');
}

export function cabecalhos(token, nomeCenario) {
  return {
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    tags: { name: nomeCenario },
  };
}

export function conferirBundle(resposta, resourceTypeEsperado) {
  return check(resposta, {
    'status 200': (r) => r.status === 200,
    'e um Bundle ou MeasureReport': (r) => {
      try {
        return r.json('resourceType') === resourceTypeEsperado;
      } catch (_) {
        return false;
      }
    },
  });
}

export const DEGRAUS = {
  executor: 'ramping-vus',
  startVUs: 0,
  stages: [
    { duration: '15s', target: 10 }, { duration: '1m', target: 10 },
    { duration: '15s', target: 50 }, { duration: '1m', target: 50 },
    { duration: '15s', target: 100 }, { duration: '1m', target: 100 },
    { duration: '30s', target: 500 }, { duration: '1m', target: 500 },
    { duration: '30s', target: 1000 }, { duration: '1m', target: 1000 },
    { duration: '30s', target: 0 },
  ],
  gracefulRampDown: '30s',
};

// abortOnFail:false — violar o limiar nos degraus altos é esperado, não motivo de abortar.
export const LIMIARES = {
  http_req_failed: [{ threshold: 'rate<0.01', abortOnFail: false }],
  http_req_duration: [{ threshold: 'p(95)<500', abortOnFail: false }],
};
