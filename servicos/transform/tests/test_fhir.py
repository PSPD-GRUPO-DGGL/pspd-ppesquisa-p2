"""Testes da montagem do Bundle HL7/FHIR."""

import json

import pytest

from anonimizacao import ANONYMIZED, FULL, PARTIAL, mapa_de_ids, projetar_paciente, pseudonimo
from fhir import montar_bundle, montar_measure_report

PACIENTE = {
    "id_paciente": "P000001",
    "nome": "João da Silva Cardoso",
    "data_nascimento": "1970-05-10",
    "genero": "male",
    "cidade": "Brasília",
    "estado": "DF",
    "cpf": "12345678901",
    "cns": "700000000000001",
}

ATENDIMENTO = {
    "id_atendimento": "E00000001",
    "id_paciente": "P000001",
    "data_inicio": "2023-02-10T08:00:00",
    "data_fim": "2023-02-10T11:00:00",
    "tipo_atendimento": "AMBULATORIAL",
    "setor": "Endocrinologia",
}

CONDICAO = {
    "id_evento": 1, "id_paciente": "P000001", "id_atendimento": "E00000001",
    "tipo_evento": "CONDITION", "codigo_tipo_evento": "DIABETES",
    "descricao": "Diabetes Mellitus Tipo 2", "data_evento": "2023-02-10",
    "valor": 0.0, "unidade": "",
}
OBSERVACAO = {
    "id_evento": 2, "id_paciente": "P000001", "id_atendimento": "E00000001",
    "tipo_evento": "OBSERVATION", "codigo_tipo_evento": "HBA1C",
    "descricao": "Hemoglobina Glicada", "data_evento": "2023-02-10",
    "valor": 8.1, "unidade": "%",
}
MEDICACAO = {
    "id_evento": 3, "id_paciente": "P000001", "id_atendimento": "E00000001",
    "tipo_evento": "MEDICATION", "codigo_tipo_evento": "METFORMIN",
    "descricao": "Metformina 850 mg", "data_evento": "2023-02-10",
    "valor": 850.0, "unidade": "mg",
}
EVENTOS = [CONDICAO, OBSERVACAO, MEDICACAO]


@pytest.fixture(autouse=True)
def _salt(monkeypatch):
    monkeypatch.setenv("ANON_SALT", "salt-de-teste")


def construir(nivel):
    projetados = [projetar_paciente(PACIENTE, nivel)]
    ids = mapa_de_ids([PACIENTE], nivel)
    return montar_bundle(projetados, [ATENDIMENTO], EVENTOS, nivel, ids)


def tipos(bundle):
    return [e["resource"]["resourceType"] for e in bundle["entry"]]


class TestBundle:
    def test_envelope(self):
        bundle, _ = construir(FULL)
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "collection"
        assert "timestamp" in bundle

    def test_um_resource_por_tipo_de_evento(self):
        bundle, contagem = construir(FULL)
        assert tipos(bundle) == [
            "Patient", "Encounter", "Condition", "Observation", "MedicationRequest",
        ]
        assert contagem == {
            "Patient": 1, "Encounter": 1, "Condition": 1,
            "Observation": 1, "MedicationRequest": 1,
        }

    def test_evento_de_tipo_desconhecido_e_ignorado(self):
        estranho = dict(OBSERVACAO, tipo_evento="Ritual", id_evento=9)
        projetados = [projetar_paciente(PACIENTE, FULL)]
        bundle, contagem = montar_bundle(projetados, [], [estranho], FULL, mapa_de_ids([PACIENTE], FULL))
        assert tipos(bundle) == ["Patient"]
        assert contagem == {"Patient": 1}

    def test_evento_de_paciente_nao_autorizado_e_descartado(self):
        intruso = dict(OBSERVACAO, id_paciente="P999999", id_evento=99)
        projetados = [projetar_paciente(PACIENTE, FULL)]
        bundle, _ = montar_bundle(projetados, [], [intruso], FULL, mapa_de_ids([PACIENTE], FULL))
        assert tipos(bundle) == ["Patient"]
        assert "P999999" not in json.dumps(bundle)


class TestPatientFull:
    def test_identifier_traz_cpf_e_cns_com_system(self):
        bundle, _ = construir(FULL)
        paciente = bundle["entry"][0]["resource"]
        sistemas = {i["system"]: i["value"] for i in paciente["identifier"]}
        assert sistemas["urn:oid:2.16.76.1.3.1"] == "12345678901"
        assert sistemas["https://fhir.saude.gov.br/sid/cns"] == "700000000000001"

    def test_birthdate_exata(self):
        bundle, _ = construir(FULL)
        assert bundle["entry"][0]["resource"]["birthDate"] == "1970-05-10"


class TestPatientPartial:
    def test_sem_identifier(self):
        bundle, _ = construir(PARTIAL)
        assert "identifier" not in bundle["entry"][0]["resource"]

    def test_birthdate_so_o_ano(self):
        bundle, _ = construir(PARTIAL)
        assert bundle["entry"][0]["resource"]["birthDate"] == "1970"

    def test_bundle_serializado_nao_contem_cpf_nem_nome(self):
        bundle, _ = construir(PARTIAL)
        bruto = json.dumps(bundle, ensure_ascii=False)
        assert "12345678901" not in bruto
        assert "700000000000001" not in bruto
        assert "João da Silva Cardoso" not in bruto


class TestPatientAnonymized:
    def test_faixa_etaria_vai_como_extension(self):
        bundle, _ = construir(ANONYMIZED)
        paciente = bundle["entry"][0]["resource"]
        assert paciente["extension"][0]["valueString"] in {"18-39", "40-59", "60-79", "80+"}
        assert "birthDate" not in paciente

    def test_endereco_perde_a_cidade(self):
        bundle, _ = construir(ANONYMIZED)
        endereco = bundle["entry"][0]["resource"]["address"][0]
        assert endereco == {"state": "DF"}

    def test_referencias_apontam_para_o_pseudonimo(self):
        bundle, _ = construir(ANONYMIZED)
        esperado = f"Patient/{pseudonimo('P000001')}"
        for entrada in bundle["entry"][1:]:
            assert entrada["resource"]["subject"]["reference"] == esperado

    def test_bundle_serializado_nao_vaza_id_real_nem_pii(self):
        bundle, _ = construir(ANONYMIZED)
        bruto = json.dumps(bundle, ensure_ascii=False)
        for proibido in ("P000001", "12345678901", "700000000000001",
                         "João da Silva Cardoso", "Brasília", "1970-05-10"):
            assert proibido not in bruto, f"vazou: {proibido}"


class TestEncounter:
    @pytest.mark.parametrize(
        "tipo,codigo",
        [("AMBULATORIAL", "AMB"), ("FOLLOW_UP", "AMB"),
         ("EMERGENCY", "EMER"), ("INPATIENT", "IMP"),
         ("ICU", "ACUTE"), ("TELEHEALTH", "VR")],
    )
    def test_class_code_do_vocabulario_hl7_v3(self, tipo, codigo):
        atendimento = dict(ATENDIMENTO, tipo_atendimento=tipo)
        projetados = [projetar_paciente(PACIENTE, FULL)]
        bundle, _ = montar_bundle(projetados, [atendimento], [], FULL, mapa_de_ids([PACIENTE], FULL))
        assert bundle["entry"][1]["resource"]["class"]["code"] == codigo

    def test_tipo_desconhecido_cai_em_ambulatory(self):
        atendimento = dict(ATENDIMENTO, tipo_atendimento="DESCONHECIDO")
        projetados = [projetar_paciente(PACIENTE, FULL)]
        bundle, _ = montar_bundle(projetados, [atendimento], [], FULL, mapa_de_ids([PACIENTE], FULL))
        assert bundle["entry"][1]["resource"]["class"]["code"] == "AMB"


class TestMeasureReport:
    AGREGADO = {
        "codigo_condicao": "Diabetes",
        "total_pacientes": 15750,
        "distribuicao_sexo": [
            {"chave": "female", "valor": 11000, "percentual": 69.8},
            {"chave": "male", "valor": 4750, "percentual": 30.2},
        ],
        "distribuicao_faixa_etaria": [],
        "distribuicao_setor": [],
        "frequencia_medicamentos": [],
        "estatisticas_exames": [
            {"nome": "HbA1c", "media": 8.41, "mediana": 8.38,
             "desvio_padrao": 0.86, "n": 41230, "unidade": "%"},
        ],
    }

    def test_tipo_summary_e_sem_paciente(self):
        relatorio, contagem = montar_measure_report(self.AGREGADO)
        assert relatorio["resourceType"] == "MeasureReport"
        assert relatorio["type"] == "summary"
        assert contagem == {"MeasureReport": 1}

    def test_total_e_estratificador_de_genero(self):
        relatorio, _ = montar_measure_report(self.AGREGADO)
        grupo = relatorio["group"][0]
        assert grupo["population"][0]["count"] == 15750
        estrato = grupo["stratifier"][0]
        assert estrato["code"][0]["text"] == "genero"
        assert estrato["stratum"][0]["population"][0]["count"] == 11000

    def test_estatisticas_continuas_vao_como_extension(self):
        relatorio, _ = montar_measure_report(self.AGREGADO)
        urls = {e["url"] for e in relatorio["extension"][0]["extension"]}
        assert {"codigo", "media", "mediana", "n"} <= urls

    def test_estratificador_vazio_e_omitido(self):
        relatorio, _ = montar_measure_report(self.AGREGADO)
        rotulos = [s["code"][0]["text"] for s in relatorio["group"][0]["stratifier"]]
        assert rotulos == ["genero"]

    def test_nenhum_identificador_no_json(self):
        relatorio, _ = montar_measure_report(self.AGREGADO)
        bruto = json.dumps(relatorio)
        assert "Patient" not in bruto
        assert "hash" not in bruto
