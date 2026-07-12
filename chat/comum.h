#ifndef PSPD_CHAT_COMUM_H
#define PSPD_CHAT_COMUM_H

#include <stddef.h>
#include <stdint.h>

#define TAM_ENTRADA 4096
#define MAX_FD 65536

typedef enum
{
    MODO_BROADCAST,
    MODO_ECO
} Modo;

typedef struct
{
    char *dados;
    size_t tam;
    size_t cap;
    size_t off;
} Buffer;

int criar_socket_escuta(uint16_t porta, int backlog);
int definir_nao_bloqueante(int fd);
int buffer_anexar(Buffer *b, const char *dados, size_t n);
void buffer_consumir(Buffer *b, size_t n);
void buffer_liberar(Buffer *b);
long agora_ns(void);
void ignorar_sigpipe(void);

#endif
