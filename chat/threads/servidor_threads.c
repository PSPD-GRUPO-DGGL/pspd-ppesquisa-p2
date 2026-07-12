
#define _GNU_SOURCE
#include "../comum.h"

#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#define MAX_CLIENTES 65536

static int clientes[MAX_CLIENTES];
static int n_clientes;
static pthread_mutex_t trava = PTHREAD_MUTEX_INITIALIZER;
static Modo modo_global;

static void registrar(int fd)
{
    pthread_mutex_lock(&trava);
    if (n_clientes < MAX_CLIENTES)
        clientes[n_clientes++] = fd;
    pthread_mutex_unlock(&trava);
}

static void remover(int fd)
{
    pthread_mutex_lock(&trava);
    for (int i = 0; i < n_clientes; i++)
    {
        if (clientes[i] == fd)
        {
            clientes[i] = clientes[--n_clientes];
            break;
        }
    }
    pthread_mutex_unlock(&trava);
}

static void escrever_tudo(int fd, const char *dados, size_t n)
{
    size_t enviado = 0;
    while (enviado < n)
    {
        ssize_t w = write(fd, dados + enviado, n - enviado);
        if (w <= 0)
            return;
        enviado += (size_t)w;
    }
}

static void difundir(int remetente, const char *linha, size_t n)
{
    if (modo_global == MODO_ECO)
    {
        escrever_tudo(remetente, linha, n);
        return;
    }
    pthread_mutex_lock(&trava);
    for (int i = 0; i < n_clientes; i++)
        if (clientes[i] != remetente)
            escrever_tudo(clientes[i], linha, n);
    pthread_mutex_unlock(&trava);
}

static void *atender(void *arg)
{
    int fd = (int)(intptr_t)arg;
    registrar(fd);

    char entrada[TAM_ENTRADA];
    size_t len = 0;

    for (;;)
    {
        ssize_t r = read(fd, entrada + len, TAM_ENTRADA - len);
        if (r <= 0)
            break;
        len += (size_t)r;

        size_t inicio = 0;
        for (size_t i = 0; i < len; i++)
        {
            if (entrada[i] != '\n')
                continue;
            difundir(fd, entrada + inicio, i - inicio + 1);
            inicio = i + 1;
        }
        if (inicio > 0)
        {
            memmove(entrada, entrada + inicio, len - inicio);
            len -= inicio;
        }
        else if (len == TAM_ENTRADA)
        {
            break;
        }
    }

    remover(fd);
    close(fd);
    return NULL;
}

int main(int argc, char **argv)
{
    if (argc < 2)
    {
        fprintf(stderr, "uso: %s <porta> [--eco] [--pilha-kb N]\n", argv[0]);
        return 1;
    }
    uint16_t porta = (uint16_t)atoi(argv[1]);
    modo_global = MODO_BROADCAST;
    size_t pilha_kb = 256;

    for (int i = 2; i < argc; i++)
    {
        if (!strcmp(argv[i], "--eco"))
            modo_global = MODO_ECO;
        else if (!strcmp(argv[i], "--pilha-kb") && i + 1 < argc)
            pilha_kb = (size_t)atoi(argv[++i]);
    }

    ignorar_sigpipe();

    int fd_escuta = criar_socket_escuta(porta, 4096);
    if (fd_escuta < 0)
    {
        perror("listen");
        return 1;
    }

    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, pilha_kb * 1024);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);

    fprintf(stderr, "threads: porta=%u modo=%s pilha=%zuKB\n",
            porta, modo_global == MODO_ECO ? "eco" : "broadcast", pilha_kb);

    long falhas_pthread = 0;
    for (;;)
    {
        int fd = accept(fd_escuta, NULL, NULL);
        if (fd < 0)
        {
            if (errno == EINTR)
                continue;
            if (errno == EMFILE || errno == ENFILE)
            {
                fprintf(stderr, "threads: sem descritores livres\n");
                continue;
            }
            perror("accept");
            break;
        }
        pthread_t t;
        int rc = pthread_create(&t, &attr, atender, (void *)(intptr_t)fd);
        if (rc != 0)
        {
            if (++falhas_pthread % 100 == 1)
                fprintf(stderr, "threads: pthread_create falhou (%s), %ld vezes\n",
                        strerror(rc), falhas_pthread);
            close(fd);
        }
    }
    return 0;
}
