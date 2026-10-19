"""Perguntas REAIS que apareceram nas candidaturas, com a resposta que você aprovou.
Rodar: python -m unittest jobhunter.tests.test_answers"""
import unittest

from jobhunter import answers
from jobhunter.answers import Question as Q

CFG = answers.load(answers.EXEMPLO)
SN, SNU = ["Sim", "Não"], ["SIM", "NÃO"]


def r(texto, opcoes=(), kind="efetivo", empresa="Funcional Health Tech"):
    return answers.resolve(Q(texto, list(opcoes)), kind, CFG, None, empresa)


class TestFuncional(unittest.TestCase):
    def test_respostas_seguras(self):
        self.assertEqual(r("Você tem algum familiar atualmente empregado pela Funcional?", SN).value, "Não")
        self.assertEqual(r("Conhece alguém que trabalhe conosco?", SN).value, "Não")
        self.assertEqual(r("Já trabalhou na Funcional Health Tech?", SN).value, "Não")
        self.assertEqual(r("Você participa ou conhece alguém, de qualquer negócio que concorra com o segmento da Funcional?", SN).value, "Não")
        self.assertEqual(r("Último Salario", []).value, "2500")
        self.assertEqual(r("Você possui formação completa ou cursando na área da Saúde?", SN).value, "Sim")

    def test_salario_abaixo_da_pretensao_vira_pendencia(self):
        x = r("Pretensão Salarial até 1760,00 + Benefícios?", SN)
        self.assertEqual(x.kind, "pending")
        self.assertIn("1760", x.reason)

    def test_horario_especifico_vira_pendencia(self):
        x = r("Você tem disponibilidade para trabalhar de 13:40h as 20:00h - 6:20hs/dia - (segunda a sexta)", SNU)
        self.assertEqual(x.kind, "pending")


class TestAlper(unittest.TestCase):
    def test_documentos_nunca_automaticos(self):
        for t in ("RG", "Nome completo da Mãe?", "Nome completo do Pai?", "CPF", "Data de nascimento", "Qual a sua raça/cor?"):
            self.assertEqual(r(t).kind, "sensitive", t)

    def test_outras(self):
        self.assertEqual(r("Você já trabalhou na Alper?", SN, empresa="Alper Carreiras").value, "Não")
        self.assertEqual(r("Possui familiares/parentes em concorrentes diretos?", SN).value, "Não")
        self.assertEqual(r("Possui familiares/parentes trabalhando na Alper?", SN).value, "Não")
        self.assertEqual(r("Qual é o seu salário atual?").value, "2500")

    def test_faixa_pretensao(self):
        x = r("Qual é a sua pretensão salarial?", ["R$ 2.500,00 - R$ 3.000,00", "Acima de R$ 3.000,00"])
        self.assertEqual(x.value, "R$ 2.500,00 - R$ 3.000,00")


class TestConsorcioZenviaOutras(unittest.TestCase):
    def test_consorcio(self):
        self.assertEqual(r("Tem experiência no segmento de consórcio?", SN).value, "Não")
        self.assertEqual(r("Qual seu nível de experiência com Excel?", ["Básico", "Intermediário", "Avançado", "Especialista"]).value, "Intermediário")
        self.assertEqual(r("Tem disponibilidade para trabalhar ao sábados conforme escala?", SN).value, "Sim")
        self.assertEqual(r("Tem disponibilidade para participar de reuniões presenciais conforme necessidade?", SN).value, "Sim")

    def test_zenvia(self):
        self.assertEqual(r("Qual sua expectativa salarial? (use somente números)").value, "3000")
        self.assertEqual(r("Você é ex-colaborador da Zenvia (ou empresa adquirida)?", SN).value, "Não")
        self.assertEqual(r("Você é colaborador da Zenvia?", SN).value, "Não")
        self.assertEqual(r("Você reside no Brasil ou no México?", ["Brasil", "México", "Não, resido em outro país."]).value, "Brasil")

    def test_habilidade_tecnica_vira_pendencia(self):
        x = r("Você possui conhecimento em lógica de programação e noções básicas de JavaScript e JSON?", SN)
        self.assertEqual(x.kind, "pending")  # nível de habilidade nunca é chutado

    def test_tecnospeed_viva(self):
        self.assertEqual(r("Pretensão Salarial", kind="estagio").value, "1600")
        self.assertEqual(r("Qual horário da sua faculdade?").value.split(",")[0], "Faculdade EAD (ensino a distância)")
        self.assertEqual(r("Tem conhecimento com NFse?").kind, "pending")
        faixas = ["Até R$ 1.800", "De R$ 1.801 a R$ 2.500", "De R$ 2.501 a R$ 3.500", "De R$ 3.501 a R$ 4.500", "Acima de R$ 4.501"]
        self.assertEqual(r("Pretensão Salarial:", faixas, kind="estagio").value, "Até R$ 1.800")
        self.assertEqual(r("Pretensão Salarial:", faixas, kind="efetivo").value, "De R$ 2.501 a R$ 3.500")


class TestAttus(unittest.TestCase):
    """Perguntas REAIS do formulário da Attus (dry-run ao vivo em 18/10/2026)."""

    def test_remuneracao_nao_e_dado_sensivel(self):
        # "remuneRAÇAo" contém "raca": antes isto era classificado como raça/cor
        x = r("Qual foi ou é atualmente sua remuneração?", [], empresa="Attus Procuradoria Digital")
        self.assertEqual((x.kind, x.value), ("answer", "2500"))

    def test_salario_desejado_nunca_vira_salario_atual(self):
        for t in ("Qual é o salário que você deseja?", "Qual salário você pretende receber?", "Qual é o salário desejado?"):
            self.assertNotEqual(r(t).value, "2500", t)

    def test_beneficios_e_viagem_ficam_pendentes(self):
        self.assertEqual(r("Em valores, quais foram ou são atualmente seus benefícios ?", []).kind, "pending")
        self.assertEqual(r("Você possui disponibilidade para viajar?", SN).kind, "pending")

    def test_pretensao_com_faixas_da_attus(self):
        faixas = ["R$ 3.000 - R$ 5.000", "R$ 5.001 - R$ 7.000", "R$ 7.001 - R$ 9.000", "Acima de R$9.001"]
        self.assertEqual(r("Qual sua pretensão salarial com base no desafio visto ?", faixas).value, "R$ 3.000 - R$ 5.000")

    def test_sensivel_usa_limite_de_palavra(self):
        for t in ("Você tem experiência com recepção de clientes?", "Já trabalhou em agência de publicidade?",
                  "Qual a sua percepção do mercado?", "Você é generoso com a equipe?"):
            self.assertNotEqual(r(t, SN).kind, "sensitive", t)
        for t in ("Qual o seu CEP?", "Qual a sua cor ou raça?", "Informe seu gênero", "Qual sua identidade de gênero?"):
            self.assertEqual(r(t).kind, "sensitive", t)


class TestSeguranca(unittest.TestCase):
    def test_pergunta_aberta_desconhecida(self):
        self.assertEqual(r("Por que você quer trabalhar aqui?").kind, "pending")

    def test_opcao_inexistente_vira_pendencia(self):
        x = r("Qual seu nível de experiência com Excel?", ["Nenhum", "Pouco"])
        self.assertEqual(x.kind, "pending")

    def test_resolve_all_so_completo_se_tudo_resolvido(self):
        qs = [Q("Já trabalhou na Acme?", SN), Q("RG", [])]
        res, ok = answers.resolve_all(qs, "efetivo", CFG, None, "Acme")
        self.assertFalse(ok)
        self.assertEqual([x.kind for x in res], ["answer", "sensitive"])

    def test_regras_gerais_nao_geram_respostas_erradas(self):
        # estes casos respondiam errado antes de amarrar as regras ao nome da empresa
        for t in ("Você trabalha na área de saúde?", "Você já atuou na área de TI?", "Você tem familiaridade com Jira?",
                  "Você está cursando medicina?"):
            self.assertEqual(r(t, SN).kind, "pending", t)

    def test_empresa_com_nome_diferente_na_pergunta(self):
        self.assertEqual(r("Você trabalha na Alper?", SN, empresa="Alper Carreiras").value, "Não")
        self.assertEqual(r("Você é colaborador da Zenvia?", SN, empresa="Zenvia Jobs").value, "Não")
        # nome genérico não vira coringa
        self.assertEqual(r("Você trabalha no grupo de risco?", SN, empresa="Grupo Alfa").kind, "pending")

    def test_sem_falso_positivo_estado_em_outra_frase(self):
        # "estado" dentro de outra palavra/contexto não deve virar "Pernambuco" em pergunta de salário
        self.assertEqual(r("Qual o estado civil?").kind, "sensitive")
        self.assertEqual(r("Em que estado você mora?").value, "Pernambuco")
        self.assertEqual(r("Em que cidade você reside?").value, "Recife")
        self.assertEqual(r("Qual a sua cidade natal?").kind, "pending")


if __name__ == "__main__":
    unittest.main()
