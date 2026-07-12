"""Cliente de fumaça do Authorization Service."""

from __future__ import annotations

import sys
import os

import grpc

import auth_pb2
import auth_pb2_grpc
import comum_pb2


def conferir(nome: str, resp, permitido: bool, nivel: int, motivo: str = "") -> int:
    ok = (
        resp.permitido == permitido
        and resp.nivel == nivel
        and (not motivo or resp.motivo_negacao == motivo)
    )
    estado = "OK" if ok else "FALHA"
    print(
        f"[{estado}] {nome}: permitido={resp.permitido} "
        f"nivel={comum_pb2.NivelAcesso.Name(resp.nivel)} motivo={resp.motivo_negacao}"
    )
    return 0 if ok else 1


def main() -> int:
    alvo = sys.argv[1] if len(sys.argv) > 1 else "localhost:50051"
    stub = auth_pb2_grpc.AuthServiceStub(grpc.insecure_channel(alvo))
    falhas = 0

    med_user = os.environ.get("AUTH_SMOKE_MED_USER", "med.cardoso")
    med_patient = os.environ.get("AUTH_SMOKE_MED_PATIENT", "P000002")
    med_denied_patient = os.environ.get("AUTH_SMOKE_MED_DENIED_PATIENT", "P049000")
    pes_user = os.environ.get("AUTH_SMOKE_PES_USER", "pes.souza")
    project = os.environ.get("AUTH_SMOKE_PROJECT", "PRJ01")
    condition = os.environ.get("AUTH_SMOKE_CONDITION", "Diabetes")

    falhas += conferir(
        "medico vinculado",
        stub.AutorizarConsulta(
            auth_pb2.RequisicaoAutorizacao(
                username=med_user,
                role="MEDICO",
                escopo="ResumoClinico",
                ids_pacientes=[med_patient],
            )
        ),
        True,
        comum_pb2.FULL,
    )
    falhas += conferir(
        "medico sem vinculo",
        stub.AutorizarConsulta(
            auth_pb2.RequisicaoAutorizacao(
                username=med_user,
                role="MEDICO",
                escopo="ResumoClinico",
                ids_pacientes=[med_denied_patient],
            )
        ),
        False,
        comum_pb2.DENY,
        "sem_vinculo_ativo",
    )
    falhas += conferir(
        "pesquisador agregado",
        stub.AutorizarConsulta(
            auth_pb2.RequisicaoAutorizacao(
                username=pes_user,
                role="PESQUISADOR",
                escopo="EstatisticasCoorte",
                id_projeto=project,
                codigo_condicao=condition,
            )
        ),
        True,
        comum_pb2.AGGREGATED,
    )

    print("\nOK" if not falhas else f"\n{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
