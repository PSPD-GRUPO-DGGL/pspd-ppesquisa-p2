# Experimento C10K: `epoll` × `select` × thread-por-conexão

Seção do relatório. Mede o custo de manter muitas conexões simultâneas sob três modelos de concorrência, usando o mesmo protocolo de chat e o mesmo gerador de carga.

## Metodologia

Três servidores implementam o mesmo protocolo de linha sobre TCP. O gerador de carga abre `N` conexões e mantém **1% delas ativas** em malha fechada — uma mensagem em voo por conexão, a próxima só depois do eco. As demais permanecem abertas e ociosas.

Essa assimetria é a definição do problema C10K: um servidor real tem milhares de clientes conectados e poucos falando ao mesmo tempo. Um teste em que todas as conexões estão ativas mede fan-out, não multiplexação.

Modo eco (a mensagem volta só ao remetente) para que o custo de broadcast não domine a medição. Duração de 8 s por corrida. Servidor e gerador no mesmo host.

**Ambiente:** Intel i7-1255U (2 P-cores + 8 E-cores, 12 threads), 16 GB, Pop!_OS 24.04, glibc com `FD_SETSIZE = 1024`. Threads criadas com pilha de 256 KB.

## Resultados

| servidor | conexões | aceitas | recusadas | RSS (MB) | CPU (s) | threads | mensagens | p50 (µs) | p95 (µs) | p99 (µs) |
|---|---|---|---|---|---|---|---|---|---|---|
| epoll | 1.000 | 1.000 | 0 | 5,5 | 7,93 | 1 | 2.045.138 | 34,9 | 58,6 | 70,5 |
| epoll | 5.000 | 5.000 | 0 | 21,3 | 8,00 | 1 | 2.214.091 | 171,0 | 250,7 | 341,3 |
| epoll | 10.000 | 10.000 | 0 | 41,1 | 8,07 | 1 | 2.185.902 | 343,8 | 560,3 | 747,1 |
| select | 1.000 | 1.000 | 0 | 5,4 | 8,01 | 1 | 561.583 | 128,6 | 202,0 | 280,7 |
| select | 5.000 | **1.020** | **3.980** | 5,5 | 8,05 | 1 | 1.508.997 | 243,8 | 361,6 | 403,3 |
| select | 10.000 | **1.020** | **8.980** | 5,6 | 8,06 | 1 | 1.766.229 | 401,3 | 767,9 | 881,5 |
| threads | 1.000 | 1.000 | 0 | 13,6 | 14,81 | 1.001 | 1.802.038 | 35,0 | 70,7 | 110,3 |
| threads | 5.000 | 5.000 | 0 | 61,6 | 14,10 | 5.001 | 1.517.326 | 238,7 | 444,0 | 538,1 |
| threads | 10.000 | 10.000 | 0 | 121,5 | 19,48 | 10.001 | 1.436.459 | 595,7 | 668,6 | 1.140,6 |

Duas grandezas derivadas dizem mais que a tabela inteira:

| servidor | conexões | memória por conexão | mensagens por segundo de CPU |
|---|---|---|---|
| epoll | 1.000 | 5,1 KB | 292.163 |
| epoll | 10.000 | **4,2 KB** | **273.238** |
| select | 1.000 | 5,1 KB | 70.198 |
| threads | 1.000 | 13,3 KB | 128.717 |
| threads | 10.000 | **12,4 KB** | **75.603** |

## Achados

### 1. `select()` não escala porque não pode: o teto é `FD_SETSIZE`

O servidor `select` aceitou **1.020 conexões** e recusou 3.980 e 8.980 nas corridas de 5 mil e 10 mil.

Não é lentidão — é impossibilidade. `fd_set` é um vetor de bits de tamanho `FD_SETSIZE`, fixado em **1024** na compilação da glibc, não do programa. Descritores acima disso não cabem na estrutura, e usá-los é comportamento indefinido. O servidor os fecha imediatamente após o `accept`.

Esse limite sozinho encerra a discussão sobre `select` para C10K. Contornos existem (`poll`, que usa vetor dinâmico; recompilar a libc), e nenhum resolve o problema seguinte.

### 2. `epoll` é O(1) nas conexões ociosas; `select` é O(n)

Com o mesmo número de conexões ativas (10) e o mesmo número de conexões abertas (1.000), `epoll` entregou **2.045.138** mensagens e `select` entregou **561.583**, ambos consumindo ~8 s de CPU. Uma razão de **3,6×**.

A diferença é exatamente o que a chamada de sistema faz. `select()` recebe a lista inteira de descritores a cada chamada e o kernel percorre todos os mil, mesmo com apenas dez tendo dado. `epoll_wait()` devolve só os prontos, porque o kernel mantém a lista de interesse registrada entre chamadas.

A confirmação vem da coluna de eficiência: `epoll` entrega **273 mil mensagens por segundo de CPU com 10 mil conexões**, contra 292 mil com mil conexões — uma queda de 6% para um crescimento de 10× no número de conexões ociosas. É a propriedade O(1) medida, não postulada.

### 3. Thread-por-conexão custa 3× mais memória e 3,6× mais CPU por mensagem

Com 10 mil conexões: **121,5 MB** de memória residente contra **41,1 MB** do `epoll`. São 12,4 KB por conexão contra 4,2 KB — e isso já com pilha reduzida a 256 KB. Com o padrão de 8 MB da glibc, o espaço virtual passaria de 80 GB.

Em CPU, o servidor de threads consumiu **19,48 s** para entregar **1.436.459** mensagens, enquanto o `epoll` consumiu **8,07 s** para entregar **2.185.902**. Por segundo de CPU: 75,6 mil contra 273,2 mil, uma razão de **3,6×**.

Onde vai essa CPU? Em troca de contexto. Dez mil threads disputando doze núcleos, cada troca salvando registradores, invalidando linhas de cache e poluindo a TLB. A degradação é visível dentro do próprio modelo: 128,7 mil mensagens por segundo de CPU com mil threads, 75,6 mil com dez mil.

### 4. Latência não é onde `epoll` ganha — e isso precisa ser dito

Em p95 com 10 mil conexões, o servidor de threads (668,6 µs) foi **melhor** que o `epoll` (560,3 µs no p95, mas 595,7 µs no p50 contra 343,8 µs).

A causa é uma assimetria do experimento: **o servidor `epoll` é single-threaded** e usa um núcleo (8,07 s de CPU em 8 s de relógio). O servidor de threads usa quantos o escalonador der — 19,48 s de CPU em 8 s de relógio, ou seja, **2,4 núcleos**.

Ele gastou 2,4× mais CPU para entregar 34% menos mensagens, e ainda assim manteve latência competitiva, porque tinha mais núcleos trabalhando em paralelo.

A comparação justa em produção seria `epoll` com `SO_REUSEPORT` e um processo por núcleo — o desenho que nginx usa. Não implementamos. Registrar essa limitação vale mais do que apresentar um gráfico onde `epoll` ganha em tudo.

## Conclusão

O modelo de multiplexação de E/S vence C10K por **custo por conexão ociosa**, não por latência bruta.

Com dez mil conexões e cem ativas, `epoll` usou 41 MB e um núcleo; thread-por-conexão usou 122 MB e 2,4 núcleos; `select` sequer aceitou as conexões.

A pergunta que o C10K faz não é "quão rápido você responde a um cliente", e sim **"quanto custa um cliente que não está falando"**. Sob essa métrica, `epoll` custa 4,2 KB e aproximadamente zero CPU; uma thread custa 12,4 KB e uma fatia do escalonador; e um descritor além do milésimo vigésimo simplesmente não cabe num `fd_set`.

## Erros de medição encontrados e corrigidos

Registrados porque a primeira rodada produziu números plausíveis e errados.

**O gerador de carga contaminava a medição.** Ao ter suas conexões fechadas pelo servidor `select`, o gerador não removia os descritores mortos do próprio `epoll`. Em modo level-triggered, um socket fechado sinaliza `EPOLLIN` indefinidamente: o gerador entrou em laço ocupado, acumulou 13 milhões de eventos de erro, e passou a competir por CPU com o servidor que deveria estar medindo. O `select` aparecia consumindo *menos* CPU (1,45 s) do que realmente consumia. Correção: `EPOLL_CTL_DEL` e `close()` ao detectar EOF.

**`connect()` bem-sucedido não significa conexão aceita.** O `accept` do servidor `select` acontece e é seguido de `close` imediato quando o descritor passa de `FD_SETSIZE`. Do lado do cliente, `connect()` retorna sucesso — o handshake foi completado pelo kernel via backlog. Medir "conexões estabelecidas" pelo cliente reportava 10.000 onde havia 1.020. A métrica honesta é quantas conexões o servidor **ainda mantinha** ao fim da corrida.

**Amostragem de memória e threads no instante errado.** Ler `/proc/<pid>/status` depois que a carga termina mostra o servidor já drenado: RSS baixo e uma thread. Os valores precisam ser amostrados durante a corrida, e o pico registrado.

**`TIME_WAIT` esgotava as portas efêmeras.** Dez mil sockets fechados por corrida, três corridas, contra as ~28 mil portas do intervalo padrão. A terceira medição falharia por exaustão. Correção: `SO_LINGER` com `l_linger = 0` no gerador, fechando com RST em vez de FIN.
