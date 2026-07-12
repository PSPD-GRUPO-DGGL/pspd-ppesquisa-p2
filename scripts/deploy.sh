#!/usr/bin/env bash
# Aplica os manifests no namespace grupo-9, adaptando as imagens locais
# (pspd/<svc>) para o registry e trocando o imagePullPolicy para Always.
# O Secret pspd-db real deve existir ANTES (ver k8s/README.md).
#
#   REGISTRY=docker.io/SEU_USUARIO KUBECONFIG=../kubeconfig-grupo-9.yaml ./scripts/deploy.sh
set -euo pipefail

REGISTRY=${REGISTRY:?defina REGISTRY, ex.: docker.io/seu_usuario}
TAG=${TAG:-0.1.0}
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"

render() {
  sed -E \
    -e "s#image: pspd/([a-z]+):[0-9.]+#image: ${REGISTRY}/pspd-\1:${TAG}#" \
    -e "s#imagePullPolicy: IfNotPresent#imagePullPolicy: Always#" \
    "$1"
}

# O Secret tem credenciais reais e não está no git; aplicamos só se já existir.
if ! kubectl -n grupo-9 get secret pspd-db >/dev/null 2>&1; then
  echo "ERRO: crie o Secret pspd-db antes (DB_USER/DB_PASSWORD/ANON_SALT reais)." >&2
  echo "Ver o comando em k8s/README.md." >&2
  exit 1
fi

for f in auth-data transform gateway hpa pdb servicemonitors ingress; do
  echo ">> apply $f.yaml"
  render "$RAIZ/k8s/app/$f.yaml" | kubectl apply -f -
done

echo "OK. Confira: kubectl -n grupo-9 get pods,svc,ingress,hpa"
