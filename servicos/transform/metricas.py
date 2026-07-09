"""Métricas Prometheus e interceptor gRPC do Data Transform Service."""

from __future__ import annotations

import time

import grpc
from prometheus_client import Counter, Histogram, start_http_server

TRANSFORM_REQUESTS = Counter(
    "transform_requests_total",
    "Transformações concluídas, por nível de acesso aplicado.",
    ["nivel"],
)

TRANSFORM_DURATION = Histogram(
    "transform_duration_seconds",
    "Duração da projeção + montagem do Bundle FHIR, por nível.",
    ["nivel"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

TRANSFORM_RECURSOS = Counter(
    "transform_fhir_resources_total",
    "Resources FHIR emitidos, por resourceType.",
    ["tipo"],
)

TRANSFORM_BYTES = Histogram(
    "transform_bundle_bytes",
    "Tamanho do Bundle serializado, por nível.",
    ["nivel"],
    buckets=(512, 2048, 8192, 32768, 131072, 524288, 2097152),
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
                # abort() não levanta grpc.RpcError; o código real está no contexto.
                GRPC_HANDLED.labels(rpc=rpc, code=_codigo(contexto, padrao="INTERNAL")).inc()
                raise
            else:
                GRPC_HANDLED.labels(rpc=rpc, code=_codigo(contexto, padrao="OK")).inc()
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
