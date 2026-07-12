require('./instrumentation'); // primeiro require: instrumenta as libs antes de carregá-las

const path = require('path');
const express = require('express');
const cors = require('cors');
const jwt = require('jsonwebtoken');
const jwksClient = require('jwks-rsa');
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');
const client = require('prom-client');

const PORT = Number(process.env.PORT || 3000);
const KEYCLOAK_URL = process.env.KEYCLOAK_URL || 'https://kiriland.unb.br/keycloak';
const REALM = process.env.KEYCLOAK_REALM || 'grupo09';
const AUTH_ADDR = process.env.AUTH_ADDR || 'localhost:50051';
const DATA_ADDR = process.env.DATA_ADDR || 'localhost:50052';
const TRANSFORM_ADDR = process.env.TRANSFORM_ADDR || 'localhost:50053';

// --- Métricas de domínio (Prometheus) ---
const registro = new client.Registry();
client.collectDefaultMetrics({ register: registro });

const httpDuracao = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Latência das rotas do Gateway',
  labelNames: ['route', 'perfil', 'status'],
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
  registers: [registro],
});
const grpcDuracao = new client.Histogram({
  name: 'grpc_client_duration_seconds',
  help: 'Latência de cada hop gRPC (tempo de resposta por serviço)',
  labelNames: ['service', 'rpc'],
  buckets: [0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2],
  registers: [registro],
});
const negadasTotal = new client.Counter({
  name: 'autorizacao_negada_total',
  help: 'Consultas negadas pelo AuthService',
  labelNames: ['role', 'motivo'],
  registers: [registro],
});
const jwtDuracao = new client.Histogram({
  name: 'jwt_validacao_duration_seconds',
  help: 'Tempo de validação do JWT contra o JWKS',
  buckets: [0.0005, 0.001, 0.005, 0.01, 0.05, 0.1],
  registers: [registro],
});

// --- JWKS do Keycloak do professor, com cache das chaves ---
const jwks = jwksClient({
  jwksUri: `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/certs`,
  cache: true,
  cacheMaxAge: 10 * 60 * 1000,
  rateLimit: true,
});

function pegarChave(header, callback) {
  jwks.getSigningKey(header.kid, (err, key) => {
    if (err) return callback(err);
    callback(null, key.getPublicKey());
  });
}

// --- Stubs gRPC ---
const pacote = grpc.loadPackageDefinition(
  protoLoader.loadSync(
    [
      path.join(__dirname, '../proto/auth.proto'),
      path.join(__dirname, '../proto/data.proto'),
      path.join(__dirname, '../proto/transform.proto'),
    ],
    { keepCase: true, longs: String, enums: String, defaults: true, oneofs: true }
  )
);

const authClient = new pacote.auth.AuthService(AUTH_ADDR, grpc.credentials.createInsecure());
const dataClient = new pacote.data.PatientDataService(DATA_ADDR, grpc.credentials.createInsecure());
const transformClient = new pacote.transform.DataTransformService(
  TRANSFORM_ADDR,
  grpc.credentials.createInsecure()
);

function chamar(stub, servico, metodo, requisicao) {
  return new Promise((resolve, reject) => {
    const fim = grpcDuracao.startTimer({ service: servico, rpc: metodo });
    stub[metodo](requisicao, (err, resposta) => {
      fim();
      if (err) return reject(err);
      resolve(resposta);
    });
  });
}

// --- Autenticação ---
const app = express();
app.use(cors());
app.use(express.json());
// Serve o frontend estático na mesma origem (evita CORS e path-rewrite de API).
app.use(express.static(path.join(__dirname, '../frontend')));

function autenticarJWT(req, res, next) {
  const cabecalho = req.headers.authorization;
  if (!cabecalho) return res.status(401).json({ erro: 'Token ausente' });
  const token = cabecalho.split(' ')[1];

  const fim = jwtDuracao.startTimer();
  jwt.verify(token, pegarChave, { algorithms: ['RS256'] }, (err, decodificado) => {
    fim();
    if (err) return res.status(401).json({ erro: 'Token inválido ou expirado' });
    req.user = decodificado;
    next();
  });
}

const PERFIS = ['MEDICO', 'ESTAGIARIO', 'PESQUISADOR'];

// Role do realm; se ausente, cai para o prefixo do username (med./est./pes.).
function resolverRole(user) {
  const roles = (user.realm_access && user.realm_access.roles) || [];
  const achado = roles.map((r) => r.toUpperCase()).find((r) => PERFIS.includes(r));
  if (achado) return achado;
  const u = user.preferred_username || '';
  if (u.startsWith('med.')) return 'MEDICO';
  if (u.startsWith('est.')) return 'ESTAGIARIO';
  if (u.startsWith('pes.')) return 'PESQUISADOR';
  return '';
}

// --- Orquestração: Auth -> (Data) -> Transform ---
async function autorizar(req) {
  const username = req.user.preferred_username;
  const role = resolverRole(req.user);
  const decisao = await chamar(authClient, 'auth', 'AutorizarConsulta', {
    username,
    role,
    escopo: req.escopo || '',
    ids_pacientes: req.ids_pacientes || [],
    codigo_condicao: req.codigo_condicao || '',
    id_projeto: req.id_projeto || '',
  });
  return { username, role, decisao };
}

async function transformar(nivel, escopo, carga) {
  const resp = await chamar(transformClient, 'transform', 'TransformarParaFHIR', {
    nivel,
    escopo,
    ...carga,
  });
  return JSON.parse(resp.fhir_bundle_json);
}

// GET /api/pacientes/:id/resumo-clinico  — MEDICO (FULL) / ESTAGIARIO (PARTIAL)
app.get('/api/pacientes/:id/resumo-clinico', autenticarJWT, async (req, res) => {
  const fim = httpDuracao.startTimer({ route: 'pacientes_resumo' });
  try {
    const { role, decisao } = await autorizar({
      user: req.user,
      escopo: 'ResumoClinico',
      ids_pacientes: [req.params.id],
    });
    if (!decisao.permitido) {
      negadasTotal.inc({ role, motivo: decisao.motivo_negacao || 'negado' });
      fim({ perfil: role, status: 403 });
      return res.status(403).json({ erro: 'Acesso negado', motivo: decisao.motivo_negacao });
    }
    const dados = await chamar(dataClient, 'data', 'BuscarPacientes', {
      ids_pacientes: decisao.ids_autorizados,
      incluir_atendimentos: true,
      incluir_eventos: true,
    });
    const bundle = await transformar(decisao.nivel, 'ResumoClinico', { dados });
    fim({ perfil: role, status: 200 });
    res.json(bundle);
  } catch (err) {
    fim({ perfil: 'erro', status: 502 });
    res.status(502).json({ erro: 'Falha no pipeline', detalhe: err.message });
  }
});

// GET /api/coortes/estatisticas?projeto&condicao  — PESQUISADOR (AGGREGATED)
app.get('/api/coortes/estatisticas', autenticarJWT, async (req, res) => {
  const fim = httpDuracao.startTimer({ route: 'coortes_estatisticas' });
  try {
    const { role, decisao } = await autorizar({
      user: req.user,
      escopo: 'EstatisticasCoorte',
      codigo_condicao: req.query.condicao || '',
      id_projeto: req.query.projeto || '',
    });
    if (!decisao.permitido) {
      negadasTotal.inc({ role, motivo: decisao.motivo_negacao || 'negado' });
      fim({ perfil: role, status: 403 });
      return res.status(403).json({ erro: 'Acesso negado', motivo: decisao.motivo_negacao });
    }
    const agregado = await chamar(dataClient, 'data', 'AgregarCoorte', {
      codigo_condicao: req.query.condicao || '',
    });
    const relatorio = await transformar(decisao.nivel, 'EstatisticasCoorte', { agregado });
    fim({ perfil: role, status: 200 });
    res.json(relatorio);
  } catch (err) {
    fim({ perfil: 'erro', status: 502 });
    res.status(502).json({ erro: 'Falha no pipeline', detalhe: err.message });
  }
});

// GET /api/coortes/exames?projeto&condicao&limite  — PESQUISADOR (ANONYMIZED)
app.get('/api/coortes/exames', autenticarJWT, async (req, res) => {
  const fim = httpDuracao.startTimer({ route: 'coortes_exames' });
  try {
    const { role, decisao } = await autorizar({
      user: req.user,
      escopo: 'ExamesCoorte',
      codigo_condicao: req.query.condicao || '',
      id_projeto: req.query.projeto || '',
    });
    if (!decisao.permitido) {
      negadasTotal.inc({ role, motivo: decisao.motivo_negacao || 'negado' });
      fim({ perfil: role, status: 403 });
      return res.status(403).json({ erro: 'Acesso negado', motivo: decisao.motivo_negacao });
    }
    const dados = await chamar(dataClient, 'data', 'BuscarCoorte', {
      codigo_condicao: req.query.condicao || '',
      incluir_exames_por_paciente: true,
      limite_pacientes: Number(req.query.limite) || 100,
    });
    const bundle = await transformar(decisao.nivel, 'ExamesCoorte', { dados });
    fim({ perfil: role, status: 200 });
    res.json(bundle);
  } catch (err) {
    fim({ perfil: 'erro', status: 502 });
    res.status(502).json({ erro: 'Falha no pipeline', detalhe: err.message });
  }
});

// GET /api/projetos  — PESQUISADOR lista os próprios projetos (sem FHIR)
app.get('/api/projetos', autenticarJWT, async (req, res) => {
  const fim = httpDuracao.startTimer({ route: 'projetos' });
  try {
    const { username, role, decisao } = await autorizar({ user: req.user, escopo: 'MeusProjetos' });
    if (!decisao.permitido) {
      negadasTotal.inc({ role, motivo: decisao.motivo_negacao || 'negado' });
      fim({ perfil: role, status: 403 });
      return res.status(403).json({ erro: 'Acesso negado', motivo: decisao.motivo_negacao });
    }
    const lista = await chamar(dataClient, 'data', 'ListarProjetos', { username });
    fim({ perfil: role, status: 200 });
    res.json(lista);
  } catch (err) {
    fim({ perfil: 'erro', status: 502 });
    res.status(502).json({ erro: 'Falha no pipeline', detalhe: err.message });
  }
});

app.get('/healthz', (_req, res) => res.json({ ok: true }));

app.get('/metrics', async (_req, res) => {
  res.set('Content-Type', registro.contentType);
  res.end(await registro.metrics());
});

app.listen(PORT, () => {
  console.log(`API Gateway na porta ${PORT} | auth=${AUTH_ADDR} data=${DATA_ADDR} transform=${TRANSFORM_ADDR}`);
});
