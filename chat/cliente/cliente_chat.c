/* Cliente de chat. Multiplexa stdin e o socket com epoll: é o que torna o
 * diálogo full-duplex de fato — dá para receber enquanto se digita.
 *
 * Uso: cliente_chat <host> <porta> <apelido>
 */

#define _GNU_SOURCE
#include "../comum.h"

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "uso: %s <host> <porta> <apelido>\n", argv[0]);
        return 1;
    }
    const char *apelido = argv[3];

    ignorar_sigpipe();

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in end = {0};
    end.sin_family = AF_INET;
    end.sin_port = htons((uint16_t)atoi(argv[2]));
    if (inet_pton(AF_INET, argv[1], &end.sin_addr) != 1) {
        fprintf(stderr, "host invalido: %s\n", argv[1]);
        return 1;
    }
    if (connect(fd, (struct sockaddr *)&end, sizeof end) < 0) {
        perror("connect");
        return 1;
    }

    int epfd = epoll_create1(0);
    struct epoll_event ev = {0};
    ev.events = EPOLLIN;
    ev.data.fd = fd;
    epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &ev);
    ev.data.fd = STDIN_FILENO;
    epoll_ctl(epfd, EPOLL_CTL_ADD, STDIN_FILENO, &ev);

    printf("conectado como %s. ctrl-d para sair.\n", apelido);
    fflush(stdout);

    struct epoll_event eventos[2];
    char linha[TAM_ENTRADA];
    char saida[TAM_ENTRADA + 64];

    for (;;) {
        int n = epoll_wait(epfd, eventos, 2, -1);
        if (n < 0) {
            if (errno == EINTR) continue;
            break;
        }
        for (int i = 0; i < n; i++) {
            if (eventos[i].data.fd == STDIN_FILENO) {
                if (!fgets(linha, sizeof linha, stdin)) return 0;
                int m = snprintf(saida, sizeof saida, "%s: %s", apelido, linha);
                if (write(fd, saida, (size_t)m) < 0) return 1;
            } else {
                ssize_t r = read(fd, linha, sizeof linha - 1);
                if (r <= 0) {
                    printf("servidor encerrou a conexao\n");
                    return 0;
                }
                linha[r] = '\0';
                fputs(linha, stdout);
                fflush(stdout);
            }
        }
    }
    return 0;
}
