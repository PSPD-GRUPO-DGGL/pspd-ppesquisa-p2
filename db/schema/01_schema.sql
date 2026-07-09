-- Pseudo-prontuário eletrônico. Índices ficam em 03_indices.sql, aplicados
-- após a carga.

DROP TABLE IF EXISTS clinical_events CASCADE;
DROP TABLE IF EXISTS encounters CASCADE;
DROP TABLE IF EXISTS user_patient_assignments CASCADE;
DROP TABLE IF EXISTS projects CASCADE;
DROP TABLE IF EXISTS patients CASCADE;

CREATE TABLE patients (
    id_paciente     TEXT PRIMARY KEY,
    nome            TEXT     NOT NULL,
    data_nascimento DATE     NOT NULL,
    genero          TEXT     NOT NULL,
    cidade          TEXT     NOT NULL,
    estado          CHAR(2)  NOT NULL,
    cpf             CHAR(11) NOT NULL,
    cns             CHAR(15) NOT NULL
);

CREATE TABLE encounters (
    id_atendimento   TEXT PRIMARY KEY,
    id_paciente      TEXT NOT NULL REFERENCES patients(id_paciente),
    data_inicio      TIMESTAMP NOT NULL,
    data_fim         TIMESTAMP,
    tipo_atendimento TEXT NOT NULL,
    setor            TEXT NOT NULL
);

-- tipo_evento discrimina o Resource FHIR de saída (Condicao|Observacao|Medicacao).
-- valor e unidade só são preenchidos para Observacao e Medicacao.
CREATE TABLE clinical_events (
    id_evento          BIGSERIAL PRIMARY KEY,
    id_paciente        TEXT NOT NULL REFERENCES patients(id_paciente),
    id_atendimento     TEXT REFERENCES encounters(id_atendimento),
    tipo_evento        TEXT NOT NULL,
    codigo_tipo_evento TEXT NOT NULL,
    descricao          TEXT,
    data_evento        DATE NOT NULL,
    valor              DOUBLE PRECISION,
    unidade            TEXT
);

-- username_supervisor só é preenchido quando tipo_vinculo = 'estagiario'.
CREATE TABLE user_patient_assignments (
    id_vinculo          BIGSERIAL PRIMARY KEY,
    username_cuidador   TEXT NOT NULL,
    id_paciente         TEXT NOT NULL REFERENCES patients(id_paciente),
    tipo_vinculo        TEXT NOT NULL,
    username_supervisor TEXT,
    status              TEXT NOT NULL
);

CREATE TABLE projects (
    id_projeto              TEXT PRIMARY KEY,
    titulo                  TEXT NOT NULL,
    username_pesquisador    TEXT NOT NULL,
    codigo_condicao_clinica TEXT NOT NULL,
    status                  TEXT NOT NULL,
    data_validade           DATE NOT NULL
);
