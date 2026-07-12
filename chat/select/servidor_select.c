
#define _GNU_SOURCE
#include "../comum.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>

typedef struct
{
    int em_uso;
    char entrada[TAM_ENTRADA];
    size_t entrada_len;
    Buffer saida;
} Conexao;

static Conexao conexoes[FD_SETSIZE];
static int maior_fd;
static long recusadas_por_fd_setsize;

static void fechar_conexao(int fd)
{
    if (!conexoes[fd].em_uso)
        return;
    close(fd);
    buffer_liberar(&conexoes[fd].saida);
    conexoes[fd].em_uso = 0;
    conexoes[fd].entrada_len = 0;
}

static void enfileirar(int fd, const char *dados, size_t n)
{
    if (!conexoes[fd].em_uso)
        return;
    if (buffer_anexar(&conexoes[fd].saida, dados, n) < 0)
        fechar_conexao(fd);
}

static void difundir(int remetente, const char *linha, size_t n, Modo modo)
{
    if (modo == MODO_ECO)
    {
        enfileirar(remetente, linha, n);
        return;
    }
    for (int fd = 0; fd <= maior_fd; fd++)
        if (conexoes[fd].em_uso && fd != remetente)
            enfileirar(fd, linha, n);
}

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

int main(int argc, char **argv)
{
    if (argc < 2)
    {
        fprintf(stderr, "uso: %s <porta> [--eco]\n", argv[0]);
        return 1;
    }
    uint16_t porta = (uint16_t)atoi(argv[1]);
    Modo modo = (argc > 2 && !strcmp(argv[2], "--eco")) ? MODO_ECO : MODO_BROADCAST;

    ignorar_sigpipe();

    int fd_escuta = criar_socket_escuta(porta, 4096);
    if (fd_escuta < 0)
    {
        perror("listen");
        return 1;
    }
    definir_nao_bloqueante(fd_escuta);
    maior_fd = fd_escuta;

    fprintf(stderr, "select: porta=%u modo=%s FD_SETSIZE=%d\n",
            porta, modo == MODO_ECO ? "eco" : "broadcast", FD_SETSIZE);

    for (;;)
    {
        fd_set leitura, escrita;
        FD_ZERO(&leitura);
        FD_ZERO(&escrita);
        FD_SET(fd_escuta, &leitura);

        for (int fd = 0; fd <= maior_fd; fd++)
        {
            if (!conexoes[fd].em_uso)
                continue;
            FD_SET(fd, &leitura);
            if (conexoes[fd].saida.off < conexoes[fd].saida.tam)
                FD_SET(fd, &escrita);
        }

        int n = select(maior_fd + 1, &leitura, &escrita, NULL, NULL);
        if (n < 0)
        {
            if (errno == EINTR)
                continue;
            perror("select");
            break;
        }

        if (FD_ISSET(fd_escuta, &leitura))
        {
            for (;;)
            {
                int fd = accept(fd_escuta, NULL, NULL);
                if (fd < 0)
                    break;
                if (fd >= FD_SETSIZE)
                {
                    recusadas_por_fd_setsize++;
                    close(fd);
                    continue;
                }
                definir_nao_bloqueante(fd);
                conexoes[fd].em_uso = 1;
                conexoes[fd].entrada_len = 0;
                if (fd > maior_fd)
                    maior_fd = fd;
            }
        }

        for (int fd = 0; fd <= maior_fd; fd++)
        {
            if (!conexoes[fd].em_uso)
                continue;

            if (FD_ISSET(fd, &escrita))
            {
                Buffer *b = &conexoes[fd].saida;
                ssize_t w = write(fd, b->dados + b->off, b->tam - b->off);
                if (w > 0)
                    buffer_consumir(b, (size_t)w);
                else if (w < 0 && errno != EAGAIN && errno != EWOULDBLOCK)
                {
                    fechar_conexao(fd);
                    continue;
                }
            }

            if (FD_ISSET(fd, &leitura))
            {
                Conexao *c = &conexoes[fd];
                ssize_t r = read(fd, c->entrada + c->entrada_len,
                                 TAM_ENTRADA - c->entrada_len);
                if (r > 0)
                {
                    c->entrada_len += (size_t)r;
                    processar_entrada(fd, modo);
                }
                else if (r == 0 || (r < 0 && errno != EAGAIN && errno != EWOULDBLOCK))
                {
                    fechar_conexao(fd);
                }
            }
        }

        if (recusadas_por_fd_setsize)
        {
            fprintf(stderr, "select: %ld conexoes recusadas por FD_SETSIZE=%d\n",
                    recusadas_por_fd_setsize, FD_SETSIZE);
            recusadas_por_fd_setsize = 0;
        }
    }
    return 0;
}
