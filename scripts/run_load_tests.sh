#!/usr/bin/env bash
# scripts/run_load_tests.sh
set -euo pipefail

# Garante que a pasta de relatorios locais exista no PC
mkdir -p resultados

# URL publica do Ingress do seu Grupo 9 no cluster da UnB
TARGET_URL="https://kiriland.unb.br/grupo9"

echo "================================================================"
echo "    K6 LOAD TEST WRAPPER - CLUSTER UNB KIRILAND (GRUPO 9)      "
echo "================================================================"
echo "Escolha o cenario de teste de carga:"
echo "1) Médico (FULL) - a_medico_full.js"
echo "2) Pesquisador (AGGREGATED) - b_pesquisador_aggregated.js"
echo "3) Pesquisador (ANONYMIZED) - c_pesquisador_anonymized.js"
echo "4) Carga Mista (RAMPA) - d_carga_mista.js"
echo "================================================================"
read -p "Opcao (1-4): " OPCAO

case $OPCAO in
  1) FILE="a_medico_full.js" ;;
  2) FILE="b_pesquisador_aggregated.js" ;;
  3) FILE="c_pesquisador_anonymized.js" ;;
  4) FILE="d_carga_mista.js" ;;
  *) echo "Opcao invalida!"; exit 1 ;;
esac

echo "Executando k6/cenarios/$FILE contra: $TARGET_URL"

# Executa o k6 local usando o caminho correto
./k6.exe run \
  --summary-export="resultados/resultado_${FILE%.js}_real_cluster.json" \
  "k6/cenarios/$FILE" \
  -e URL="$TARGET_URL"

echo "================================================================"
echo "Teste finalizado! Relatorio correspondente salvo em: resultados/"
echo "================================================================"