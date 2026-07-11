"""Acesso SQL usado pelo Authorization Service."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg_pool import ConnectionPool

from metricas import medir_query


@dataclass(frozen=True)
class Projeto:
    id_projeto: str
    username_pesquisador: str
    codigo_condicao_clinica: str
    status: str
    vigente: bool


class RepositorioAuth:
    def __init__(self, conninfo: str, min_size: int = 1, max_size: int = 4):
        self.pool = ConnectionPool(conninfo, min_size=min_size, max_size=max_size, open=True)

    def fechar(self) -> None:
        self.pool.close()

    def pacientes_vinculados(
        self,
        *,
        username: str,
        ids_pacientes: list[str],
        tipo_vinculo: str,
        exigir_supervisor: bool = False,
    ) -> list[str]:
        if not ids_pacientes:
            return []

        filtro_supervisor = "AND supervisor_username IS NOT NULL" if exigir_supervisor else ""
        sql = f"""
            SELECT patient_id
            FROM user_patient_assignments
            WHERE username = %s
              AND assignment_type = %s
              AND active IS TRUE
              AND patient_id = ANY(%s)
              {filtro_supervisor}
            ORDER BY patient_id
        """
        with medir_query("pacientes_vinculados"), self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (username, tipo_vinculo, ids_pacientes))
                return [linha[0] for linha in cur.fetchall()]

    def projeto(self, id_projeto: str) -> Projeto | None:
        sql = """
            SELECT project_id,
                   researcher_username,
                   target_condition_code,
                   status,
                   valid_until >= CURRENT_DATE AS vigente
            FROM projects
            WHERE project_id = %s
        """
        with medir_query("projeto"), self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (id_projeto,))
                linha = cur.fetchone()
                if linha is None:
                    return None
                return Projeto(*linha)
