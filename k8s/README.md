# Kubernetes — deploy no namespace `grupo-9`

Manifests da entrega, no namespace `grupo-9` do cluster do professor. Exposto em `https://kiriland.unb.br/grupo9`.

## Split dev × entrega

- **`k8s/app/`** — entrega no `grupo-9` (abaixo).
- **`k8s/infra/`** (`postgres.yaml`, `keycloak.yaml`, `kind-config.yaml`) — **só laboratório local** com `kind`. O professor já provê banco e Keycloak; **não aplicar no `grupo-9`**. Servem também à seção "montagem do K8s" do relatório.
- **`k8s/app/mocks.yaml`** — dummies (`httpbin`) para ensaio de HPA local; **aposentado** pela entrega real, não aplicar no `grupo-9`.

## Manifests da entrega (`k8s/app/`)

| Arquivo | Conteúdo |
|---|---|
| `auth-data.yaml` | Deployments/Services de Auth (50051) e Data (50052), com probes |
| `transform.yaml` | Deployment/Service do Transform (50053), `ANON_SALT` via Secret |
| `gateway.yaml` | Deployment/Service do Gateway (3000) — serve também o frontend estático |
| `ingress.yaml` | Ingress `/grupo9` → gateway (assume ingress-nginx) |
| `servicemonitors.yaml` | ServiceMonitors dos quatro serviços |
| `hpa.yaml` | HPAs recalibrados à cota (auth 4, data 5, transform 5, gateway 3) |
| `pdb.yaml` | PodDisruptionBudgets |
| `secret-db.example.yaml` | Chaves esperadas do Secret (preencher fora do git) |

Todas as imagens (`pspd/auth|data|transform|gateway`) expõem métricas; Auth/Data/Transform em `:8000/metrics`, Gateway em `:3000/metrics`.

## Runbook

**1. Imagens no registry** (o cluster baixa imagens públicas do Docker Hub):
```
REGISTRY=docker.io/SEU_USUARIO ./scripts/build_push.sh
```

**2. Secret real** (fora do git — tem credenciais):
```
kubectl -n grupo-9 create secret generic pspd-db \
  --from-literal=DB_HOST=192.168.122.1 \
  --from-literal=DB_PORT=5432 \
  --from-literal=DB_NAME=pseudopep_g09 \
  --from-literal=DB_USER=grupo09_user \
  --from-literal=DB_PASSWORD='***' \
  --from-literal=ANON_SALT='***'
```

**3. Aplicar** (adapta imagem/registry e pull policy, aplica na ordem certa):
```
REGISTRY=docker.io/SEU_USUARIO KUBECONFIG=../kubeconfig-grupo-9.yaml ./scripts/deploy.sh
```

**4. Verificar:**
```
kubectl -n grupo-9 get pods,svc,ingress,hpa
curl -k https://kiriland.unb.br/grupo9/healthz
```

## Antes de valer a nota — confirmar

- **Label do ServiceMonitor**: `servicemonitors.yaml` usa `release: kube-prometheus-stack`. Descobrir o valor real do `serviceMonitorSelector` do operator do professor; sem ele, nada é raspado:
  ```
  kubectl get prometheus -A -o jsonpath='{.items[0].spec.serviceMonitorSelector}'
  ```
- **Ingress**: `ingress.yaml` assume ingress-nginx (`rewrite-target: /$2`). Se o controller for outro, ajustar a anotação e a `ingressClassName`.
- **Cota**: `kubectl -n grupo-9 describe resourcequota` — a soma de `limits` × réplicas de HPA cabe em 6 CPU / 7Gi.
