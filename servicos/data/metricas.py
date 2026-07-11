"""Métricas Prometheus e interceptor gRPC do Patient Data Service."""

from __future__ import annotations

import time
from contextlib import contextmanager

import grpc
from prometheus_client import Counter, Gauge, Histogram, start_http_server

DATA_QUERIES = Counter(
    "data_queries_total",
    "Consultas executadas pelo Patient Data Service.",
    ["tipo"],
)

DATA_QUERY_DURATION = Histogram(
    "data_query_duration_seconds",
    "Duração das consultas SQL do Patient Data Service.",
    ["tipo"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

DATA_LINHAS_RETORNADAS = Histogram(
    "data_linhas_retornadas",
    "Quantidade de linhas retornadas por tipo de consulta.",
    ["tipo"],
    buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000, 10000),
)

DATA_DB_POOL_EM_USO = Gauge(
    "data_db_pool_em_uso",
    "Conexões do pool atualmente emprestadas ao serviço.",
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
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


@contextmanager
def medir_query(tipo: str):
    inicio = time.perf_counter()
    DATA_DB_POOL_EM_USO.inc()
    try:
        yield
    finally:
        DATA_DB_POOL_EM_USO.dec()
        DATA_QUERY_DURATION.labels(tipo=tipo).observe(time.perf_counter() - inicio)
        DATA_QUERIES.labels(tipo=tipo).inc()


def observar_linhas(tipo: str, n: int) -> None:
    DATA_LINHAS_RETORNADAS.labels(tipo=tipo).observe(n)


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
