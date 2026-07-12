"""Patient Data Service — servidor gRPC."""

from __future__ import annotations

import logging
import os
from concurrent import futures

import grpc

import data_pb2_grpc
from config import conninfo
from conversao import agregado, conjunto, lista_projetos
from metricas import InterceptorDeMetricas, servir_metricas
from repositorio import RepositorioData

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format='{"ts":"%(asctime)s","nivel":"%(levelname)s","msg":"%(message)s"}',
)
log = logging.getLogger("data")

PORTA_GRPC = int(os.environ.get("GRPC_PORT", "50052"))
PORTA_METRICAS = int(os.environ.get("METRICS_PORT", "8000"))
MAX_WORKERS = int(os.environ.get("GRPC_MAX_WORKERS", "8"))


class Servico(data_pb2_grpc.PatientDataServiceServicer):
    def __init__(self, repo: RepositorioData):
        self.repo = repo

    def BuscarPacientes(self, requisicao, contexto):
        dados = self.repo.buscar_pacientes(
            list(requisicao.ids_pacientes),
            incluir_atendimentos=requisicao.incluir_atendimentos,
            incluir_eventos=requisicao.incluir_eventos,
            tipo_evento=requisicao.tipo_evento,
            limite_eventos=requisicao.limite_eventos,
        )
        return conjunto(dados)

    def BuscarCoorte(self, requisicao, contexto):
        dados = self.repo.buscar_coorte(
            requisicao.codigo_condicao,
            limite_pacientes=requisicao.limite_pacientes,
        )
        return conjunto(dados)

    def AgregarCoorte(self, requisicao, contexto):
        return agregado(self.repo.agregar_coorte(requisicao.codigo_condicao))

    def ListarProjetos(self, requisicao, contexto):
        return lista_projetos(self.repo.listar_projetos(requisicao.username))


def main() -> None:
    repo = RepositorioData(conninfo())
    servir_metricas(PORTA_METRICAS)

    servidor = grpc.server(
        futures.ThreadPoolExecutor(max_workers=MAX_WORKERS),
        interceptors=[InterceptorDeMetricas()],
    )
    data_pb2_grpc.add_PatientDataServiceServicer_to_server(Servico(repo), servidor)
    servidor.add_insecure_port(f"[::]:{PORTA_GRPC}")
    servidor.start()
    log.info("data ouvindo gRPC=%d metrics=%d", PORTA_GRPC, PORTA_METRICAS)
    try:
        servidor.wait_for_termination()
    finally:
        repo.fechar()


if __name__ == "__main__":
    main()
