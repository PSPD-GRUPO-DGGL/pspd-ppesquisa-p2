"""Cliente de fumaça: exercita os quatro níveis contra um servidor real e
verifica que nenhum identificador direto escapou.

Uso:  ANON_SALT=x python cliente_teste.py [host:porta]
"""

from __future__ import annotations

import json
import sys

import grpc

import comum_pb2
import transform_pb2
import transform_pb2_grpc

PROIBIDOS_POR_NIVEL = {
    "PARTIAL": ["12345678901", "700000000000001", "João da Silva Cardoso"],
    "ANONYMIZED": ["12345678901", "700000000000001", "João da Silva Cardoso",
                   "P000001", "Brasília", "1970-05-10"],
    "AGGREGATED": ["12345678901", "P000001", "Patient"],
}


def _dados() -> comum_pb2.ConjuntoDadosClinicos:
    return comum_pb2.ConjuntoDadosClinicos(
        pacientes=[comum_pb2.Paciente(
            id_paciente="P000001", nome="João da Silva Cardoso",
            data_nascimento="1970-05-10", genero="male",
            cidade="Brasília", estado="DF",
            cpf="12345678901", cns="700000000000001",
        )],
        atendimentos=[comum_pb2.Atendimento(
            id_atendimento="E00000001", id_paciente="P000001",
            data_inicio="2023-02-10T08:00:00", data_fim="2023-02-10T11:00:00",
            tipo_atendimento="AMBULATORIAL", setor="ENDOCRINOLOGY",
        )],
        eventos=[
            comum_pb2.EventoClinico(
                id_evento="1", id_paciente="P000001", id_atendimento="E00000001",
                tipo_evento="CONDITION", codigo_tipo_evento="DIABETES",
                descricao="Diabetes Mellitus Tipo 2", data_evento="2023-02-10"),
            comum_pb2.EventoClinico(
                id_evento="2", id_paciente="P000001", id_atendimento="E00000001",
                tipo_evento="OBSERVATION", codigo_tipo_evento="HBA1C",
                descricao="Hemoglobina Glicada", data_evento="2023-02-10",
                valor=8.1, unidade="%"),
            comum_pb2.EventoClinico(
                id_evento="3", id_paciente="P000001", id_atendimento="E00000001",
                tipo_evento="MEDICATION", codigo_tipo_evento="METFORMIN",
                descricao="Metformina 850 mg", data_evento="2023-02-10",
                valor=850.0, unidade="mg"),
        ],
    )


def _agregado() -> comum_pb2.ResultadoAgregado:
    return comum_pb2.ResultadoAgregado(
        codigo_condicao="Diabetes",
        total_pacientes=15750,
        distribuicao_sexo=[
            comum_pb2.Contagem(chave="female", valor=11000, percentual=69.8),
            comum_pb2.Contagem(chave="male", valor=4750, percentual=30.2),
        ],
        estatisticas_exames=[
            comum_pb2.Estatistica(nome="HbA1c", media=8.41, mediana=8.38,
                                  desvio_padrao=0.86, n=41230, unidade="%"),
        ],
    )


def main() -> int:
    alvo = sys.argv[1] if len(sys.argv) > 1 else "localhost:50053"
    canal = grpc.insecure_channel(alvo)
    stub = transform_pb2_grpc.DataTransformServiceStub(canal)

    falhas = 0
    for nome, nivel in (("FULL", comum_pb2.FULL), ("PARTIAL", comum_pb2.PARTIAL),
                        ("ANONYMIZED", comum_pb2.ANONYMIZED),
                        ("AGGREGATED", comum_pb2.AGGREGATED)):
        if nivel == comum_pb2.AGGREGATED:
            req = transform_pb2.RequisicaoTransformacao(
                nivel=nivel, escopo="EstatisticasCoorte", agregado=_agregado())
        else:
            req = transform_pb2.RequisicaoTransformacao(
                nivel=nivel, escopo="ResumoClinico", dados=_dados())

        resp = stub.TransformarParaFHIR(req)
        bruto = resp.fhir_bundle_json

        assert resp.nivel_aplicado == nivel, "servidor não honrou o nível pedido"

        vazou = [p for p in PROIBIDOS_POR_NIVEL.get(nome, []) if p in bruto]
        estado = "VAZOU " + ", ".join(vazou) if vazou else "limpo"
        if vazou:
            falhas += 1

        print(f"[{nome:<11}] recursos={resp.total_recursos:<3} "
              f"bytes={len(bruto):<6} {estado}")
        print("   " + json.dumps(json.loads(bruto), ensure_ascii=False)[:180] + "...")

    try:
        stub.TransformarParaFHIR(transform_pb2.RequisicaoTransformacao(
            nivel=comum_pb2.DENY, escopo="ResumoClinico", dados=_dados()))
        print("[DENY       ] FALHA: servidor aceitou transformar uma negação")
        falhas += 1
    except grpc.RpcError as erro:
        assert erro.code() == grpc.StatusCode.INVALID_ARGUMENT, erro.code()
        print(f"[DENY       ] rejeitado corretamente: {erro.code().name}")

    print("\nOK" if not falhas else f"\n{falhas} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
