from repositorio import DadosClinicos
from conversao import agregado, conjunto, lista_projetos, numero


def test_conjunto_converte_linhas_sql_para_proto():
    dados = DadosClinicos(
        pacientes=[{
            "id_paciente": "P000001",
            "nome": "Ana Silva",
            "data_nascimento": "1980-01-02",
            "genero": "female",
            "cidade": "Brasília",
            "estado": "DF",
            "cpf": "12345678901",
            "cns": "700000000000001",
        }],
        atendimentos=[{
            "id_atendimento": "E00000001",
            "id_paciente": "P000001",
            "data_inicio": "2024-01-01 10:00:00",
            "data_fim": None,
            "tipo_atendimento": "Ambulatorial",
            "setor": "Cardiologia",
        }],
        eventos=[{
            "id_evento": "1",
            "id_paciente": "P000001",
            "id_atendimento": "E00000001",
            "tipo_evento": "Observacao",
            "codigo_tipo_evento": "HbA1c",
            "descricao": "Hemoglobina Glicada",
            "data_evento": "2024-01-01",
            "valor": 8.1,
            "unidade": "%",
        }],
    )
    msg = conjunto(dados)
    assert msg.pacientes[0].id_paciente == "P000001"
    assert msg.atendimentos[0].data_fim == ""
    assert msg.eventos[0].valor == 8.1


def test_agregado_converte_json_sql_para_proto():
    msg = agregado({
        "codigo_condicao": "Diabetes",
        "total_pacientes": 10,
        "distribuicao_sexo": [{"chave": "female", "valor": 7, "percentual": 70}],
        "distribuicao_faixa_etaria": [],
        "distribuicao_setor": [],
        "frequencia_medicamentos": [],
        "estatisticas_exames": [{
            "nome": "HbA1c", "media": 8.1, "mediana": 8.0,
            "desvio_padrao": 0.5, "n": 10, "unidade": "%"
        }],
    })
    assert msg.codigo_condicao == "Diabetes"
    assert msg.total_pacientes == 10
    assert msg.distribuicao_sexo[0].chave == "female"
    assert msg.estatisticas_exames[0].nome == "HbA1c"


def test_lista_projetos():
    msg = lista_projetos([{
        "id_projeto": "PRJ01",
        "titulo": "Coorte",
        "username": "pes.mendes",
        "codigo_condicao": "Diabetes",
        "status": "Aprovado",
        "data_validade": "2027-12-31",
    }])
    assert msg.projetos[0].username == "pes.mendes"


def test_numero_extrai_valor_de_texto_institucional():
    assert numero("182 mg/dL") == 182.0
    assert numero("8,1") == 8.1
    assert numero(None) == 0.0
    assert numero("sem valor") == 0.0
