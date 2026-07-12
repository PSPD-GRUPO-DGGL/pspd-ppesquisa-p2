"""Authorization Service — servidor gRPC."""

from __future__ import annotations

import logging
import os
from concurrent import futures

import grpc

import auth_pb2
import auth_pb2_grpc
import comum_pb2
from config import conninfo
from metricas import AUTH_DECISOES, InterceptorDeMetricas, servir_metricas
from regras import NOMES_NIVEL, normalizar_role, nivel_para_escopo_pesquisador
from repositorio import RepositorioAuth

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format='{"ts":"%(asctime)s","nivel":"%(levelname)s","msg":"%(message)s"}',
)
log = logging.getLogger("auth")

PORTA_GRPC = int(os.environ.get("GRPC_PORT", "50051"))
PORTA_METRICAS = int(os.environ.get("METRICS_PORT", "8000"))
MAX_WORKERS = int(os.environ.get("GRPC_MAX_WORKERS", "8"))


class Servico(auth_pb2_grpc.AuthServiceServicer):
    def __init__(self, repo: RepositorioAuth):
        self.repo = repo

    def _resposta(
        self,
        *,
        role: str,
        permitido: bool,
        nivel: int,
        ids_autorizados: list[str] | None = None,
        motivo: str = "",
    ) -> auth_pb2.RespostaAutorizacao:
        decisao = "ALLOW" if permitido else "DENY"
        AUTH_DECISOES.labels(
            decisao=decisao,
            nivel=NOMES_NIVEL.get(nivel, "DESCONHECIDO"),
            role=role or "DESCONHECIDO",
            motivo=motivo or "ok",
        ).inc()
        return auth_pb2.RespostaAutorizacao(
            permitido=permitido,
            nivel=nivel,
            ids_autorizados=ids_autorizados or [],
            motivo_negacao=motivo,
        )

    def AutorizarConsulta(self, requisicao, contexto):
        role = normalizar_role(requisicao.role)
        username = requisicao.username.strip()
        escopo = requisicao.escopo.strip()
        ids = list(dict.fromkeys(requisicao.ids_pacientes))

        if not username:
            return self._resposta(
                role=role, permitido=False, nivel=comum_pb2.DENY, motivo="username_ausente"
            )

        if role == "MEDICO":
            autorizados = self.repo.pacientes_vinculados(
                username=username,
                ids_pacientes=ids,
                tipo_vinculo="ATTENDING",
            )
            if autorizados:
                return self._resposta(
                    role=role,
                    permitido=True,
                    nivel=comum_pb2.FULL,
                    ids_autorizados=autorizados,
                )
            return self._resposta(
                role=role,
                permitido=False,
                nivel=comum_pb2.DENY,
                motivo="sem_vinculo_ativo",
            )

        if role == "ESTAGIARIO":
            autorizados = self.repo.pacientes_vinculados(
                username=username,
                ids_pacientes=ids,
                tipo_vinculo="TRAINEE",
                exigir_supervisor=True,
            )
            if autorizados:
                return self._resposta(
                    role=role,
                    permitido=True,
                    nivel=comum_pb2.PARTIAL,
                    ids_autorizados=autorizados,
                )
            return self._resposta(
                role=role,
                permitido=False,
                nivel=comum_pb2.DENY,
                motivo="sem_supervisao_ativa",
            )

        if role == "PESQUISADOR":
            nivel = nivel_para_escopo_pesquisador(escopo)
            if nivel is None:
                return self._resposta(
                    role=role,
                    permitido=False,
                    nivel=comum_pb2.DENY,
                    motivo="escopo_invalido",
                )

            if escopo == "MeusProjetos":
                return self._resposta(
                    role=role,
                    permitido=True,
                    nivel=comum_pb2.NIVEL_INDEFINIDO,
                )

            projeto = self.repo.projeto(requisicao.id_projeto)
            if projeto is None:
                return self._resposta(
                    role=role,
                    permitido=False,
                    nivel=comum_pb2.DENY,
                    motivo="projeto_inexistente",
                )
            if projeto.username_pesquisador != username:
                return self._resposta(
                    role=role,
                    permitido=False,
                    nivel=comum_pb2.DENY,
                    motivo="projeto_de_outro_pesquisador",
                )
            if projeto.status == "EXPIRED" or not projeto.vigente:
                return self._resposta(
                    role=role,
                    permitido=False,
                    nivel=comum_pb2.DENY,
                    motivo="projeto_expirado",
                )
            if projeto.status != "APPROVED":
                return self._resposta(
                    role=role,
                    permitido=False,
                    nivel=comum_pb2.DENY,
                    motivo="projeto_nao_aprovado",
                )
            if projeto.codigo_condicao_clinica.upper() != requisicao.codigo_condicao.strip().upper():
                return self._resposta(
                    role=role,
                    permitido=False,
                    nivel=comum_pb2.DENY,
                    motivo="condicao_fora_do_projeto",
                )

            return self._resposta(role=role, permitido=True, nivel=nivel)

        return self._resposta(
            role=role,
            permitido=False,
            nivel=comum_pb2.DENY,
            motivo="role_desconhecida",
        )


def main() -> None:
    repo = RepositorioAuth(conninfo())
    servir_metricas(PORTA_METRICAS)

    servidor = grpc.server(
        futures.ThreadPoolExecutor(max_workers=MAX_WORKERS),
        interceptors=[InterceptorDeMetricas()],
    )
    auth_pb2_grpc.add_AuthServiceServicer_to_server(Servico(repo), servidor)
    servidor.add_insecure_port(f"[::]:{PORTA_GRPC}")
    servidor.start()
    log.info("auth ouvindo gRPC=%d metrics=%d", PORTA_GRPC, PORTA_METRICAS)
    try:
        servidor.wait_for_termination()
    finally:
        repo.fechar()


if __name__ == "__main__":
    main()
