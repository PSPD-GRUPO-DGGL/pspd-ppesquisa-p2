# Chat full-duplex com `epoll` e experimento C10K

Servidor de chat em C, com multiplexação de E/S via `epoll` em modo *edge-triggered*, mais duas implementações alternativas do mesmo protocolo para comparação: `select()` e thread-por-conexão.

Requisito apresentado pelo professor em aula (não consta no PDF do enunciado). É o componente do projeto que toca diretamente a ementa da disciplina: comunicação interprocessos, multiplexação de E/S e chamadas de sistema.

## Construir

```bash
make todos          # gera bin/servidor_{epoll,select,threads}, bin/cliente_chat, bin/carga_conexoes
make limpar
```

Sem dependências além de `gcc` e `pthread`.

## Usar o chat

```bash
./bin/servidor_epoll 9100 --metricas 9101

# em outros terminais
./bin/cliente_chat 127.0.0.1 9100 ana
./bin/cliente_chat 127.0.0.1 9100 bruno
```

O cliente multiplexa `stdin` e o socket com `epoll`, então recebe mensagens enquanto o usuário digita. É isso que torna o diálogo full-duplex de fato, e não um ciclo pergunta-resposta.

O servidor expõe métricas em texto Prometheus na porta indicada por `--metricas`:

```
chat_conexoes_ativas
chat_mensagens_total
chat_bytes_enviados_total
chat_epoll_wait_duration_seconds_{sum,count}
```

A flag `--eco` troca o broadcast por eco ao remetente. É o modo usado no experimento: com 10 mil conexões, retransmitir cada mensagem para todos os pares mediria o custo do fan-out, não o da multiplexação.

## O experimento

```bash
./scripts/experimento_c10k.sh 8 1000 5000 10000
```

Para cada servidor e cada número de conexões, o script sobe o servidor, abre `N` conexões simultâneas mantendo **1% delas ativas** em malha fechada (uma mensagem em voo por conexão, a próxima só depois do eco), e mede memória residente de pico, CPU consumida, número de threads e latência de ida-e-volta.

A assimetria entre conexões abertas e conexões ativas é o que define o problema C10K: um servidor real tem milhares de clientes conectados e poucos falando ao mesmo tempo.

Resultados em `resultados/c10k.csv`.

## Detalhes de implementação que importam

**Edge-triggered exige `O_NONBLOCK` e drenar até `EAGAIN`.** No modo `EPOLLET`, o kernel avisa uma única vez, quando o estado do socket muda. Ler menos que o disponível significa não ser avisado de novo: o dado fica no buffer e a conexão parece morta. `ler_ate_eagain()` e `drenar_saida()` existem por isso.

**Buffer de saída por conexão.** `write()` pode aceitar menos bytes do que o pedido. O resto espera o socket ficar gravável, e só então o `EPOLLOUT` é registrado — mantê-lo sempre ligado transformaria o `epoll_wait` num laço ocupado.

**`FD_SETSIZE` é o teto do `select()`.** São 1024 descritores na glibc, e o valor é fixado em tempo de compilação da libc, não do programa. O servidor `select` recusa conexões acima disso, e o experimento mede exatamente onde.

**`SO_LINGER` com `l_linger = 0` no gerador de carga.** Fecha com RST em vez de FIN. Sem isso, cada corrida deixa milhares de sockets em `TIME_WAIT` e esgota as ~28 mil portas efêmeras do host antes da terceira medição.

**O gerador remove sockets mortos do `epoll`.** Um socket fechado pelo par sinaliza `EPOLLIN` indefinidamente em modo level-triggered. Sem `EPOLL_CTL_DEL`, o gerador entra em laço ocupado e passa a competir por CPU com o servidor que deveria estar medindo — o que contaminou a primeira rodada de medições deste experimento.

## Limitação conhecida da comparação

O servidor `epoll` é **single-threaded**; o servidor de threads usa quantos núcleos o escalonador lhe der. Numa máquina de 12 threads com apenas 1% das conexões ativas, isso favorece o modelo de threads na métrica de latência, ao custo de memória e de CPU total.

A comparação justa em produção seria `epoll` com `SO_REUSEPORT` e um processo por núcleo. Não implementamos. O que o experimento mede, e mede corretamente, é **o custo por conexão ociosa** — que é a pergunta do C10K.
