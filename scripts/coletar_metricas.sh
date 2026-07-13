#!/usr/bin/env bash
# Consolida uma linha da matriz: métricas de carga (do resumo do k6) + recursos
# (do metrics-server via kubectl top) + contagem de pods. Anexa ao CSV.
# Chamado pelo exp_runner.sh ao fim de cada corrida.
#   coletar_metricas.sh <exp> <vus> <summary.json> <csv_saida>
#
# NB: NÃO usar pipefail — grep retorna exit 1 quando nenhum pod bate no filtro,
# o que abortava o script silenciosamente antes de escrever no CSV (bug original).
set -eu

EXP=$1; VUS=$2; SUMMARY=$3; CSV=$4
NS=${NS:-grupo-9}

if [ ! -f "$CSV" ]; then
  echo "exp,vus,throughput_rps,lat_avg_ms,lat_p95_ms,lat_p99_ms,erro_rate,cpu_total_m,mem_total_mi,pods" > "$CSV"
fi

# --- métricas de carga, do resumo do k6 ---
# O formato do --summary-export varia entre versões do k6:
#   - Versões mais novas: m[metric]["values"][sub]  (com envelope type/contains/values)
#   - Versão da VM:       m[metric][sub]            (flat, sem envelope)
# O parser tenta "values" primeiro; se não existir, acessa direto.
read -r TP AVG P95 P99 ERR < <(python3 - "$SUMMARY" <<'PY'
import json, sys
try:
    m = json.load(open(sys.argv[1]))["metrics"]
except Exception:
    print("0 0 0 0 0"); sys.exit()
def g(metric, sub, d=0.0):
    entry = m.get(metric, {})
    if "values" in entry:
        entry = entry["values"]
    return float(entry.get(sub, d))
tp  = g("http_reqs", "rate")
avg = g("http_req_duration", "avg")
p95 = g("http_req_duration", "p(95)")
p99 = g("http_req_duration", "p(99)")
err = g("http_req_failed", "rate")   # taxa de falha (0..1)
print(f"{tp:.2f} {avg:.2f} {p95:.2f} {p99:.2f} {err:.4f}")
PY
)

# --- recursos: soma de CPU(m) e memória(Mi) dos 4 serviços ---
# kubectl top imprime "42m" / "128Mi"; awk `+0` descarta o sufixo texto.
# Se kubectl top ou grep falharem (metrics-server lento, sem pods), assume 0 0.
CPU=0; MEM=0
if _raw=$(kubectl -n "$NS" top pods --no-headers 2>/dev/null); then
  read -r CPU MEM < <(echo "$_raw" \
    | grep -E 'auth-service|data-service|transform-service|api-gateway' \
    | awk '{c += $2 + 0; m += $3 + 0} END {printf "%d %d", c, m}') || true
fi

PODS=$(kubectl -n "$NS" get pods -l 'app in (auth-service,data-service,transform-service,api-gateway)' \
  --no-headers 2>/dev/null | grep -c Running || echo 0)

echo "$EXP,$VUS,$TP,$AVG,$P95,$P99,$ERR,${CPU:-0},${MEM:-0},$PODS" >> "$CSV"
echo "   coletado: $EXP vus=$VUS tp=${TP}rps p95=${P95}ms err=${ERR} cpu=${CPU:-0}m mem=${MEM:-0}Mi pods=$PODS"
