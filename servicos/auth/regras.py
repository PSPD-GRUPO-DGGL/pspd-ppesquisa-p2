"""Regras de autorização normativas do projeto."""

from __future__ import annotations

import comum_pb2

NOMES_NIVEL = {
    comum_pb2.NIVEL_INDEFINIDO: "NIVEL_INDEFINIDO",
    comum_pb2.FULL: "FULL",
    comum_pb2.PARTIAL: "PARTIAL",
    comum_pb2.ANONYMIZED: "ANONYMIZED",
    comum_pb2.AGGREGATED: "AGGREGATED",
    comum_pb2.DENY: "DENY",
}

ESCOPOS_PACIENTE = {
    "ListaPacientes",
    "ResumoClinico",
    "HistoricoClinico",
    "Exames",
    "Medicamentos",
}

ESCOPOS_AGREGADOS = {"EstatisticasCoorte", "ResumoCoorte"}
ESCOPOS_ANONIMIZADOS = {"ExamesCoorte"}


def normalizar_role(role: str) -> str:
    return role.strip().upper()


def nivel_para_escopo_pesquisador(escopo: str) -> int | None:
    if escopo in ESCOPOS_AGREGADOS:
        return comum_pb2.AGGREGATED
    if escopo in ESCOPOS_ANONIMIZADOS:
        return comum_pb2.ANONYMIZED
    if escopo == "MeusProjetos":
        return comum_pb2.NIVEL_INDEFINIDO
    return None
