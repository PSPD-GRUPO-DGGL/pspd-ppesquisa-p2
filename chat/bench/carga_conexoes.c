/* Gerador de carga do experimento C10K.
 *
 * Uso: carga_conexoes <host> <porta> <n_conexoes> <n_ativas> <duracao_s>
 *
 * Abre n_conexoes simultâneas e mantém n_ativas delas trocando mensagens em
 * malha fechada (uma mensagem em voo por conexão, a próxima só depois do eco).
 * As demais ficam ociosas — é a assimetria que define o problema C10K: muitas
 * conexões, poucas ativas.
 *
 * O servidor precisa estar em modo --eco. Saída em CSV na última linha.
 */

#define _GNU_SOURCE
#include "../comum.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <unistd.h>

#define MAX_AMOSTRAS 2000000

typedef struct {
    int  fd;
    int  ativa;
    int  viva;
    long enviado_ns;
    char entrada[128];
    size_t entrada_len;
} Cliente;

static Cliente *clientes;
static long *amostras_ns;
static long n_amostras;
static long mensagens_enviadas;
static long conexoes_derrubadas;
static int  epfd;

static int comparar(const void *a, const void *b) {
    long x = *(const long *)a, y = *(const long *)b;
    return (x > y) - (x < y);
}

static long percentil(double p) {
    if (n_amostras == 0) return 0;
    long i = (long)(p * (double)(n_amostras - 1));
    return amostras_ns[i];
}

/* Um socket fechado pelo servidor sinaliza EPOLLIN para sempre em modo
   level-triggered. Sem removê-lo do epoll, o gerador entra em laço ocupado e
   passa a competir por CPU com o servidor que ele deveria estar medindo. */
static void derrubar(Cliente *c) {
    if (!c->viva) return;
    epoll_ctl(epfd, EPOLL_CTL_DEL, c->fd, NULL);
    close(c->fd);
    c->viva = 0;
    conexoes_derrubadas++;
}

static void enviar(Cliente *c) {
    if (!c->viva) return;
    char msg[64];
    c->enviado_ns = agora_ns();
    int n = snprintf(msg, sizeof msg, "T %ld\n", c->enviado_ns);
    if (write(c->fd, msg, (size_t)n) < 0) derrubar(c);
    else mensagens_enviadas++;
}

int main(int argc, char **argv) {
    if (argc != 6) {
        fprintf(stderr,
            "uso: %s <host> <porta> <n_conexoes> <n_ativas> <duracao_s>\n", argv[0]);
        return 1;
    }
    const char *host = argv[1];
    uint16_t porta = (uint16_t)atoi(argv[2]);
    long n_conexoes = atol(argv[3]);
    long n_ativas = atol(argv[4]);
    long duracao_s = atol(argv[5]);

    ignorar_sigpipe();

    clientes = calloc((size_t)n_conexoes, sizeof(Cliente));
    amostras_ns = malloc(sizeof(long) * MAX_AMOSTRAS);
    if (!clientes || !amostras_ns) { perror("malloc"); return 1; }

    struct sockaddr_in end = {0};
    end.sin_family = AF_INET;
    end.sin_port = htons(porta);
    inet_pton(AF_INET, host, &end.sin_addr);

    epfd = epoll_create1(0);
    long estabelecidas = 0, falhas_conexao = 0;

    for (long i = 0; i < n_conexoes; i++) {
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) { falhas_conexao++; continue; }
        if (connect(fd, (struct sockaddr *)&end, sizeof end) < 0) {
            close(fd);
            falhas_conexao++;
            continue;
        }
        int um = 1;
        setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &um, sizeof um);
        /* Fecha com RST em vez de FIN: sem isso, cada corrida deixa milhares de
           sockets em TIME_WAIT e esgota as ~28k portas efêmeras do host. */
        struct linger sem_espera = {.l_onoff = 1, .l_linger = 0};
        setsockopt(fd, SOL_SOCKET, SO_LINGER, &sem_espera, sizeof sem_espera);
        definir_nao_bloqueante(fd);

        clientes[estabelecidas].fd = fd;
        clientes[estabelecidas].ativa = (estabelecidas < n_ativas);
        clientes[estabelecidas].viva = 1;
        clientes[estabelecidas].entrada_len = 0;

        struct epoll_event ev = {0};
        ev.events = EPOLLIN;
        ev.data.u64 = (uint64_t)estabelecidas;
        epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &ev);
        estabelecidas++;
    }

    fprintf(stderr, "carga: estabelecidas=%ld falhas=%ld ativas=%ld\n",
            estabelecidas, falhas_conexao, n_ativas < estabelecidas ? n_ativas : estabelecidas);

    if (estabelecidas == 0) {
        printf("conexoes=%ld,estabelecidas=0,vivas=0,falhas=%ld,msgs=0,"
               "p50_us=0,p95_us=0,p99_us=0,derrubadas=0\n", n_conexoes, falhas_conexao);
        return 1;
    }

    for (long i = 0; i < estabelecidas && i < n_ativas; i++) enviar(&clientes[i]);

    long fim_ns = agora_ns() + duracao_s * 1000000000L;
    struct epoll_event eventos[4096];

    while (agora_ns() < fim_ns) {
        int n = epoll_wait(epfd, eventos, 4096, 200);
        if (n < 0) {
            if (errno == EINTR) continue;
            break;
        }
        for (int i = 0; i < n; i++) {
            Cliente *c = &clientes[eventos[i].data.u64];
            if (!c->viva) continue;
            ssize_t r = read(c->fd, c->entrada + c->entrada_len,
                             sizeof c->entrada - c->entrada_len - 1);
            if (r <= 0) {
                if (r == 0 || (errno != EAGAIN && errno != EWOULDBLOCK)) derrubar(c);
                continue;
            }
            c->entrada_len += (size_t)r;
            c->entrada[c->entrada_len] = '\0';

            char *nl = memchr(c->entrada, '\n', c->entrada_len);
            if (!nl) continue;

            if (n_amostras < MAX_AMOSTRAS)
                amostras_ns[n_amostras++] = agora_ns() - c->enviado_ns;
            c->entrada_len = 0;

            if (c->ativa && agora_ns() < fim_ns) enviar(c);
        }
    }

    qsort(amostras_ns, (size_t)n_amostras, sizeof(long), comparar);

    long vivas = 0;
    for (long i = 0; i < estabelecidas; i++) if (clientes[i].viva) vivas++;

    printf("conexoes=%ld,estabelecidas=%ld,vivas=%ld,falhas=%ld,msgs=%ld,"
           "p50_us=%.1f,p95_us=%.1f,p99_us=%.1f,derrubadas=%ld\n",
           n_conexoes, estabelecidas, vivas, falhas_conexao, mensagens_enviadas,
           percentil(0.50) / 1000.0, percentil(0.95) / 1000.0,
           percentil(0.99) / 1000.0, conexoes_derrubadas);

    for (long i = 0; i < estabelecidas; i++) if (clientes[i].viva) close(clientes[i].fd);
    return 0;
}
