#!/usr/bin/env bash
# Build e push das imagens dos quatro serviços para um registry que o cluster do
# professor consiga puxar (o cluster baixa imagens públicas do Docker Hub).
#
#   REGISTRY=docker.io/SEU_USUARIO ./scripts/build_push.sh
#   REGISTRY=ghcr.io/sua-org TAG=0.2.0 ./scripts/build_push.sh
set -euo pipefail

REGISTRY=${REGISTRY:?defina REGISTRY, ex.: docker.io/seu_usuario}
TAG=${TAG:-0.1.0}

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"

dockerfile_de() {
  case "$1" in
    auth) echo servicos/auth/Dockerfile ;;
    data) echo servicos/data/Dockerfile ;;
    transform) echo servicos/transform/Dockerfile ;;
    gateway) echo gateway/Dockerfile ;;
  esac
}

for svc in auth data transform gateway; do
  img="$REGISTRY/pspd-$svc:$TAG"
  echo ">> build $img"
  docker build -f "$(dockerfile_de "$svc")" -t "$img" .
  echo ">> push $img"
  docker push "$img"
done

echo "OK: imagens publicadas em $REGISTRY (tag $TAG)"
