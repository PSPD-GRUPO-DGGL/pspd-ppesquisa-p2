-- Aplicar somente após a carga do seed.
--
-- Não criar índice que cubra (tipo_evento='Observacao', codigo_tipo_evento, valor).
-- A varredura das observações é o custo que o cenário AGGREGATED mede; cobri-la
-- com índice eliminaria o contraste entre os caminhos leve e pesado.

CREATE INDEX idx_upa_cuidador     ON user_patient_assignments (username_cuidador, status);
CREATE INDEX idx_upa_supervisor   ON user_patient_assignments (username_supervisor, status);
CREATE INDEX idx_upa_paciente     ON user_patient_assignments (id_paciente);

CREATE INDEX idx_projects_pesq    ON projects (username_pesquisador, status);

CREATE INDEX idx_enc_paciente     ON encounters (id_paciente);
CREATE INDEX idx_ce_paciente_data ON clinical_events (id_paciente, data_evento DESC);
CREATE INDEX idx_ce_paciente_tipo ON clinical_events (id_paciente, tipo_evento);

-- Resolução de coorte. Parcial: condições são ~10% da tabela.
CREATE INDEX idx_ce_coorte ON clinical_events (codigo_tipo_evento)
    WHERE tipo_evento = 'Condicao';

ANALYZE patients;
ANALYZE encounters;
ANALYZE clinical_events;
ANALYZE user_patient_assignments;
ANALYZE projects;
