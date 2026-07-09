CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -std=c11
LDFLAGS ?=

BIN = bin
ALVOS = $(BIN)/servidor_epoll $(BIN)/servidor_select $(BIN)/servidor_threads \
        $(BIN)/cliente_chat $(BIN)/carga_conexoes

.PHONY: todos limpar
todos: $(ALVOS)

$(BIN):
	mkdir -p $(BIN)

$(BIN)/servidor_epoll: epoll/servidor_epoll.c comum.c comum.h | $(BIN)
	$(CC) $(CFLAGS) -o $@ epoll/servidor_epoll.c comum.c $(LDFLAGS)

$(BIN)/servidor_select: select/servidor_select.c comum.c comum.h | $(BIN)
	$(CC) $(CFLAGS) -o $@ select/servidor_select.c comum.c $(LDFLAGS)

$(BIN)/servidor_threads: threads/servidor_threads.c comum.c comum.h | $(BIN)
	$(CC) $(CFLAGS) -o $@ threads/servidor_threads.c comum.c $(LDFLAGS) -lpthread

$(BIN)/cliente_chat: cliente/cliente_chat.c comum.c comum.h | $(BIN)
	$(CC) $(CFLAGS) -o $@ cliente/cliente_chat.c comum.c $(LDFLAGS)

$(BIN)/carga_conexoes: bench/carga_conexoes.c comum.c comum.h | $(BIN)
	$(CC) $(CFLAGS) -o $@ bench/carga_conexoes.c comum.c $(LDFLAGS)

limpar:
	rm -rf $(BIN)
