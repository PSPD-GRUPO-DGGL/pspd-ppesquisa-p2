#!/usr/bin/env bash
# Gera os stubs Python a partir de proto/ para cada serviço.
# Stubs não são versionados; rode isto após alterar proto/.
#
# Uso:  ./scripts/gen_protos.sh [caminho-do-python]

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${1:-${RAIZ}/.venv/bin/python}"

if ! "$PY" -c "import grpc_tools" 2>/dev/null; then
    echo "erro: grpc_tools não encontrado em $PY" >&2
    echo "instale com: $PY -m pip install grpcio-tools==1.64.1" >&2
    exit 1
fi

for destino in servicos/transform servicos/auth servicos/data; do
    [ -d "${RAIZ}/${destino}" ] || continue
    "$PY" -m grpc_tools.protoc \
        -I"${RAIZ}/proto" \
        --python_out="${RAIZ}/${destino}" \
        --grpc_python_out="${RAIZ}/${destino}" \
        "${RAIZ}"/proto/*.proto
    echo "stubs gerados em ${destino}"
done
