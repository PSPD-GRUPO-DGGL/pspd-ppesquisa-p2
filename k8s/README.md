# Kubernetes

Os manifests existentes em `k8s/app/` e `k8s/infra/` nasceram para laboratório local com `kind`, mocks e namespace `default`. Eles **não** são a forma final de entrega no cluster da disciplina.

## Alvo final

Para a entrega, criar ou ajustar manifests para:

- namespace/contexto `grupo-9`;
- URL pública `https://kiriland.unb.br/grupo9`;
- banco institucional `pseudopep_g09`, acessado por `Secret`;
- Keycloak institucional `https://kiriland.unb.br/keycloak/realms/grupo09`;
- `requests` e `limits` em todos os containers;
- Services internos para Gateway/Auth/Data/Transform;
- endpoint `/metrics` em todos os serviços reais;
- HPA apontando para Deployments reais, não mocks.

Não versionar segredos. Um arquivo final pode referenciar `Secret`, mas os valores reais devem ser criados fora do git.

## Regra prática

- `k8s/infra/postgres.yaml` e `k8s/infra/keycloak.yaml`: uso local, não aplicar no cluster final.
- `k8s/app/mocks.yaml`: uso local para ensaio de HPA/carga, não conta como validação funcional final.
- `k8s/app/auth-data.yaml`: base inicial dos serviços reais Auth/Data para `grupo-9`.
- `k8s/app/secret-db.example.yaml`: exemplo de chaves esperadas; copiar para fora do git e preencher com valores reais antes de aplicar.
- `k8s/app/hpa*.yaml`: reaproveitar a ideia, mas trocar `namespace`, `scaleTargetRef` e métricas para os serviços reais antes da entrega.
