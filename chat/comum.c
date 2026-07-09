#define _GNU_SOURCE
#include "comum.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

int definir_nao_bloqueante(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0) return -1;
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

int criar_socket_escuta(uint16_t porta, int backlog) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;

    int um = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &um, sizeof um);

    struct sockaddr_in end = {0};
    end.sin_family = AF_INET;
    end.sin_addr.s_addr = htonl(INADDR_ANY);
    end.sin_port = htons(porta);

    if (bind(fd, (struct sockaddr *)&end, sizeof end) < 0) {
        close(fd);
        return -1;
    }
    if (listen(fd, backlog) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

int buffer_anexar(Buffer *b, const char *dados, size_t n) {
    if (b->off > 0 && b->off == b->tam) {
        b->tam = 0;
        b->off = 0;
    }
    if (b->tam + n > b->cap) {
        size_t nova = b->cap ? b->cap : 1024;
        while (nova < b->tam + n) nova *= 2;
        char *p = realloc(b->dados, nova);
        if (!p) return -1;
        b->dados = p;
        b->cap = nova;
    }
    memcpy(b->dados + b->tam, dados, n);
    b->tam += n;
    return 0;
}

void buffer_consumir(Buffer *b, size_t n) {
    b->off += n;
    if (b->off == b->tam) {
        b->off = 0;
        b->tam = 0;
    }
}

void buffer_liberar(Buffer *b) {
    free(b->dados);
    b->dados = NULL;
    b->tam = b->cap = b->off = 0;
}

long agora_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000000000L + ts.tv_nsec;
}

/* Sem isto, um write para um par que fechou mata o processo. */
void ignorar_sigpipe(void) { signal(SIGPIPE, SIG_IGN); }
