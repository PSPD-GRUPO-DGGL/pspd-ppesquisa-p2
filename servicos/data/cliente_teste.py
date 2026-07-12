"""Cliente de fumaça do Patient Data Service."""

from __future__ import annotations

import sys
import os

import grpc

import data_pb2
import data_pb2_grpc


def main() -> int:
    alvo = sys.argv[1] if len(sys.argv) > 1 else "localhost:50052"
    stub = data_pb2_grpc.PatientDataServiceStub(grpc.insecure_channel(alvo))
    falhas = 0
    patient_id = os.environ.get("DATA_SMOKE_PATIENT", "P000002")
    condition = os.environ.get("DATA_SMOKE_CONDITION", "Diabetes")

    dados = stub.BuscarPacientes(data_pb2.FiltroPacientes(
        ids_pacientes=[patient_id],
        incluir_atendimentos=True,
        incluir_eventos=True,
        limite_eventos=20,
    ))
    print(f"[BuscarPacientes] pacientes={len(dados.pacientes)} "
          f"atendimentos={len(dados.atendimentos)} eventos={len(dados.eventos)}")
    falhas += 0 if dados.pacientes else 1

    coorte = stub.BuscarCoorte(data_pb2.FiltroCoorte(
        codigo_condicao=condition,
        limite_pacientes=5,
    ))
    print(f"[BuscarCoorte] pacientes={len(coorte.pacientes)} eventos={len(coorte.eventos)}")
    falhas += 0 if coorte.pacientes else 1

    agregado = stub.AgregarCoorte(data_pb2.FiltroCoorte(codigo_condicao=condition))
    print(f"[AgregarCoorte] total={agregado.total_pacientes} "
          f"sexo={len(agregado.distribuicao_sexo)} exames={len(agregado.estatisticas_exames)}")
    falhas += 0 if agregado.total_pacientes > 0 else 1

    print("\nOK" if not falhas else f"\n{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
