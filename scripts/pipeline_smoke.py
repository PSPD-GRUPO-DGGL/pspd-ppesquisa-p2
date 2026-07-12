"""Smoke ponta a ponta gRPC: Auth -> Data -> Transform.

O script assume que os três serviços já estão de pé localmente e que as
variáveis AUTH_SMOKE_*/DATA_SMOKE_* foram preenchidas pelo shell wrapper.
"""

from __future__ import annotations

import json
import os
import sys

import grpc

import auth_pb2
import auth_pb2_grpc
import comum_pb2
import data_pb2
import data_pb2_grpc
import transform_pb2
import transform_pb2_grpc


AUTH_ADDR = os.environ.get("AUTH_ADDR", "localhost:50051")
DATA_ADDR = os.environ.get("DATA_ADDR", "localhost:50052")
TRANSFORM_ADDR = os.environ.get("TRANSFORM_ADDR", "localhost:50053")


def auth_stub():
    return auth_pb2_grpc.AuthServiceStub(grpc.insecure_channel(AUTH_ADDR))


def data_stub():
    return data_pb2_grpc.PatientDataServiceStub(grpc.insecure_channel(DATA_ADDR))


def transform_stub():
    return transform_pb2_grpc.DataTransformServiceStub(
        grpc.insecure_channel(TRANSFORM_ADDR)
    )


def autorizar(**kwargs):
    return auth_stub().AutorizarConsulta(auth_pb2.RequisicaoAutorizacao(**kwargs))


def transformar(nivel: int, escopo: str, *, dados=None, agregado=None):
    req = transform_pb2.RequisicaoTransformacao(nivel=nivel, escopo=escopo)
    if dados is not None:
        req.dados.CopyFrom(dados)
    if agregado is not None:
        req.agregado.CopyFrom(agregado)
    return transform_stub().TransformarParaFHIR(req)


def assert_json_sem(bruto: str, proibidos: list[str]) -> None:
    vazamentos = [p for p in proibidos if p and p in bruto]
    if vazamentos:
        raise AssertionError("vazou no JSON: " + ", ".join(vazamentos))


def assert_anonymized_estrutural(body: dict, dados) -> None:
    ids_reais = {p.id_paciente for p in dados.pacientes}
    nomes = {p.nome for p in dados.pacientes}
    cpfs = {p.cpf for p in dados.pacientes}
    cns = {p.cns for p in dados.pacientes}

    for entrada in body.get("entry", []):
        recurso = entrada.get("resource", {})
        tipo = recurso.get("resourceType")

        if tipo == "Patient":
            if recurso.get("id") in ids_reais:
                raise AssertionError(f"Patient.id real vazou: {recurso.get('id')}")
            if not str(recurso.get("id", "")).startswith("hash"):
                raise AssertionError(f"Patient.id não é pseudônimo: {recurso.get('id')}")
            if "identifier" in recurso:
                raise AssertionError("Patient.identifier vazou em ANONYMIZED")
            if "name" in recurso:
                raise AssertionError("Patient.name vazou em ANONYMIZED")
            if "birthDate" in recurso:
                raise AssertionError("Patient.birthDate exata vazou em ANONYMIZED")
            for endereco in recurso.get("address", []):
                if "city" in endereco:
                    raise AssertionError("Patient.address.city vazou em ANONYMIZED")

        subject = recurso.get("subject", {})
        ref = subject.get("reference", "")
        if ref.startswith("Patient/") and not ref.startswith("Patient/hash"):
            raise AssertionError(f"subject.reference real vazou: {ref}")

    bruto_pacientes = json.dumps(
        [
            entrada.get("resource", {})
            for entrada in body.get("entry", [])
            if entrada.get("resource", {}).get("resourceType") == "Patient"
        ],
        ensure_ascii=False,
    )
    assert_json_sem(bruto_pacientes, list(ids_reais | nomes | cpfs | cns))


def imprimir_bundle(nome: str, resp) -> dict:
    body = json.loads(resp.fhir_bundle_json)
    print(
        f"[OK] {nome}: resourceType={body.get('resourceType')} "
        f"recursos={resp.total_recursos} nivel={comum_pb2.NivelAcesso.Name(resp.nivel_aplicado)}"
    )
    return body


def fluxo_full() -> str:
    username = os.environ["AUTH_SMOKE_MED_USER"]
    patient = os.environ["AUTH_SMOKE_MED_PATIENT"]

    decisao = autorizar(
        username=username,
        role="MEDICO",
        escopo="ResumoClinico",
        ids_pacientes=[patient],
    )
    assert decisao.permitido, decisao
    assert decisao.nivel == comum_pb2.FULL

    dados = data_stub().BuscarPacientes(
        data_pb2.FiltroPacientes(
            ids_pacientes=list(decisao.ids_autorizados),
            incluir_atendimentos=True,
            incluir_eventos=True,
            limite_eventos=20,
        )
    )
    assert len(dados.pacientes) == 1

    resp = transformar(comum_pb2.FULL, "ResumoClinico", dados=dados)
    body = imprimir_bundle("FULL medico", resp)
    bruto = resp.fhir_bundle_json
    assert body["resourceType"] == "Bundle"
    assert patient in bruto
    assert dados.pacientes[0].cpf in bruto
    return patient


def fluxo_deny() -> None:
    decisao = autorizar(
        username=os.environ["AUTH_SMOKE_MED_USER"],
        role="MEDICO",
        escopo="ResumoClinico",
        ids_pacientes=[os.environ["AUTH_SMOKE_MED_DENIED_PATIENT"]],
    )
    assert not decisao.permitido
    assert decisao.nivel == comum_pb2.DENY
    assert decisao.motivo_negacao == "sem_vinculo_ativo"
    print(f"[OK] DENY medico: motivo={decisao.motivo_negacao}")


def fluxo_aggregated() -> None:
    condition = os.environ["AUTH_SMOKE_CONDITION"]
    decisao = autorizar(
        username=os.environ["AUTH_SMOKE_PES_USER"],
        role="PESQUISADOR",
        escopo="EstatisticasCoorte",
        id_projeto=os.environ["AUTH_SMOKE_PROJECT"],
        codigo_condicao=condition,
    )
    assert decisao.permitido, decisao
    assert decisao.nivel == comum_pb2.AGGREGATED

    agregado = data_stub().AgregarCoorte(
        data_pb2.FiltroCoorte(codigo_condicao=condition)
    )
    assert agregado.total_pacientes > 0

    resp = transformar(comum_pb2.AGGREGATED, "EstatisticasCoorte", agregado=agregado)
    body = imprimir_bundle("AGGREGATED pesquisador", resp)
    assert body["resourceType"] == "MeasureReport"
    assert_json_sem(resp.fhir_bundle_json, ["Patient/", "cpf", "cns"])


def fluxo_anonymized() -> None:
    condition = os.environ["AUTH_SMOKE_CONDITION"]
    decisao = autorizar(
        username=os.environ["AUTH_SMOKE_PES_USER"],
        role="PESQUISADOR",
        escopo="ExamesCoorte",
        id_projeto=os.environ["AUTH_SMOKE_PROJECT"],
        codigo_condicao=condition,
    )
    assert decisao.permitido, decisao
    assert decisao.nivel == comum_pb2.ANONYMIZED

    dados = data_stub().BuscarCoorte(
        data_pb2.FiltroCoorte(codigo_condicao=condition, limite_pacientes=5)
    )
    assert len(dados.pacientes) > 0
    ids_reais = [p.id_paciente for p in dados.pacientes]
    nomes = [p.nome for p in dados.pacientes]
    cpfs = [p.cpf for p in dados.pacientes]

    resp = transformar(comum_pb2.ANONYMIZED, "ExamesCoorte", dados=dados)
    body = imprimir_bundle("ANONYMIZED pesquisador", resp)
    assert body["resourceType"] == "Bundle"
    assert "hash" in resp.fhir_bundle_json
    assert_anonymized_estrutural(body, dados)


def main() -> int:
    try:
        fluxo_full()
        fluxo_deny()
        fluxo_aggregated()
        fluxo_anonymized()
    except Exception as exc:
        print(f"[FALHA] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
