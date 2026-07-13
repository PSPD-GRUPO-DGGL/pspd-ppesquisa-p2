# Resultados dos testes de carga

Dados brutos da matriz de experimentos executada no cluster real do professor (`kiriland.unb.br`, namespace `grupo-9`). Metodologia completa em `docs/relatorio-final.md`, Seções 2.1 a 2.4.

## Execução

`scripts/exp_runner.sh` reconfigura o número de réplicas de cada serviço via `kubectl scale`, dispara o k6 contra `https://kiriland.unb.br/grupo9` a partir da VM da disciplina, e `scripts/coletar_metricas.sh` consolida throughput, latência e erro (do k6) com CPU, memória e contagem de pods (do `kubectl top`) numa linha de CSV por corrida.

## `matriz-final/matriz.csv`

Uma linha por experimento e nível de VU. Colunas: `exp, vus, throughput_rps, lat_avg_ms, lat_p95_ms, lat_p99_ms, erro_rate, cpu_total_m, mem_total_mi, pods`.

| Config. testada | Réplicas (auth/data/transform/gw) | Variável isolada |
|---|---|---|
| E0 | 1/1/1/1 | baseline sem escala |
| E2 | 1/1/3/1 | Transform×3 |
| E3 | 1/3/1/1 | Data×3 |
| E4 | 3/3/3/3 | cadeia inteira |

`erro_rate` conta apenas falhas reais (5xx, timeout). O caminho DENY (403 de autorização, 5% da carga mista) não conta como erro.

## `matriz-final/E5_pods.csv`

Autoscaling por HPA. `timestamp_unix, pods_running`, amostrado a cada 10s durante a rampa de 10 a 1000 VUs. Os pods sobem de 4 para 12 em cerca de 3 minutos e ficam estáveis em 12 pelo resto da rampa, mesmo com a carga ainda subindo.

## Leitura dos números

A CPU nunca passa de 900m em nenhuma linha do CSV, menos de 15% da cota do namespace (6000m de `limits.cpu`). O gargalo não é processamento.

Escalar um serviço sozinho ajuda pouco. A 1000 VUs sustentados, o Transform×3 (E2) chega a 40,73 req/s contra 35,95 do baseline, um ganho de 13%. O Data×3 (E3) chega a 38,25, um ganho de 6%.

Escalar a cadeia inteira (E4) muda o quadro: 48,69 req/s, ganho de 35%. O p95 cai de 21.715ms para 12.511ms. O erro real cai de 10,44% para 6,73%. O gargalo está distribuído entre os hops sequenciais Gateway, Auth, Data e Transform, não concentrado num serviço.

O HPA parou de escalar em 12 pods, não nos 17 permitidos pelos máximos configurados. Os eventos do Kubernetes mostram 8 minutos sem nenhum registro de "CPU acima do alvo" antes do platô, e o scale-down registra `"All metrics below target"`. Isso indica que 12 réplicas já satisfaziam o alvo de CPU. O RBAC do namespace impede confirmar se havia ou não capacidade física de sobra no cluster compartilhado por 10 grupos, então essa leitura fica sem confirmação independente.

## O que não está aqui

Os JSONs brutos de cada corrida do k6 e o resumo completo do E5 ficam fora do `.gitignore` (`resultados/*.json`) por serem artefatos volumosos. Os números que importam já estão extraídos em `docs/relatorio-final.md`.
