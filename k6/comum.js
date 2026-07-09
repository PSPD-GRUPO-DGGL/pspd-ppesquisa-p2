import http from 'k6/http';
import { check } from 'k6';

export const GATEWAY = __ENV.GATEWAY || 'http://localhost:30080';
export const KEYCLOAK = __ENV.KEYCLOAK || 'http://localhost:8080';
export const REALM = __ENV.REALM || 'hospital';
export const CLIENT_ID = __ENV.CLIENT_ID || 'frontend';

// Usuários do realm versionado em keycloak/realm-hospital.json.
export const USUARIOS = {
  medico: { username: 'med.cardoso', password: 'senha123' },
  estagiario: { username: 'est.pereira', password: 'senha123' },
  pesquisador: { username: 'pes.souza', password: 'senha123' },
};

// Token obtido uma vez por VU no setup e reusado. Buscá-lo a cada iteração
// mediria o Keycloak, não a aplicação.
export function obterToken(perfil) {
  const u = USUARIOS[perfil];
  const url = `${KEYCLOAK}/realms/${REALM}/protocol/openid-connect/token`;
  const corpo = {
    grant_type: 'password',
    client_id: CLIENT_ID,
    username: u.username,
    password: u.password,
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

// Degraus exigidos pelo enunciado (seção 3.b): 10, 50, 100, 500 e 1000 VUs.
// Patamares de 1 min com rampas curtas; o warm-up é descartado na análise.
export const DEGRAUS = {
  executor: 'ramping-vus',
  startVUs: 0,
  stages: [
    { duration: '15s', target: 10 },   { duration: '1m', target: 10 },
    { duration: '15s', target: 50 },   { duration: '1m', target: 50 },
    { duration: '15s', target: 100 },  { duration: '1m', target: 100 },
    { duration: '30s', target: 500 },  { duration: '1m', target: 500 },
    { duration: '30s', target: 1000 }, { duration: '1m', target: 1000 },
    { duration: '30s', target: 0 },
  ],
  gracefulRampDown: '30s',
};

// SLO do projeto. `abortOnFail: false` porque a violação do limiar é um
// resultado esperado nos degraus altos, e não motivo para encerrar a corrida.
export const LIMIARES = {
  http_req_failed: [{ threshold: 'rate<0.01', abortOnFail: false }],
  http_req_duration: [{ threshold: 'p(95)<500', abortOnFail: false }],
};
