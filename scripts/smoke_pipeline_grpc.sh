#!/usr/bin/env bash
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-${RAIZ}/.venv/bin/python}"

for nome in DB_HOST DB_NAME DB_USER DB_PASSWORD; do
  if [ -z "${!nome:-}" ]; then
    echo "erro: variável obrigatória ausente: ${nome}" >&2
    exit 2
  fi
done

if [ -z "${ANON_SALT:-}" ]; then
  echo "erro: ANON_SALT ausente; defina um salt de teste antes de rodar" >&2
  echo "exemplo: export ANON_SALT=smoke-local-nao-usar-em-producao" >&2
  exit 2
fi

if [ ! -x "$PY" ]; then
  echo "erro: ambiente Python não encontrado em $PY" >&2
  echo "rode primeiro: ./scripts/test_python_services.sh" >&2
  exit 2
fi

"${RAIZ}/scripts/gen_protos.sh" "$PY"

echo "== descobrindo casos de pipeline no banco =="
eval "$("$PY" - <<'PY'
import os
import shlex

import psycopg

conninfo = (
    f"host={os.environ['DB_HOST']} "
    f"port={os.environ.get('DB_PORT', '5432')} "
    f"dbname={os.environ['DB_NAME']} "
    f"user={os.environ['DB_USER']} "
    f"password={os.environ['DB_PASSWORD']}"
)


def emit(nome, valor):
    print(f"export {nome}={shlex.quote(str(valor))}")


with psycopg.connect(conninfo) as conn:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT username, patient_id
            FROM user_patient_assignments
            WHERE assignment_type = 'ATTENDING'
              AND active IS TRUE
            ORDER BY username, patient_id
            LIMIT 1
        """)
        med_user, med_patient = cur.fetchone()

        cur.execute("""
            SELECT patient_id
            FROM patients p
            WHERE NOT EXISTS (
                SELECT 1
                FROM user_patient_assignments a
                WHERE a.username = %s
                  AND a.patient_id = p.patient_id
                  AND a.assignment_type = 'ATTENDING'
                  AND a.active IS TRUE
            )
            ORDER BY patient_id
            LIMIT 1
        """, (med_user,))
        denied_patient = cur.fetchone()[0]

        cur.execute("""
            SELECT researcher_username, project_id, target_condition_code
            FROM projects
            WHERE status = 'APPROVED'
              AND valid_until >= CURRENT_DATE
            ORDER BY researcher_username, project_id
            LIMIT 1
        """)
        pes_user, project_id, condition = cur.fetchone()

emit("AUTH_SMOKE_MED_USER", os.environ.get("AUTH_SMOKE_MED_USER", med_user))
emit("AUTH_SMOKE_MED_PATIENT", os.environ.get("AUTH_SMOKE_MED_PATIENT", med_patient))
emit(
    "AUTH_SMOKE_MED_DENIED_PATIENT",
    os.environ.get("AUTH_SMOKE_MED_DENIED_PATIENT", denied_patient),
)
emit("AUTH_SMOKE_PES_USER", os.environ.get("AUTH_SMOKE_PES_USER", pes_user))
emit("AUTH_SMOKE_PROJECT", os.environ.get("AUTH_SMOKE_PROJECT", project_id))
emit("AUTH_SMOKE_CONDITION", os.environ.get("AUTH_SMOKE_CONDITION", condition))
PY
)"

echo "medico=${AUTH_SMOKE_MED_USER} paciente=${AUTH_SMOKE_MED_PATIENT} paciente_negado=${AUTH_SMOKE_MED_DENIED_PATIENT}"
echo "pesquisador=${AUTH_SMOKE_PES_USER} projeto=${AUTH_SMOKE_PROJECT} condicao=${AUTH_SMOKE_CONDITION}"

cleanup() {
  jobs -p | xargs -r kill
}
trap cleanup EXIT

cd "$RAIZ"

echo "== subindo Auth Service =="
PYTHONPATH=servicos/auth GRPC_PORT=50051 METRICS_PORT=18051 "$PY" servicos/auth/server.py &

echo "== subindo Data Service =="
PYTHONPATH=servicos/data GRPC_PORT=50052 METRICS_PORT=18052 "$PY" servicos/data/server.py &

echo "== subindo Transform Service =="
PYTHONPATH=servicos/transform GRPC_PORT=50053 METRICS_PORT=18053 "$PY" servicos/transform/server.py &

sleep 3

echo "== pipeline Auth -> Data -> Transform =="
PYTHONPATH=servicos/auth:servicos/data:servicos/transform "$PY" scripts/pipeline_smoke.py

echo "== metrics Transform =="
"$PY" - <<'PY'
from urllib.request import urlopen
body = urlopen("http://localhost:18053/metrics", timeout=5).read().decode()
assert "transform_requests_total" in body
print("transform /metrics OK")
PY

echo "OK"
