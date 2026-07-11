"""Acesso SQL usado pelo Patient Data Service."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from metricas import medir_query, observar_linhas


@dataclass
class DadosClinicos:
    pacientes: list[dict]
    atendimentos: list[dict]
    eventos: list[dict]


class RepositorioData:
    def __init__(self, conninfo: str, min_size: int = 1, max_size: int = 8):
        self.pool = ConnectionPool(conninfo, min_size=min_size, max_size=max_size, open=True)

    def fechar(self) -> None:
        self.pool.close()

    def _fetchall(self, tipo: str, sql: str, params: tuple) -> list[dict]:
        with medir_query(tipo), self.pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                linhas = list(cur.fetchall())
                observar_linhas(tipo, len(linhas))
                return linhas

    def buscar_pacientes(
        self,
        ids_pacientes: list[str],
        *,
        incluir_atendimentos: bool,
        incluir_eventos: bool,
        tipo_evento: str = "",
        limite_eventos: int = 0,
    ) -> DadosClinicos:
        if not ids_pacientes:
            return DadosClinicos([], [], [])

        pacientes = self._fetchall(
            "pacientes_por_id",
            """
            SELECT patient_id AS id_paciente,
                   full_name AS nome,
                   birth_date::text AS data_nascimento,
                   gender AS genero,
                   city AS cidade,
                   state AS estado,
                   cpf,
                   cns
            FROM patients
            WHERE patient_id = ANY(%s)
            ORDER BY patient_id
            """,
            (ids_pacientes,),
        )

        atendimentos: list[dict] = []
        if incluir_atendimentos:
            atendimentos = self._fetchall(
                "atendimentos_por_paciente",
                """
                SELECT encounter_id AS id_atendimento,
                       patient_id AS id_paciente,
                       start_date::text AS data_inicio,
                       end_date::text AS data_fim,
                       encounter_type AS tipo_atendimento,
                       department AS setor
                FROM encounters
                WHERE patient_id = ANY(%s)
                ORDER BY patient_id, start_date DESC, encounter_id
                """,
                (ids_pacientes,),
            )

        eventos: list[dict] = []
        if incluir_eventos:
            eventos = self._fetchall(
                "eventos_por_paciente",
                """
                WITH filtrados AS (
                    SELECT event_id AS id_evento,
                           patient_id AS id_paciente,
                           encounter_id AS id_atendimento,
                           CASE event_type
                               WHEN 'CONDITION' THEN 'Condicao'
                               WHEN 'OBSERVATION' THEN 'Observacao'
                               WHEN 'MEDICATION' THEN 'Medicacao'
                               ELSE event_type
                           END AS tipo_evento,
                           code AS codigo_tipo_evento,
                           description AS descricao,
                           event_date::text AS data_evento,
                           value AS valor,
                           unit AS unidade,
                           row_number() OVER (
                               PARTITION BY patient_id
                               ORDER BY event_date DESC, event_id DESC
                           ) AS rn
                    FROM clinical_events
                    WHERE patient_id = ANY(%s)
                      AND (
                          %s = ''
                          OR event_type = %s
                          OR event_type = CASE %s
                              WHEN 'Condicao' THEN 'CONDITION'
                              WHEN 'Observacao' THEN 'OBSERVATION'
                              WHEN 'Medicacao' THEN 'MEDICATION'
                              ELSE %s
                          END
                      )
                )
                SELECT id_evento, id_paciente, id_atendimento,
                       tipo_evento, codigo_tipo_evento, descricao,
                       data_evento, valor, unidade
                FROM filtrados
                WHERE %s = 0 OR rn <= %s
                ORDER BY id_paciente, data_evento DESC, id_evento DESC
                """,
                (
                    ids_pacientes,
                    tipo_evento,
                    tipo_evento,
                    tipo_evento,
                    tipo_evento,
                    limite_eventos,
                    limite_eventos,
                ),
            )

        return DadosClinicos(pacientes, atendimentos, eventos)

    def ids_coorte(self, codigo_condicao: str, limite_pacientes: int = 0) -> list[str]:
        limite_sql = "LIMIT %s" if limite_pacientes > 0 else ""
        params: tuple = (codigo_condicao, limite_pacientes) if limite_pacientes > 0 else (codigo_condicao,)
        linhas = self._fetchall(
            "ids_coorte",
            f"""
            SELECT DISTINCT patient_id AS id_paciente
            FROM clinical_events
            WHERE event_type = 'CONDITION'
              AND upper(code) = upper(%s)
            ORDER BY patient_id
            {limite_sql}
            """,
            params,
        )
        return [linha["id_paciente"] for linha in linhas]

    def buscar_coorte(self, codigo_condicao: str, limite_pacientes: int = 0) -> DadosClinicos:
        ids = self.ids_coorte(codigo_condicao, limite_pacientes)
        return self.buscar_pacientes(
            ids,
            incluir_atendimentos=True,
            incluir_eventos=True,
            tipo_evento="OBSERVATION",
            limite_eventos=0,
        )

    def agregar_coorte(self, codigo_condicao: str) -> dict:
        sql = """
        WITH coorte AS MATERIALIZED (
            SELECT DISTINCT patient_id
            FROM clinical_events
            WHERE event_type = 'CONDITION'
              AND upper(code) = upper(%(codigo)s)
        ),
        total AS (
            SELECT count(*)::bigint AS total_pacientes FROM coorte
        ),
        sexo AS (
            SELECT p.gender AS chave, count(*)::bigint AS valor
            FROM coorte c JOIN patients p USING (patient_id)
            GROUP BY p.gender
        ),
        faixa AS (
            SELECT CASE
                     WHEN age(current_date, p.birth_date) < interval '40 years' THEN '18-39'
                     WHEN age(current_date, p.birth_date) < interval '60 years' THEN '40-59'
                     WHEN age(current_date, p.birth_date) < interval '80 years' THEN '60-79'
                     ELSE '80+'
                   END AS chave,
                   count(*)::bigint AS valor
            FROM coorte c JOIN patients p USING (patient_id)
            GROUP BY chave
        ),
        setor AS (
            SELECT e.department AS chave, count(*)::bigint AS valor
            FROM coorte c JOIN encounters e USING (patient_id)
            GROUP BY e.department
        ),
        meds AS (
            SELECT ce.code AS chave, count(*)::bigint AS valor
            FROM coorte c JOIN clinical_events ce USING (patient_id)
            WHERE ce.event_type = 'MEDICATION'
            GROUP BY ce.code
        ),
        exames AS (
            SELECT ce.code AS nome,
                   avg(val.valor)::float8 AS media,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY val.valor)::float8 AS mediana,
                   stddev_samp(val.valor)::float8 AS desvio_padrao,
                   count(*)::bigint AS n,
                   max(ce.unit) AS unidade
            FROM coorte c
            JOIN clinical_events ce USING (patient_id)
            CROSS JOIN LATERAL (
                SELECT nullif(substring(ce.value from '[-+]?[0-9]+[.,]?[0-9]*'), '')::text AS bruto
            ) bruto
            CROSS JOIN LATERAL (
                SELECT replace(bruto.bruto, ',', '.')::double precision AS valor
                WHERE bruto.bruto IS NOT NULL
            ) val
            WHERE ce.event_type = 'OBSERVATION'
            GROUP BY ce.code
        )
        SELECT
            (SELECT total_pacientes FROM total) AS total_pacientes,
            coalesce((SELECT jsonb_agg(jsonb_build_object(
                'chave', chave, 'valor', valor,
                'percentual', round((100.0 * valor / nullif((SELECT total_pacientes FROM total), 0))::numeric, 2)
            ) ORDER BY chave) FROM sexo), '[]'::jsonb) AS distribuicao_sexo,
            coalesce((SELECT jsonb_agg(jsonb_build_object(
                'chave', chave, 'valor', valor,
                'percentual', round((100.0 * valor / nullif((SELECT total_pacientes FROM total), 0))::numeric, 2)
            ) ORDER BY chave) FROM faixa), '[]'::jsonb) AS distribuicao_faixa_etaria,
            coalesce((SELECT jsonb_agg(jsonb_build_object(
                'chave', chave, 'valor', valor,
                'percentual', round((100.0 * valor / nullif((SELECT sum(valor) FROM setor), 0))::numeric, 2)
            ) ORDER BY valor DESC, chave) FROM setor), '[]'::jsonb) AS distribuicao_setor,
            coalesce((SELECT jsonb_agg(jsonb_build_object(
                'chave', chave, 'valor', valor,
                'percentual', round((100.0 * valor / nullif((SELECT sum(valor) FROM meds), 0))::numeric, 2)
            ) ORDER BY valor DESC, chave) FROM meds), '[]'::jsonb) AS frequencia_medicamentos,
            coalesce((SELECT jsonb_agg(jsonb_build_object(
                'nome', nome,
                'media', coalesce(media, 0),
                'mediana', coalesce(mediana, 0),
                'desvio_padrao', coalesce(desvio_padrao, 0),
                'n', n,
                'unidade', coalesce(unidade, '')
            ) ORDER BY nome) FROM exames), '[]'::jsonb) AS estatisticas_exames
        """
        linhas = self._fetchall("agregar_coorte", sql, {"codigo": codigo_condicao})
        resultado = linhas[0] if linhas else {}
        resultado["codigo_condicao"] = codigo_condicao
        return resultado

    def listar_projetos(self, username: str) -> list[dict]:
        return self._fetchall(
            "listar_projetos",
            """
            SELECT project_id AS id_projeto,
                   title AS titulo,
                   researcher_username AS username,
                   target_condition_code AS codigo_condicao,
                   status,
                   valid_until::text AS data_validade
            FROM projects
            WHERE researcher_username = %s
            ORDER BY project_id
            """,
            (username,),
        )
