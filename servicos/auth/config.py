"""Configuração do Authorization Service."""

from __future__ import annotations

import os


def conninfo() -> str:
    """Monta a string de conexão a partir de variáveis de ambiente.

    Em Kubernetes, esses valores devem vir de Secret/ConfigMap. Não há senha
    padrão propositalmente.
    """

    host = os.environ.get("DB_HOST")
    dbname = os.environ.get("DB_NAME")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    port = os.environ.get("DB_PORT", "5432")

    faltando = [
        nome
        for nome, valor in (
            ("DB_HOST", host),
            ("DB_NAME", dbname),
            ("DB_USER", user),
            ("DB_PASSWORD", password),
        )
        if not valor
    ]
    if faltando:
        raise RuntimeError("variáveis obrigatórias ausentes: " + ", ".join(faltando))

    return f"host={host} port={port} dbname={dbname} user={user} password={password}"
