"""Data Transform Service — servidor gRPC."""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent import futures

import grpc

import comum_pb2
import transform_pb2
import transform_pb2_grpc
from anonimizacao import (
    AGGREGATED,
    DENY,
    NOMES_NIVEL,
    SaltAusente,
    mapa_de_ids,
    projetar_paciente,
)
from fhir import montar_bundle, montar_measure_report
from metricas import (
    TRANSFORM_BYTES,
    TRANSFORM_DURATION,
    TRANSFORM_RECURSOS,
    TRANSFORM_REQUESTS,
    InterceptorDeMetricas,
    servir_metricas,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format='{"ts":"%(asctime)s","nivel":"%(levelname)s","msg":"%(message)s"}',
)
log = logging.getLogger("transform")

PORTA_GRPC = int(os.environ.get("GRPC_PORT", "50053"))
PORTA_METRICAS = int(os.environ.get("METRICS_PORT", "8000"))
MAX_WORKERS = int(os.environ.get("GRPC_MAX_WORKERS", "8"))


# Conversão explícita, e não MessageToDict, que converteria os nomes de campo
# para camelCase e quebraria as funções de anonimizacao.py e fhir.py.


def _paciente(m: comum_pb2.Paciente) -> dict:
    return {
        "id_paciente": m.id_paciente,
        "nome": m.nome,
        "data_nascimento": m.data_nascimento,
        "genero": m.genero,
        "cidade": m.cidade,
        "estado": m.estado,
        "cpf": m.cpf,
        "cns": m.cns,
    }


def _atendimento(m: comum_pb2.Atendimento) -> dict:
    return {
        "id_atendimento": m.id_atendimento,
        "id_paciente": m.id_paciente,
        "data_inicio": m.data_inicio,
        "data_fim": m.data_fim,
        "tipo_atendimento": m.tipo_atendimento,
        "setor": m.setor,
    }


def _evento(m: comum_pb2.EventoClinico) -> dict:
    return {
        "id_evento": m.id_evento,
        "id_paciente": m.id_paciente,
        "id_atendimento": m.id_atendimento,
        "tipo_evento": m.tipo_evento,
        "codigo_tipo_evento": m.codigo_tipo_evento,
        "descricao": m.descricao,
        "data_evento": m.data_evento,
        "valor": m.valor,
        "unidade": m.unidade,
    }


def _contagem(m: comum_pb2.Contagem) -> dict:
    return {"chave": m.chave, "valor": m.valor, "percentual": m.percentual}


def _estatistica(m: comum_pb2.Estatistica) -> dict:
    return {
        "nome": m.nome,
        "media": m.media,
        "mediana": m.mediana,
        "desvio_padrao": m.desvio_padrao,
        "n": m.n,
        "unidade": m.unidade,
    }


def _agregado(m: comum_pb2.ResultadoAgregado) -> dict:
    return {
        "codigo_condicao": m.codigo_condicao,
        "total_pacientes": m.total_pacientes,
        "distribuicao_sexo": [_contagem(c) for c in m.distribuicao_sexo],
        "distribuicao_faixa_etaria": [_contagem(c) for c in m.distribuicao_faixa_etaria],
        "distribuicao_setor": [_contagem(c) for c in m.distribuicao_setor],
        "frequencia_medicamentos": [_contagem(c) for c in m.frequencia_medicamentos],
        "estatisticas_exames": [_estatistica(s) for s in m.estatisticas_exames],
    }


class Servico(transform_pb2_grpc.DataTransformServiceServicer):
    def TransformarParaFHIR(self, requisicao, contexto):
        nivel = requisicao.nivel
        rotulo = NOMES_NIVEL.get(nivel, "DESCONHECIDO")

        if nivel in (DENY, comum_pb2.NIVEL_INDEFINIDO):
            contexto.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"nível não transformável: {rotulo}",
            )

        inicio = time.perf_counter()
        try:
            if nivel == AGGREGATED:
                if requisicao.WhichOneof("carga") != "agregado":
                    contexto.abort(
                        grpc.StatusCode.INVALID_ARGUMENT,
                        "AGGREGATED exige carga `agregado`",
                    )
                bundle, contagem = montar_measure_report(_agregado(requisicao.agregado))
            else:
                if requisicao.WhichOneof("carga") != "dados":
                    contexto.abort(
                        grpc.StatusCode.INVALID_ARGUMENT,
                        f"{rotulo} exige carga `dados`",
                    )
                dados = requisicao.dados
                pacientes = [_paciente(p) for p in dados.pacientes]
                atendimentos = [_atendimento(a) for a in dados.atendimentos]
                eventos = [_evento(e) for e in dados.eventos]

                projetados = [projetar_paciente(p, nivel) for p in pacientes]
                ids = mapa_de_ids(pacientes, nivel)
                bundle, contagem = montar_bundle(
                    projetados, atendimentos, eventos, nivel, ids
                )

            corpo = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))

        except SaltAusente as erro:
            log.error("ANON_SALT ausente: %s", erro)
            contexto.abort(grpc.StatusCode.FAILED_PRECONDITION, str(erro))
        except ValueError as erro:
            contexto.abort(grpc.StatusCode.INVALID_ARGUMENT, str(erro))
        finally:
            TRANSFORM_DURATION.labels(nivel=rotulo).observe(time.perf_counter() - inicio)

        TRANSFORM_REQUESTS.labels(nivel=rotulo).inc()
        TRANSFORM_BYTES.labels(nivel=rotulo).observe(len(corpo))
        for tipo, n in contagem.items():
            TRANSFORM_RECURSOS.labels(tipo=tipo).inc(n)

        return transform_pb2.RespostaFHIR(
            fhir_bundle_json=corpo,
            total_recursos=sum(contagem.values()),
            nivel_aplicado=nivel,
        )


def main() -> None:
    if os.environ.get("ANON_SALT") is None:
        log.warning(
            "ANON_SALT não definido: requisições ANONYMIZED falharão com FAILED_PRECONDITION"
        )

    servir_metricas(PORTA_METRICAS)

    servidor = grpc.server(
        futures.ThreadPoolExecutor(max_workers=MAX_WORKERS),
        interceptors=[InterceptorDeMetricas()],
    )
    transform_pb2_grpc.add_DataTransformServiceServicer_to_server(Servico(), servidor)
    servidor.add_insecure_port(f"[::]:{PORTA_GRPC}")
    servidor.start()
    log.info("transform ouvindo gRPC=%d metrics=%d", PORTA_GRPC, PORTA_METRICAS)
    servidor.wait_for_termination()


if __name__ == "__main__":
    main()
