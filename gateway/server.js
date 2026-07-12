const express = require('express');
const cors = require('cors');
const jwt = require('jsonwebtoken');
const jwksClient = require('jwks-rsa');
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');

const app = express();
app.use(cors());
app.use(express.json());

// 1. Configuração do Keycloak do Grupo 09
const client = jwksClient({
  jwksUri: 'https://kiriland.unb.br/keycloak/realms/grupo09/protocol/openid-connect/certs'
});

function getKey(header, callback) {
  client.getSigningKey(header.kid, function(err, key) {
    const signingKey = key.publicKey || key.rsaPublicKey;
    callback(null, signingKey);
  });
}

// Middleware de Autenticação JWT
const autenticarJWT = (req, res, next) => {
  const authHeader = req.headers.authorization;
  if (!authHeader) return res.status(401).json({ erro: 'Token ausente' });

  const token = authHeader.split(' ')[1];
  jwt.verify(token, getKey, { algorithms: ['RS256'] }, (err, decoded) => {
    if (err) return res.status(401).json({ erro: 'Token inválido ou expirado' });
    req.user = decoded; // Salva os dados do usuário (ex: med.cardoso) na requisição
    next();
  });
};

// 2. Carregamento dos gRPCs (stubs)
// Obs: Assumindo que a pasta proto está acessível. Ajuste o caminho se necessário.
const packageDefinition = protoLoader.loadSync(
  ['../proto/auth.proto', '../proto/data.proto', '../proto/transform.proto'],
  { keepCase: true, longs: String, enums: String, defaults: true, oneofs: true }
);
const protoDescriptor = grpc.loadPackageDefinition(packageDefinition);

// Conexão com os microsserviços (usando os nomes de serviço do K8s ou localhost)
const authClient = new protoDescriptor.auth.AuthService('localhost:50051', grpc.credentials.createInsecure());
const dataClient = new protoDescriptor.data.DataService('localhost:50052', grpc.credentials.createInsecure());
const transformClient = new protoDescriptor.transform.TransformService('localhost:50053', grpc.credentials.createInsecure());

// 3. Rota de Orquestração (Pipeline Auth -> Data -> Transform)
app.get('/api/consultar-dados', autenticarJWT, (req, res) => {
  const username = req.user.preferred_username; // Extraído do Token do Keycloak

  // Passo A: Auth
  authClient.AutorizarConsulta({ username: username }, (errAuth, authRes) => {
    if (errAuth) return res.status(403).json({ erro: 'Acesso negado no Auth', detalhe: errAuth.message });

    // Passo B: Data
    dataClient.BuscarDados({ paciente_ids: authRes.pacientes_permitidos }, (errData, dataRes) => {
      if (errData) return res.status(500).json({ erro: 'Erro ao buscar dados', detalhe: errData.message });

      // Passo C: Transform (Anonimização, útil se for perfil PESQUISADOR)
      if (req.user.realm_access?.roles.includes('PESQUISADOR')) {
        transformClient.AnonimizarDados({ dados_clinicos: dataRes.dados }, (errTrans, transRes) => {
          if (errTrans) return res.status(500).json({ erro: 'Erro na anonimização', detalhe: errTrans.message });
          res.json(transRes.dados_anonimizados);
        });
      } else {
        // Se for médico/estagiário, devolve o dado bruto
        res.json(dataRes.dados);
      }
    });
  });
});

const PORT = 3000;
app.listen(PORT, () => {
  console.log(`🚀 API Gateway rodando na porta ${PORT}`);
});