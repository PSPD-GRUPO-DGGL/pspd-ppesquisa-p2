

#define _GNU_SOURCE
#include "../comum.h"

#include <errno.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <unistd.h>

typedef struct
{
    int em_uso;
    char entrada[TAM_ENTRADA];
    size_t entrada_len;
    Buffer saida;
    int quer_escrita;
} Conexao;

static Conexao conexoes[MAX_FD];
static int epfd;
static long conexoes_ativas;
static long mensagens_total;
static long bytes_enviados_total;
static long epoll_wait_ns_total;
static long epoll_wait_chamadas;

static void ajustar_interesse(int fd, int quer_escrita)
{
    if (conexoes[fd].quer_escrita == quer_escrita)
        return;
    struct epoll_event ev = {0};
    ev.data.fd = fd;
    ev.events = EPOLLIN | EPOLLET | EPOLLRDHUP | (quer_escrita ? EPOLLOUT : 0);
    epoll_ctl(epfd, EPOLL_CTL_MOD, fd, &ev);
    conexoes[fd].quer_escrita = quer_escrita;
}

static void fechar_conexao(int fd)
{
    if (!conexoes[fd].em_uso)
        return;
    epoll_ctl(epfd, EPOLL_CTL_DEL, fd, NULL);
    close(fd);
    buffer_liberar(&conexoes[fd].saida);
    conexoes[fd].em_uso = 0;
    conexoes[fd].entrada_len = 0;
    conexoes[fd].quer_escrita = 0;
    conexoes_ativas--;
}

/* Edge-triggered: escreve até EAGAIN, senão o evento de gravável não volta. */
static void drenar_saida(int fd)
{
    Buffer *b = &conexoes[fd].saida;
    while (b->off < b->tam)
    {
        ssize_t n = write(fd, b->dados + b->off, b->tam - b->off);
        if (n > 0)
        {
            bytes_enviados_total += n;
            buffer_consumir(b, (size_t)n);
            continue;
        }
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK))
        {
            ajustar_interesse(fd, 1);
            return;
        }
        fechar_conexao(fd);
        return;
    }
    ajustar_interesse(fd, 0);
}

static void enfileirar(int fd, const char *dados, size_t n)
{
    if (!conexoes[fd].em_uso)
        return;
    if (buffer_anexar(&conexoes[fd].saida, dados, n) < 0)
    {
        fechar_conexao(fd);
        return;
    }
    drenar_saida(fd);
}

static void difundir(int remetente, const char *linha, size_t n, Modo modo)
{
    mensagens_total++;
    if (modo == MODO_ECO)
    {
        enfileirar(remetente, linha, n);
        return;
    }
    for (int fd = 0; fd < MAX_FD; fd++)
        if (conexoes[fd].em_uso && fd != remetente)
            enfileirar(fd, linha, n);
}

/* Consome linhas completas do buffer de entrada. Uma linha maior que
   TAM_ENTRADA derruba a conexão em vez de estourar o buffer. */
static void processar_entrada(int fd, Modo modo)
{
    Conexao *c = &conexoes[fd];
    size_t inicio = 0;
    for (size_t i = 0; i < c->entrada_len; i++)
    {
        if (c->entrada[i] != '\n')
            continue;
        difundir(fd, c->entrada + inicio, i - inicio + 1, modo);
        if (!c->em_uso)
            return;
        inicio = i + 1;
    }
    if (inicio > 0)
    {
        memmove(c->entrada, c->entrada + inicio, c->entrada_len - inicio);
        c->entrada_len -= inicio;
    }
    else if (c->entrada_len == TAM_ENTRADA)
    {
        fechar_conexao(fd);
    }
}

static void ler_ate_eagain(int fd, Modo modo)
{
    Conexao *c = &conexoes[fd];
    for (;;)
    {
        if (c->entrada_len == TAM_ENTRADA)
        {
            fechar_conexao(fd);
            return;
        }
        ssize_t n = read(fd, c->entrada + c->entrada_len, TAM_ENTRADA - c->entrada_len);
        if (n > 0)
        {
            c->entrada_len += (size_t)n;
            processar_entrada(fd, modo);
            if (!c->em_uso)
                return;
            continue;
        }
        if (n == 0)
        {
            fechar_conexao(fd);
            return;
        }
        if (errno == EAGAIN || errno == EWOULDBLOCK)
            return;
        fechar_conexao(fd);
        return;
    }
}

static void aceitar_todas(int fd_escuta, Modo modo)
{
    (void)modo;
    for (;;)
    {
        int fd = accept(fd_escuta, NULL, NULL);
        if (fd < 0)
        {
            if (errno == EAGAIN || errno == EWOULDBLOCK)
                return;
            if (errno == EMFILE || errno == ENFILE)
            {
                fprintf(stderr, "sem descritores livres\n");
                return;
            }
            return;
        }
        if (fd >= MAX_FD)
        {
            close(fd);
            continue;
        }
        definir_nao_bloqueante(fd);
        conexoes[fd].em_uso = 1;
        conexoes[fd].entrada_len = 0;
        conexoes[fd].quer_escrita = 0;
        conexoes_ativas++;

        struct epoll_event ev = {0};
        ev.data.fd = fd;
        ev.events = EPOLLIN | EPOLLET | EPOLLRDHUP;
        epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &ev);
    }
}

static void servir_metricas(int fd_escuta)
{
    int fd = accept(fd_escuta, NULL, NULL);
    if (fd < 0)
        return;

    char descarte[512];
    ssize_t lido = read(fd, descarte, sizeof descarte);
    (void)lido;

    char corpo[1024];
    int n = snprintf(corpo, sizeof corpo,
                     "# TYPE chat_conexoes_ativas gauge\n"
                     "chat_conexoes_ativas %ld\n"
                     "# TYPE chat_mensagens_total counter\n"
                     "chat_mensagens_total %ld\n"
                     "# TYPE chat_bytes_enviados_total counter\n"
                     "chat_bytes_enviados_total %ld\n"
                     "# TYPE chat_epoll_wait_duration_seconds summary\n"
                     "chat_epoll_wait_duration_seconds_sum %.6f\n"
                     "chat_epoll_wait_duration_seconds_count %ld\n",
                     conexoes_ativas, mensagens_total, bytes_enviados_total,
                     epoll_wait_ns_total / 1e9, epoll_wait_chamadas);

    char cab[256];
    int m = snprintf(cab, sizeof cab,
                     "HTTP/1.1 200 OK\r\nContent-Type: text/plain; version=0.0.4\r\n"
                     "Content-Length: %d\r\nConnection: close\r\n\r\n",
                     n);

    ssize_t ignorado;
    ignorado = write(fd, cab, (size_t)m);
    ignorado = write(fd, corpo, (size_t)n);
    (void)ignorado;
    close(fd);
}

int main(int argc, char **argv)
{
    if (argc < 2)
    {
        fprintf(stderr, "uso: %s <porta> [--eco] [--metricas <porta>]\n", argv[0]);
        return 1;
    }
    uint16_t porta = (uint16_t)atoi(argv[1]);
    Modo modo = MODO_BROADCAST;
    uint16_t porta_metricas = 0;

    for (int i = 2; i < argc; i++)
    {
        if (!strcmp(argv[i], "--eco"))
            modo = MODO_ECO;
        else if (!strcmp(argv[i], "--metricas") && i + 1 < argc)
            porta_metricas = (uint16_t)atoi(argv[++i]);
    }

    ignorar_sigpipe();

    int fd_escuta = criar_socket_escuta(porta, 4096);
    if (fd_escuta < 0)
    {
        perror("listen");
        return 1;
    }
    definir_nao_bloqueante(fd_escuta);

    int fd_metricas = -1;
    if (porta_metricas)
    {
        fd_metricas = criar_socket_escuta(porta_metricas, 16);
        if (fd_metricas < 0)
        {
            perror("listen metricas");
            return 1;
        }
        definir_nao_bloqueante(fd_metricas);
    }

    epfd = epoll_create1(0);
    struct epoll_event ev = {0};
    ev.data.fd = fd_escuta;
    ev.events = EPOLLIN | EPOLLET;
    epoll_ctl(epfd, EPOLL_CTL_ADD, fd_escuta, &ev);

    if (fd_metricas >= 0)
    {
        ev.data.fd = fd_metricas;
        ev.events = EPOLLIN;
        epoll_ctl(epfd, EPOLL_CTL_ADD, fd_metricas, &ev);
    }

    fprintf(stderr, "epoll: porta=%u modo=%s metricas=%u\n",
            porta, modo == MODO_ECO ? "eco" : "broadcast", porta_metricas);

    struct epoll_event eventos[1024];
    for (;;)
    {
        long t0 = agora_ns();
        int n = epoll_wait(epfd, eventos, 1024, -1);
        epoll_wait_ns_total += agora_ns() - t0;
        epoll_wait_chamadas++;

        if (n < 0)
        {
            if (errno == EINTR)
                continue;
            perror("epoll_wait");
            break;
        }
        for (int i = 0; i < n; i++)
        {
            int fd = eventos[i].data.fd;
            uint32_t e = eventos[i].events;

            if (fd == fd_escuta)
            {
                aceitar_todas(fd_escuta, modo);
                continue;
            }
            if (fd == fd_metricas)
            {
                servir_metricas(fd_metricas);
                continue;
            }

            if (e & (EPOLLHUP | EPOLLERR))
            {
                fechar_conexao(fd);
                continue;
            }
            if (e & EPOLLOUT)
            {
                drenar_saida(fd);
                if (!conexoes[fd].em_uso)
                    continue;
            }
            if (e & (EPOLLIN | EPOLLRDHUP))
                ler_ate_eagain(fd, modo);
        }
    }
    return 0;
}
