import auth_pb2
import comum_pb2
from repositorio import Projeto
from server import Servico


class RepoFake:
    def pacientes_vinculados(self, *, username, ids_pacientes, tipo_vinculo, exigir_supervisor=False):
        autorizados = {
            ("med.cardoso", "ATTENDING", False): {"P000002"},
            ("est.ferreira", "TRAINEE", True): {"P000002"},
        }.get((username, tipo_vinculo, exigir_supervisor), set())
        return [p for p in ids_pacientes if p in autorizados]

    def projeto(self, id_projeto):
        projetos = {
            "PRJ01": Projeto("PRJ01", "pes.mendes", "DIABETES", "APPROVED", True),
            "PRJ02": Projeto("PRJ02", "pes.mendes", "HYPERTENSION", "EXPIRED", False),
            "PRJ03": Projeto("PRJ03", "pes.mendes", "OBESITY", "SUSPENDED", True),
            "PRJ04": Projeto("PRJ04", "pes.araujo", "PNEUMONIA", "APPROVED", True),
        }
        return projetos.get(id_projeto)


def req(**kwargs):
    return auth_pb2.RequisicaoAutorizacao(**kwargs)


class TestAuthService:
    def setup_method(self):
        self.svc = Servico(RepoFake())

    def test_medico_vinculado_recebe_full(self):
        resp = self.svc.AutorizarConsulta(req(
            username="med.cardoso", role="MEDICO", escopo="ResumoClinico",
            ids_pacientes=["P000002"]), None)
        assert resp.permitido
        assert resp.nivel == comum_pb2.FULL
        assert list(resp.ids_autorizados) == ["P000002"]

    def test_medico_sem_vinculo_nega(self):
        resp = self.svc.AutorizarConsulta(req(
            username="med.cardoso", role="MEDICO", escopo="ResumoClinico",
            ids_pacientes=["P049000"]), None)
        assert not resp.permitido
        assert resp.nivel == comum_pb2.DENY
        assert resp.motivo_negacao == "sem_vinculo_ativo"

    def test_estagiario_supervisionado_recebe_partial(self):
        resp = self.svc.AutorizarConsulta(req(
            username="est.ferreira", role="ESTAGIARIO", escopo="ResumoClinico",
            ids_pacientes=["P000002"]), None)
        assert resp.permitido
        assert resp.nivel == comum_pb2.PARTIAL

    def test_pesquisador_projeto_aprovado_aggregated(self):
        resp = self.svc.AutorizarConsulta(req(
            username="pes.mendes", role="PESQUISADOR", escopo="EstatisticasCoorte",
            id_projeto="PRJ01", codigo_condicao="DIABETES"), None)
        assert resp.permitido
        assert resp.nivel == comum_pb2.AGGREGATED

    def test_pesquisador_exames_coorte_anonymized(self):
        resp = self.svc.AutorizarConsulta(req(
            username="pes.mendes", role="PESQUISADOR", escopo="ExamesCoorte",
            id_projeto="PRJ01", codigo_condicao="diabetes"), None)
        assert resp.permitido
        assert resp.nivel == comum_pb2.ANONYMIZED

    def test_pesquisador_projeto_expirado(self):
        resp = self.svc.AutorizarConsulta(req(
            username="pes.mendes", role="PESQUISADOR", escopo="EstatisticasCoorte",
            id_projeto="PRJ02", codigo_condicao="HYPERTENSION"), None)
        assert not resp.permitido
        assert resp.motivo_negacao == "projeto_expirado"

    def test_pesquisador_projeto_nao_aprovado(self):
        resp = self.svc.AutorizarConsulta(req(
            username="pes.mendes", role="PESQUISADOR", escopo="EstatisticasCoorte",
            id_projeto="PRJ03", codigo_condicao="OBESITY"), None)
        assert not resp.permitido
        assert resp.motivo_negacao == "projeto_nao_aprovado"

    def test_pesquisador_projeto_de_outro_pesquisador(self):
        resp = self.svc.AutorizarConsulta(req(
            username="pes.mendes", role="PESQUISADOR", escopo="EstatisticasCoorte",
            id_projeto="PRJ04", codigo_condicao="PNEUMONIA"), None)
        assert not resp.permitido
        assert resp.motivo_negacao == "projeto_de_outro_pesquisador"

    def test_pesquisador_condicao_fora_do_projeto(self):
        resp = self.svc.AutorizarConsulta(req(
            username="pes.mendes", role="PESQUISADOR", escopo="EstatisticasCoorte",
            id_projeto="PRJ01", codigo_condicao="ASTHMA"), None)
        assert not resp.permitido
        assert resp.motivo_negacao == "condicao_fora_do_projeto"
