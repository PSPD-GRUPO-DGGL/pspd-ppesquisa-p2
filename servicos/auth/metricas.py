"""Métricas Prometheus e interceptor gRPC do Authorization Service."""

from __future__ import annotations

import time
from contextlib import contextmanager

import grpc
from prometheus_client import Counter, Histogram, start_http_server

AUTH_DECISOES = Counter(
    "auth_decisoes_total",
    "Decisões de autorização por perfil, nível e motivo.",
    ["decisao", "nivel", "role", "motivo"],
)

AUTH_DB_QUERY_DURATION = Histogram(
    "auth_db_query_duration_seconds",
    "Duração das consultas SQL do Authorization Service.",
    ["consulta"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

GRPC_HANDLED = Counter(
    "grpc_server_handled_total",
    "RPCs concluídos, por método e código de status.",
    ["rpc", "code"],
)

GRPC_HANDLING = Histogram(
    "grpc_server_handling_seconds",
    "Latência de RPC do lado do servidor.",
    ["rpc"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


@contextmanager
def medir_query(nome: str):
    inicio = time.perf_counter()
    try:
        yield
    finally:
        AUTH_DB_QUERY_DURATION.labels(consulta=nome).observe(time.perf_counter() - inicio)


def _codigo(contexto, padrao: str) -> str:
    codigo = contexto.code()
    if codigo is None:
        return padrao
    return codigo.name if hasattr(codigo, "name") else str(codigo)


class InterceptorDeMetricas(grpc.ServerInterceptor):
    def intercept_service(self, continuation, handler_call_details):
        handler = continuation(handler_call_details)
        if handler is None or not handler.unary_unary:
            return handler

        rpc = handler_call_details.method.rsplit("/", 1)[-1]
        original = handler.unary_unary

        def envolvido(requisicao, contexto):
            inicio = time.perf_counter()
            try:
                resposta = original(requisicao, contexto)
            except Exception:
                GRPC_HANDLED.labels(rpc=rpc, code=_codigo(contexto, "INTERNAL")).inc()
                raise
            else:
                GRPC_HANDLED.labels(rpc=rpc, code=_codigo(contexto, "OK")).inc()
                return resposta
            finally:
                GRPC_HANDLING.labels(rpc=rpc).observe(time.perf_counter() - inicio)

        return grpc.unary_unary_rpc_method_handler(
            envolvido,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


def servir_metricas(porta: int = 8000) -> None:
    start_http_server(porta)
