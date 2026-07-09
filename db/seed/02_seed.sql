-- Seed determinístico. Escala via :n_pacientes (padrão 50000).
--
-- Toda aleatoriedade deriva de hashtext() sobre a chave da linha, e não de
-- random(). Duas razões, ambas obrigatórias:
--   1. A expressão precisa referenciar a linha externa, senão o planner trata o
--      LATERAL como subconsulta não-correlacionada e avalia o argumento uma
--      única vez para a consulta inteira.
--   2. Reprodutibilidade entre cargas, exigida para comparar corridas de carga.
-- hashtext é estável dentro de uma major version; o projeto fixa postgres:16.

\if :{?n_pacientes}
\else
  \set n_pacientes 50000
\endif

INSERT INTO patients (id_paciente, nome, data_nascimento, genero, cidade, estado, cpf, cns)
SELECT
    pid,
    (ARRAY['Ana','Bruno','Carla','Daniel','Elisa','Fernando','Gabriela','Heitor',
           'Isabela','João','Karina','Lucas','Mariana','Nelson','Olivia','Paulo',
           'Queila','Rafael','Sofia','Tiago','Ursula','Vitor','Wanda','Yuri'])[1 + (abs(hashtext(pid || 'n1')) % 24)]
      || ' ' ||
    (ARRAY['Silva','Souza','Oliveira','Santos','Pereira','Costa','Rodrigues','Almeida',
           'Nascimento','Lima','Araujo','Fernandes','Carvalho','Gomes','Martins','Rocha'])[1 + (abs(hashtext(pid || 'n2')) % 16)]
      || ' ' ||
    (ARRAY['Cardoso','Barbosa','Ribeiro','Teixeira','Moraes','Pinto','Correia','Dias'])[1 + (abs(hashtext(pid || 'n3')) % 8)],
    (DATE '2008-01-01' - (abs(hashtext(pid || 'dob')) % 26280))::date,
    CASE WHEN (abs(hashtext(pid || 'g')) % 100) < 55 THEN 'female' ELSE 'male' END,
    (ARRAY['Brasília','Goiânia','Anápolis','Formosa','Luziânia','Valparaíso','Planaltina','Taguatinga'])[1 + (abs(hashtext(pid || 'c')) % 8)],
    (ARRAY['DF','GO','GO','GO','GO','GO','DF','DF'])[1 + (abs(hashtext(pid || 'c')) % 8)],
    lpad((abs(hashtext(pid || 'cpf')))::text, 11, '0'),
    lpad((abs(hashtext(pid || 'cns')))::text, 15, '0')
FROM (
    SELECT 'P' || lpad(i::text, 6, '0') AS pid
    FROM generate_series(1, :n_pacientes) AS i
) AS g;

INSERT INTO encounters (id_atendimento, id_paciente, data_inicio, data_fim, tipo_atendimento, setor)
SELECT
    'E' || lpad((row_number() OVER (ORDER BY p.id_paciente, enc.n))::text, 8, '0'),
    p.id_paciente,
    inicio,
    inicio + (interval '1 hour' * (1 + (abs(hashtext(p.id_paciente || 'dur' || enc.n)) % 72))),
    (ARRAY['Ambulatorial','Ambulatorial','Ambulatorial','Emergencia','Internacao','Retorno'])[1 + (abs(hashtext(p.id_paciente || 'tp' || enc.n)) % 6)],
    (ARRAY['Cardiologia','Endocrinologia','Pediatria','Clinica Geral','Nefrologia','Emergencia'])[1 + (abs(hashtext(p.id_paciente || 'st' || enc.n)) % 6)]
FROM patients p
CROSS JOIN LATERAL generate_series(1, 1 + (abs(hashtext(p.id_paciente || 'enc')) % 6)) AS enc(n)
CROSS JOIN LATERAL (
    SELECT TIMESTAMP '2021-01-01' + (interval '1 day' * (abs(hashtext(p.id_paciente || 'dt' || enc.n)) % 1800)) AS inicio
) AS d;

-- DISTINCT ON, e não JOIN LATERAL ... LIMIT 1: neste ponto ainda não existe
-- índice em encounters(id_paciente), e o LATERAL faria seq scan por paciente.
INSERT INTO clinical_events (id_paciente, id_atendimento, tipo_evento, codigo_tipo_evento, descricao, data_evento, valor, unidade)
WITH primeiro_atendimento AS MATERIALIZED (
    SELECT DISTINCT ON (id_paciente) id_paciente, id_atendimento, data_inicio
    FROM encounters
    ORDER BY id_paciente, data_inicio, id_atendimento
)
SELECT
    p.id_paciente,
    e.id_atendimento,
    'Condicao',
    cond.codigo,
    cond.descricao,
    e.data_inicio::date,
    NULL,
    NULL
FROM patients p
JOIN primeiro_atendimento e ON e.id_paciente = p.id_paciente
CROSS JOIN LATERAL (
    VALUES
      ('Diabetes',    'Diabetes Mellitus Tipo 2',  CASE WHEN p.genero = 'female' THEN 42 ELSE 18 END),
      ('Hipertensao', 'Hipertensão Arterial',      30),
      ('Obesidade',   'Obesidade Grau I',          20),
      ('Pneumonia',   'Pneumonia Adquirida',        8),
      ('Asma',        'Asma Brônquica',            10)
) AS cond(codigo, descricao, prob_pct)
WHERE (abs(hashtext(p.id_paciente || 'cond' || cond.codigo)) % 100) < cond.prob_pct;

-- Diabéticos recebem deslocamento em HbA1c e Glicemia, para que a agregação da
-- coorte difira da população geral.
-- MATERIALIZED evita que o planner reavalie a CTE por linha de observação.
WITH cat_obs(idx, codigo, descricao, base, amplitude, unidade) AS (
    VALUES
      (0, 'HbA1c',       'Hemoglobina Glicada',        4.5,   3.0, '%'),
      (1, 'Glicemia',    'Glicemia de Jejum',         70.0,  60.0, 'mg/dL'),
      (2, 'IMC',         'Índice de Massa Corporal',  18.0,  20.0, 'kg/m2'),
      (3, 'Creatinina',  'Creatinina Sérica',          0.6,   1.2, 'mg/dL'),
      (4, 'Colesterol',  'Colesterol Total',         130.0, 140.0, 'mg/dL'),
      (5, 'PressaoSist', 'Pressão Sistólica',        100.0,  80.0, 'mmHg')
),
diabeticos AS MATERIALIZED (
    SELECT DISTINCT id_paciente FROM clinical_events
    WHERE tipo_evento = 'Condicao' AND codigo_tipo_evento = 'Diabetes'
)
INSERT INTO clinical_events (id_paciente, id_atendimento, tipo_evento, codigo_tipo_evento, descricao, data_evento, valor, unidade)
SELECT
    e.id_paciente,
    e.id_atendimento,
    'Observacao',
    c.codigo,
    c.descricao,
    e.data_inicio::date,
    round((
        c.base
        + c.amplitude * ((abs(hashtext(e.id_atendimento || 'v' || n)) % 1000) / 1000.0)
        + CASE WHEN d.id_paciente IS NOT NULL AND c.codigo = 'HbA1c'    THEN 2.4
               WHEN d.id_paciente IS NOT NULL AND c.codigo = 'Glicemia' THEN 55.0
               ELSE 0.0 END
    )::numeric, 2),
    c.unidade
FROM encounters e
CROSS JOIN LATERAL generate_series(1, 3 + (abs(hashtext(e.id_atendimento || 'nobs')) % 6)) AS n
JOIN cat_obs c ON c.idx = (abs(hashtext(e.id_atendimento || 'o' || n)) % 6)
LEFT JOIN diabeticos d ON d.id_paciente = e.id_paciente;

WITH cat_med(idx, codigo, descricao, dose) AS (
    VALUES
      (0, 'Metformina',   'Metformina 850 mg',   850.0),
      (1, 'Losartana',    'Losartana 50 mg',      50.0),
      (2, 'Insulina',     'Insulina NPH 10 UI',   10.0),
      (3, 'Enalapril',    'Enalapril 20 mg',      20.0),
      (4, 'Sinvastatina', 'Sinvastatina 40 mg',   40.0)
)
INSERT INTO clinical_events (id_paciente, id_atendimento, tipo_evento, codigo_tipo_evento, descricao, data_evento, valor, unidade)
SELECT
    e.id_paciente,
    e.id_atendimento,
    'Medicacao',
    c.codigo,
    c.descricao,
    e.data_inicio::date,
    c.dose,
    'mg'
FROM encounters e
CROSS JOIN LATERAL generate_series(1, (abs(hashtext(e.id_atendimento || 'nmed')) % 4)) AS n
JOIN cat_med c ON c.idx = (abs(hashtext(e.id_atendimento || 'm' || n)) % 5);

-- Limites derivados de count(*) para funcionar em qualquer escala. O último
-- paciente fica sem vínculo ativo, reservado para o caso Inativo abaixo.
INSERT INTO user_patient_assignments (username_cuidador, id_paciente, tipo_vinculo, username_supervisor, status)
SELECT
    CASE WHEN i % 2 = 0 THEN 'med.cardoso' ELSE 'med.silva' END,
    'P' || lpad(i::text, 6, '0'),
    'medico',
    NULL,
    'Ativo'
FROM generate_series(1, (SELECT LEAST(2000, count(*) - 1) FROM patients)) AS i;

INSERT INTO user_patient_assignments (username_cuidador, id_paciente, tipo_vinculo, username_supervisor, status)
SELECT
    CASE WHEN i % 2 = 0 THEN 'est.pereira' ELSE 'est.lima' END,
    'P' || lpad(i::text, 6, '0'),
    'estagiario',
    CASE WHEN i % 2 = 0 THEN 'med.cardoso' ELSE 'med.silva' END,
    'Ativo'
FROM generate_series(1, (SELECT LEAST(800, count(*) - 1) FROM patients)) AS i;

-- Caso Inativo: exercita o filtro por status no AuthService.
INSERT INTO user_patient_assignments (username_cuidador, id_paciente, tipo_vinculo, username_supervisor, status)
SELECT 'med.cardoso', id_paciente, 'medico', NULL, 'Inativo'
FROM patients ORDER BY id_paciente DESC LIMIT 1;

-- Cobre os quatro desfechos do AuthService: aprovado e vigente, expirado,
-- suspenso, e aprovado porém de outro pesquisador.
INSERT INTO projects (id_projeto, titulo, username_pesquisador, codigo_condicao_clinica, status, data_validade) VALUES
  ('PRJ01', 'Coorte de Diabetes Tipo 2 no DF',      'pes.souza',   'Diabetes',    'Aprovado', DATE '2027-12-31'),
  ('PRJ02', 'Hipertensão e adesão medicamentosa',   'pes.souza',   'Hipertensao', 'Expirado', DATE '2024-06-30'),
  ('PRJ03', 'Obesidade infantil e comorbidades',    'pes.souza',   'Obesidade',   'Suspenso', DATE '2027-01-31'),
  ('PRJ04', 'Pneumonia adquirida na comunidade',    'pes.almeida', 'Pneumonia',   'Aprovado', DATE '2027-06-30');
