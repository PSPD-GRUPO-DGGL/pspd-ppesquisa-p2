"""Conversão de linhas SQL para mensagens protobuf."""

from __future__ import annotations

import re

import comum_pb2
import data_pb2


def numero(valor) -> float:
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    encontrado = re.search(r"[-+]?\d+(?:[,.]\d+)?", str(valor))
    if not encontrado:
        return 0.0
    return float(encontrado.group(0).replace(",", "."))


def paciente(linha: dict) -> comum_pb2.Paciente:
    return comum_pb2.Paciente(
        id_paciente=linha["id_paciente"],
        nome=linha["nome"],
        data_nascimento=linha["data_nascimento"],
        genero=linha["genero"],
        cidade=linha["cidade"],
        estado=linha["estado"],
        cpf=linha["cpf"],
        cns=linha["cns"],
    )


def atendimento(linha: dict) -> comum_pb2.Atendimento:
    return comum_pb2.Atendimento(
        id_atendimento=linha["id_atendimento"],
        id_paciente=linha["id_paciente"],
        data_inicio=linha["data_inicio"] or "",
        data_fim=linha["data_fim"] or "",
        tipo_atendimento=linha["tipo_atendimento"],
        setor=linha["setor"],
    )


def evento(linha: dict) -> comum_pb2.EventoClinico:
    return comum_pb2.EventoClinico(
        id_evento=str(linha["id_evento"]),
        id_paciente=linha["id_paciente"],
        id_atendimento=linha["id_atendimento"] or "",
        tipo_evento=linha["tipo_evento"],
        codigo_tipo_evento=linha["codigo_tipo_evento"],
        descricao=linha["descricao"] or "",
        data_evento=linha["data_evento"],
        valor=numero(linha["valor"]),
        unidade=linha["unidade"] or "",
    )


def conjunto(dados) -> comum_pb2.ConjuntoDadosClinicos:
    return comum_pb2.ConjuntoDadosClinicos(
        pacientes=[paciente(p) for p in dados.pacientes],
        atendimentos=[atendimento(a) for a in dados.atendimentos],
        eventos=[evento(e) for e in dados.eventos],
    )


def contagem(linha: dict) -> comum_pb2.Contagem:
    return comum_pb2.Contagem(
        chave=linha["chave"],
        valor=int(linha["valor"]),
        percentual=float(linha["percentual"]),
    )


def estatistica(linha: dict) -> comum_pb2.Estatistica:
    return comum_pb2.Estatistica(
        nome=linha["nome"],
        media=float(linha["media"]),
        mediana=float(linha["mediana"]),
        desvio_padrao=float(linha["desvio_padrao"]),
        n=int(linha["n"]),
        unidade=linha["unidade"] or "",
    )


def agregado(dados: dict) -> comum_pb2.ResultadoAgregado:
    return comum_pb2.ResultadoAgregado(
        codigo_condicao=dados["codigo_condicao"],
        total_pacientes=int(dados["total_pacientes"] or 0),
        distribuicao_sexo=[contagem(c) for c in dados["distribuicao_sexo"]],
        distribuicao_faixa_etaria=[
            contagem(c) for c in dados["distribuicao_faixa_etaria"]
        ],
        distribuicao_setor=[contagem(c) for c in dados["distribuicao_setor"]],
        frequencia_medicamentos=[
            contagem(c) for c in dados["frequencia_medicamentos"]
        ],
        estatisticas_exames=[estatistica(e) for e in dados["estatisticas_exames"]],
    )


def projeto(linha: dict) -> comum_pb2.Projeto:
    return comum_pb2.Projeto(
        id_projeto=linha["id_projeto"],
        titulo=linha["titulo"],
        username=linha["username"],
        codigo_condicao=linha["codigo_condicao"],
        status=linha["status"],
        data_validade=linha["data_validade"],
    )


def lista_projetos(linhas: list[dict]) -> data_pb2.ListaProjetos:
    return data_pb2.ListaProjetos(projetos=[projeto(p) for p in linhas])
