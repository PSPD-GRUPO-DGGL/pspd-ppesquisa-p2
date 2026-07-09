"""Testes da projeção por nível de acesso."""

from datetime import date

import pytest

from anonimizacao import (
    AGGREGATED,
    ANONYMIZED,
    FULL,
    PARTIAL,
    SaltAusente,
    faixa_etaria,
    idade,
    iniciais,
    mapa_de_ids,
    projetar_paciente,
    pseudonimo,
)

HOJE = date(2026, 7, 9)

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

IDENTIFICADORES_DIRETOS = ("12345678901", "700000000000001", "João da Silva Cardoso")


@pytest.fixture(autouse=True)
def _salt(monkeypatch):
    monkeypatch.setenv("ANON_SALT", "salt-de-teste")


class TestIniciais:
    def test_descarta_particulas(self):
        assert iniciais("João da Silva Cardoso") == "J.S.C."

    def test_nome_simples(self):
        assert iniciais("Ana Souza") == "A.S."

    def test_varias_particulas(self):
        assert iniciais("Maria dos Santos de Oliveira e Costa") == "M.S.O.C."


class TestIdadeEFaixa:
    def test_aniversario_ainda_nao_ocorreu(self):
        assert idade("1970-05-10", HOJE) == 56

    def test_aniversario_amanha(self):
        assert idade("1970-07-10", HOJE) == 55

    def test_aniversario_hoje(self):
        assert idade("1970-07-09", HOJE) == 56

    @pytest.mark.parametrize(
        "nascimento,esperado",
        [
            ("2000-01-01", "18-39"),
            ("1980-01-01", "40-59"),
            ("1960-01-01", "60-79"),
            ("1930-01-01", "80+"),
        ],
    )
    def test_faixas(self, nascimento, esperado):
        assert faixa_etaria(nascimento, HOJE) == esperado


class TestPseudonimo:
    def test_estavel_para_o_mesmo_paciente(self):
        assert pseudonimo("P000001") == pseudonimo("P000001")

    def test_distinto_entre_pacientes(self):
        assert pseudonimo("P000001") != pseudonimo("P000002")

    def test_nao_contem_o_id_original(self):
        assert "P000001" not in pseudonimo("P000001")

    def test_muda_com_o_salt(self, monkeypatch):
        primeiro = pseudonimo("P000001")
        monkeypatch.setenv("ANON_SALT", "outro-salt")
        assert pseudonimo("P000001") != primeiro

    def test_sem_salt_falha_alto(self, monkeypatch):
        monkeypatch.delenv("ANON_SALT", raising=False)
        with pytest.raises(SaltAusente):
            pseudonimo("P000001")


class TestProjecaoFull:
    def test_preserva_tudo(self):
        p = projetar_paciente(PACIENTE, FULL, HOJE)
        assert p["cpf"] == "12345678901"
        assert p["cns"] == "700000000000001"
        assert p["nome"] == "João da Silva Cardoso"
        assert p["data_nascimento"] == "1970-05-10"
        assert p["cidade"] == "Brasília"


class TestProjecaoPartial:
    def test_remove_identificadores_diretos(self):
        p = projetar_paciente(PACIENTE, PARTIAL, HOJE)
        assert "cpf" not in p
        assert "cns" not in p

    def test_nome_vira_iniciais(self):
        assert projetar_paciente(PACIENTE, PARTIAL, HOJE)["nome"] == "J.S.C."

    def test_data_nascimento_vira_ano(self):
        assert projetar_paciente(PACIENTE, PARTIAL, HOJE)["data_nascimento"] == "1970"

    def test_mantem_cidade_e_estado(self):
        p = projetar_paciente(PACIENTE, PARTIAL, HOJE)
        assert p["cidade"] == "Brasília" and p["estado"] == "DF"

    def test_nenhum_identificador_direto_sobra(self):
        valores = " ".join(str(v) for v in projetar_paciente(PACIENTE, PARTIAL, HOJE).values())
        for proibido in IDENTIFICADORES_DIRETOS:
            assert proibido not in valores


class TestProjecaoAnonymized:
    def test_id_vira_pseudonimo(self):
        p = projetar_paciente(PACIENTE, ANONYMIZED, HOJE)
        assert p["id"].startswith("hash")
        assert p["id"] != "P000001"

    def test_remove_nome_cpf_cns_cidade_e_data(self):
        p = projetar_paciente(PACIENTE, ANONYMIZED, HOJE)
        for campo in ("nome", "cpf", "cns", "cidade", "data_nascimento"):
            assert campo not in p

    def test_mantem_estado_genero_e_faixa(self):
        p = projetar_paciente(PACIENTE, ANONYMIZED, HOJE)
        assert p["estado"] == "DF"
        assert p["genero"] == "male"
        assert p["faixa_etaria"] == "40-59"

    def test_nenhum_identificador_direto_sobra(self):
        valores = " ".join(str(v) for v in projetar_paciente(PACIENTE, ANONYMIZED, HOJE).values())
        for proibido in IDENTIFICADORES_DIRETOS + ("P000001",):
            assert proibido not in valores


class TestProjecaoAggregated:
    def test_recusa_projetar_individuo(self):
        with pytest.raises(ValueError):
            projetar_paciente(PACIENTE, AGGREGATED, HOJE)


class TestMapaDeIds:
    def test_anonymized_traduz_para_pseudonimo(self):
        mapa = mapa_de_ids([PACIENTE], ANONYMIZED)
        assert mapa["P000001"] == pseudonimo("P000001")

    @pytest.mark.parametrize("nivel", [FULL, PARTIAL])
    def test_demais_niveis_sao_identidade(self, nivel):
        assert mapa_de_ids([PACIENTE], nivel) == {"P000001": "P000001"}
