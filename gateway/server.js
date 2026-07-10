const express = require('express');
const jwt = require('jsonwebtoken');
const jwksClient = require('jwks-rsa');
const client = require('prom-client');
const axios = require('axios');
const cors = require('cors');

const app = express();
app.use(express.json());
app.use(cors()); // Permite que o index.html faça chamadas para esta API

// ==========================================
// 1. CONFIGURAÇÃO DO PROM-CLIENT (MÉTRICAS)
// ==========================================
client.collectDefaultMetrics({ register: client.register });

const httpRequestDurationMicroseconds = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Duração das requisições HTTP em segundos',
  labelNames: ['method', 'route', 'status_code'],
  buckets: [0.1, 0.3, 0.5, 0.7, 1, 3, 5]
});

app.use((req, res, next) => {
  const end = httpRequestDurationMicroseconds.startTimer();
  res.on('finish', () => {
    end({ method: req.method, route: req.route ? req.route.path : req.path, status_code: res.statusCode });
  });
  next();
});

app.get('/metrics', async (req, res) => {
  res.set('Content-Type', client.register.contentType);
  res.end(await client.register.metrics());
});

// ==========================================
// 2. CONFIGURAÇÃO DO JWKS (VALIDAÇÃO JWT)
// ==========================================
const jwks = jwksClient({
  jwksUri: process.env.JWKS_URI || 'http://localhost:8080/realms/hospital/protocol/openid-connect/certs',
  cache: true,
  rateLimit: true,
});

function getKey(header, callback) {
  jwks.getSigningKey(header.kid, function(err, key) {
    if (err) return callback(err);
    callback(null, key.getPublicKey());
  });
}

const validateJWT = (req, res, next) => {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Token não fornecido' });
  }

  const token = authHeader.split(' ')[1];
  
  // MOCK PARA DESENVOLVIMENTO: Ignora Keycloak se DEV_MODE estiver ativo
  if (process.env.DEV_MODE === 'true') {
      req.user = { preferred_username: 'dev_user', realm_access: { roles: ['MEDICO'] } };
      return next();
  }

  jwt.verify(token, getKey, { algorithms: ['RS256'] }, (err, decoded) => {
    if (err) return res.status(401).json({ error: 'Token inválido' });
    req.user = decoded;
    next();
  });
};

// ==========================================
// 3. ORQUESTRAÇÃO DE SERVIÇOS
// ==========================================
app.get('/api/patients/:id', validateJWT, async (req, res) => {
  const patientId = req.params.id;
  const username = req.user.preferred_username;
  const role = req.user.realm_access?.roles[0] || 'DESCONHECIDO';

  try {
    const authRes = await axios.post('http://auth-service:5001/authorize', { username, role, patientId });
    if (authRes.data.decision === 'DENY') return res.status(403).json({ error: 'Acesso negado' });

    const dataRes = await axios.get(`http://patient-data:5002/data/${patientId}`);
    const fhirRes = await axios.post('http://transform-service:5003/transform', { data: dataRes.data, level: authRes.data.accessLevel });

    return res.json(fhirRes.data);

  } catch (error) {
    console.log("Serviços internos ausentes. Utilizando MOCK de resposta...");
    
    // MOCK: Resposta simulada para validar o Frontend sem os serviços do Danilo
    const mockFhirResponse = {
      resourceType: "Patient",
      id: patientId,
      name: [{ text: role === 'ESTAGIARIO' ? "J. S." : "João da Silva" }],
      birthDate: "1970-05-10",
      gender: "male",
      _mocked: true,
      _userContext: { username, role }
    };
    
    return res.json(mockFhirResponse);
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`API Gateway na porta ${PORT}`));