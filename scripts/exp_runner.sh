#!/usr/bin/env bash
# Orquestra a matriz de experimentos (E0–E5) na VM da disciplina.
# k6 = gerador de carga; kubectl = configura réplicas/HPA entre experimentos.
# Ambos rodam AQUI (a VM alcança a URL pública :443 e a API do cluster :8141).
#
# Uso (na VM, após instalar kubectl e ter o kubeconfig):
#   export KUBECONFIG=~/kubeconfig-grupo-9.yaml
#   export K6_PASSWORD_MEDICO=PseudoPEP2026! \
#          K6_PASSWORD_ESTAGIARIO=PseudoPEP2026! \
#          K6_PASSWORD_PESQUISADOR=PseudoPEP2026!
#   ./scripts/exp_runner.sh E0            # um experimento
#   ./scripts/exp_runner.sh todos         # E0..E5 em sequência
set -euo pipefail

: "${KUBECONFIG:?defina KUBECONFIG (ex.: ~/kubeconfig-grupo-9.yaml)}"
export KUBECONFIG
NS=${NS:-grupo-9}
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT=${SCRIPT:-$RAIZ/k6/cenarios/d_carga_mista.js}   # carga mista realista
OUT=${OUT:-$RAIZ/resultados/$(date +%Y%m%d-%H%M%S)}
VUS_LIST=${VUS_LIST:-"10 50 100 500 1000"}
DURATION=${DURATION:-60s}
mkdir -p "$OUT"

# Coordenadas do ambiente real (defaults corretos; sobrescreva por env se preciso).
export GATEWAY=${GATEWAY:-https://kiriland.unb.br/grupo9}
export KEYCLOAK=${KEYCLOAK:-https://kiriland.unb.br/keycloak}
export REALM=${REALM:-grupo09}
export CLIENT_ID=${CLIENT_ID:-pseudopep-frontend}
export K6_PROJECT=${K6_PROJECT:-PRJ01_G09}
export K6_CONDITION=${K6_CONDITION:-DIABETES}
export K6_MED_PATIENT=${K6_MED_PATIENT:-P090000002}
export K6_TRAINEE_PATIENT=${K6_TRAINEE_PATIENT:-P090000030}
export K6_DENIED_PATIENT=${K6_DENIED_PATIENT:-P090000001}
: "${K6_PASSWORD_MEDICO:?exporte K6_PASSWORD_MEDICO}"
: "${K6_PASSWORD_ESTAGIARIO:?exporte K6_PASSWORD_ESTAGIARIO}"
: "${K6_PASSWORD_PESQUISADOR:?exporte K6_PASSWORD_PESQUISADOR}"

SERVICOS="auth-service data-service transform-service api-gateway"

hpa_off() { kubectl -n "$NS" delete hpa $SERVICOS --ignore-not-found >/dev/null 2>&1 || true; }
hpa_on()  { kubectl -n "$NS" apply -f "$RAIZ/k8s/app/hpa.yaml" >/dev/null; }

escala() { # $1=auth $2=data $3=transform $4=gateway
  kubectl -n "$NS" scale deploy/auth-service      --replicas="$1" >/dev/null
  kubectl -n "$NS" scale deploy/data-service      --replicas="$2" >/dev/null
  kubectl -n "$NS" scale deploy/transform-service --replicas="$3" >/dev/null
  kubectl -n "$NS" scale deploy/api-gateway       --replicas="$4" >/dev/null
  for s in $SERVICOS; do kubectl -n "$NS" rollout status "deploy/$s" --timeout=180s >/dev/null; done
  sleep 5   # deixa métricas/HPA estabilizarem
}

roda_niveis() { # $1=nome do experimento — carga CONSTANTE por nível de VU
  local exp=$1 v
  for v in $VUS_LIST; do
    echo ">> [$exp] k6 constante VUs=$v (${DURATION})"
    K6_VUS=$v K6_DURATION=$DURATION k6 run --summary-trend-stats="min,avg,med,max,p(90),p(95),p(99)" --summary-export="$OUT/${exp}_vus${v}.json" "$SCRIPT" || true
    local linhas_antes; linhas_antes=$([ -f "$OUT/matriz.csv" ] && wc -l < "$OUT/matriz.csv" || echo 0)
    bash "$RAIZ/scripts/coletar_metricas.sh" "$exp" "$v" "$OUT/${exp}_vus${v}.json" "$OUT/matriz.csv"
    local linhas_depois; linhas_depois=$(wc -l < "$OUT/matriz.csv")
    if [ "$linhas_depois" -le "$linhas_antes" ]; then
      echo "AVISO: coletor NÃO adicionou linha ao CSV (verifique $OUT/${exp}_vus${v}.json)" >&2
    fi
  done
}

roda_rampa_hpa() { # $1=nome — rampa 10->1000 com HPA ligado, amostrando pods
  local exp=$1
  ( while true; do
      echo "$(date +%s),$(kubectl -n "$NS" get pods -l 'app in (auth-service,data-service,transform-service,api-gateway)' --no-headers 2>/dev/null | grep -c Running)" >> "$OUT/${exp}_pods.csv"
      sleep 10
    done ) & local sampler=$!
  echo ">> [$exp] k6 RAMPA 10->1000 com HPA (amostrando pods a cada 10s)"
  k6 run --summary-trend-stats="min,avg,med,max,p(90),p(95),p(99)" --summary-export="$OUT/${exp}_summary.json" "$SCRIPT" || true
  kill "$sampler" 2>/dev/null || true
}

experimento() {
  case "$1" in
    E0|E1) hpa_off; escala 1 1 1 1; roda_niveis "$1" ;;   # baseline 1 réplica
    E2)    hpa_off; escala 1 1 3 1; roda_niveis E2 ;;      # Transform x3 (stateless)
    E3)    hpa_off; escala 1 3 1 1; roda_niveis E3 ;;      # Data x3 (Postgres único)
    E4)    hpa_off; escala 3 3 3 3; roda_niveis E4 ;;      # tudo x3
    E5)    hpa_off; escala 1 1 1 1; hpa_on; roda_rampa_hpa E5 ;;  # autoscaling
    *) echo "experimento desconhecido: $1 (use E0|E2|E3|E4|E5|todos)"; exit 1 ;;
  esac
}

echo "Saída em: $OUT"
if [ "${1:-todos}" = "todos" ]; then
  for e in E0 E2 E3 E4 E5; do experimento "$e"; done
else
  experimento "$1"
fi
echo "OK. Matriz consolidada: $OUT/matriz.csv"
