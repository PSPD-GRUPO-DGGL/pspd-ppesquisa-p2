\echo '== tabelas =='
\dt

\echo '== schemas esperados =='
\d patients
\d encounters
\d clinical_events
\d user_patient_assignments
\d projects

\echo '== cardinalidades =='
select 'patients' as tabela, count(*) from patients
union all select 'encounters', count(*) from encounters
union all select 'clinical_events', count(*) from clinical_events
union all select 'user_patient_assignments', count(*) from user_patient_assignments
union all select 'projects', count(*) from projects
order by tabela;

\echo '== amostras patients =='
select * from patients order by patient_id limit 5;

\echo '== amostras assignments =='
select * from user_patient_assignments order by assignment_id limit 20;

\echo '== amostras projects =='
select * from projects order by project_id limit 20;

\echo '== usuarios por perfil no banco =='
select assignment_type, username, count(*) as vinculos
from user_patient_assignments
group by assignment_type, username
order by assignment_type, username;

\echo '== projetos por pesquisador =='
select researcher_username, status, target_condition_code, count(*) as projetos
from projects
group by researcher_username, status, target_condition_code
order by researcher_username, status, target_condition_code;

\echo '== sugestoes de casos MEDICO/ESTAGIARIO =='
select assignment_type, username, patient_id, supervisor_username, active
from user_patient_assignments
where active is true
order by assignment_type, username, patient_id
limit 30;

\echo '== sugestoes de projetos =='
select project_id, researcher_username, target_condition_code, status, valid_until
from projects
order by researcher_username, project_id;

\echo '== indices =='
select schemaname, tablename, indexname, indexdef
from pg_indexes
where tablename in ('patients', 'encounters', 'clinical_events', 'user_patient_assignments', 'projects')
order by tablename, indexname;
