"""Projeção de dados clínicos por nível de acesso. Ver docs/matriz-acesso.md §2."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import date

# Espelha comum.proto:NivelAcesso, para não depender dos stubs gerados.
NIVEL_INDEFINIDO = 0
FULL = 1
PARTIAL = 2
ANONYMIZED = 3
AGGREGATED = 4
DENY = 5

NOMES_NIVEL = {
    FULL: "FULL",
    PARTIAL: "PARTIAL",
    ANONYMIZED: "ANONYMIZED",
    AGGREGATED: "AGGREGATED",
    DENY: "DENY",
}

_PARTICULAS = {"da", "de", "do", "das", "dos", "e"}

_FAIXAS = ((18, 39), (40, 59), (60, 79))


class SaltAusente(RuntimeError):
    pass


def _salt() -> bytes:
    salt = os.environ.get("ANON_SALT")
    if not salt:
        # Sem default: o espaço de id_paciente é pequeno e conhecido, então um
        # salt embutido no código torna o pseudônimo reversível por força bruta.
        raise SaltAusente(
            "ANON_SALT não definido. Pseudonimização sem salt secreto é reversível."
        )
    return salt.encode("utf-8")


def pseudonimo(id_paciente: str) -> str:
    """Estável dentro de uma resposta, para que as referências do Bundle resolvam."""
    digest = hmac.new(_salt(), id_paciente.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hash{digest[:6]}"


def iniciais(nome_completo: str) -> str:
    partes = [p for p in nome_completo.split() if p.lower() not in _PARTICULAS]
    return "".join(f"{p[0].upper()}." for p in partes if p)


def idade(data_nascimento: str, hoje: date | None = None) -> int:
    hoje = hoje or date.today()
    nasc = date.fromisoformat(data_nascimento)
    anterior = (hoje.month, hoje.day) < (nasc.month, nasc.day)
    return hoje.year - nasc.year - (1 if anterior else 0)


def faixa_etaria(data_nascimento: str, hoje: date | None = None) -> str:
    anos = idade(data_nascimento, hoje)
    for inicio, fim in _FAIXAS:
        if inicio <= anos <= fim:
            return f"{inicio}-{fim}"
    return "80+" if anos >= 80 else "0-17"


def projetar_paciente(paciente: dict, nivel: int, hoje: date | None = None) -> dict:
    """Monta um dicionário novo com os campos permitidos.

    Nunca copiar e apagar: um campo acrescentado ao schema passaria a vazar
    silenciosamente.
    """
    if nivel == FULL:
        return {
            "id": paciente["id_paciente"],
            "nome": paciente["nome"],
            "data_nascimento": paciente["data_nascimento"],
            "genero": paciente["genero"],
            "cidade": paciente["cidade"],
            "estado": paciente["estado"],
            "cpf": paciente["cpf"],
            "cns": paciente["cns"],
        }

    if nivel == PARTIAL:
        return {
            "id": paciente["id_paciente"],
            "nome": iniciais(paciente["nome"]),
            "data_nascimento": paciente["data_nascimento"][:4],
            "genero": paciente["genero"],
            "cidade": paciente["cidade"],
            "estado": paciente["estado"],
        }

    if nivel == ANONYMIZED:
        return {
            "id": pseudonimo(paciente["id_paciente"]),
            "genero": paciente["genero"],
            "estado": paciente["estado"],
            "faixa_etaria": faixa_etaria(paciente["data_nascimento"], hoje),
        }

    if nivel == AGGREGATED:
        raise ValueError("AGGREGATED não projeta pacientes individuais")

    raise ValueError(f"nível não projetável: {nivel}")


def mapa_de_ids(pacientes: list[dict], nivel: int) -> dict[str, str]:
    """id real -> id exibido, para reescrever as referências do Bundle.

    Sem isso, Encounter.subject e Observation.subject vazam o id que o Patient
    acabou de esconder.
    """
    if nivel == ANONYMIZED:
        return {p["id_paciente"]: pseudonimo(p["id_paciente"]) for p in pacientes}
    return {p["id_paciente"]: p["id_paciente"] for p in pacientes}
