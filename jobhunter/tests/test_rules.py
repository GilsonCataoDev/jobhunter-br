"""Casos reais (resumidos) de vagas que lemos nesta sessão. Rodar: python -m unittest jobhunter.tests.test_rules"""
import os
import unittest
from datetime import datetime, timezone

import yaml

from jobhunter import db, rules
from jobhunter.collectors import gupy
from jobhunter.run import norm_company, process

CFG = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config.yml"), encoding="utf-8"))
HOJE = datetime(2026, 10, 18, tzinfo=timezone.utc)


def vaga(title, desc, kind="efetivo", published="2026-10-10T00:00:00Z", deadline="2026-12-01T00:00:00Z", company="X"):
    return {"id": f"gupy:{abs(hash(title)) % 10**8}", "source": "gupy", "title": title, "company": company,
            "url": "https://x.gupy.io/job/1", "description": desc, "workplace": "remote", "kind": kind,
            "published": published, "deadline": deadline}


def ev(j):
    return rules.evaluate(j, CFG, HOJE)


class TestRegras(unittest.TestCase):
    def test_stefanini_suporte_n1_passa(self):
        d = ev(vaga("ANALISTA SUPORTE JR N1", "Ensino superior incompleto ou em andamento em Sistemas de Informação. "
                    "Atender e registrar solicitações de usuários. Solucionar chamados por telefone e acesso remoto."))
        self.assertTrue(d.ok, d.reason)
        self.assertEqual(d.tier, 1)

    def test_softexpert_espanhol_fluente_rejeita(self):
        d = ev(vaga("Técnico(a) de Suporte", "Espanhol fluente, com boa capacidade de conversação.\n"
                    "Experiência profissional anterior em suporte técnico."))
        self.assertFalse(d.ok)
        self.assertEqual(d.reason, "espanhol")

    def test_ingles_como_diferencial_nao_rejeita(self):
        d = ev(vaga("Analista de Suporte Jr", "Você irá se diferenciar se tiver: Inglês avançado. Conhecimento básico em HTML."))
        self.assertTrue(d.ok, d.reason)

    def test_zenvia_ingles_nao_obrigatorio_passa(self):
        d = ev(vaga("Desenvolvedor(a) Operações Júnior (remoto)", "Noções básicas de Javascript e JSON.\n"
                    "Bacana se você tiver, mas não é obrigatório: Inglês Intermediário."))
        self.assertTrue(d.ok, d.reason)

    def test_mtp_experiencia_comprovada_rejeita(self):
        d = ev(vaga("Analista QA Júnior", "Experiência comprovada como Analista de QA ou função similar em projetos de grande porte."))
        self.assertFalse(d.ok)
        self.assertIn("experiência", d.reason)

    def test_desejavel_experiencia_nao_rejeita(self):
        d = ev(vaga("Analista de Atendimento Júnior", "Formação: Superior na área de saúde: cursando ou concluído.\n"
                    "Desejável experiência mínima de 6 meses em programa de Suporte ao paciente."))
        self.assertTrue(d.ok, d.reason)

    def test_l8_formacao_e_anos_rejeita(self):
        d = ev(vaga("Analista Administrativo de Projetos", "Ensino Superior completo ou em fase final de conclusão em "
                    "Administração de Empresas, Engenharia de Produção.\nExperiência prévia (1 a 3 anos) em rotinas administrativas."))
        self.assertFalse(d.ok)

    def test_consorcio_passa(self):
        d = ev(vaga("ASSISTENTE ADMINISTRATIVO - CONSÓRCIO", "Ensino Médio Completo;\nConhecimento intermediário em Excel e Pacote Office;\n"
                    "Familiaridade com sistemas de consórcio, como Newcon."))
        self.assertTrue(d.ok, d.reason)
        self.assertEqual(d.tier, 2)

    def test_credirural_presencial_disfarcado_rejeita(self):
        # título genérico já cai em "fora do foco"; com título dentro do foco, a regra de presencial pega
        self.assertFalse(ev(vaga("Assistente de Negócios e Operações - PA Indiara", "Atender cooperados, caixas eletrônicos.")).ok)
        d = ev(vaga("Auxiliar Administrativo - Agência", "Atender cooperados, auxiliando com caixas eletrônicos e mobile."))
        self.assertFalse(d.ok)
        self.assertIn("presencial", d.reason)

    def test_pj_e_senior_rejeitam(self):
        self.assertEqual(ev(vaga("Suporte e Dados", "x", kind="pj")).reason, "PJ")
        self.assertFalse(ev(vaga("Analista de Suporte Sênior", "x")).ok)

    def test_vaga_antiga_e_encerrada(self):
        self.assertIn("encerradas", ev(vaga("Suporte Jr", "x", deadline="2026-09-01T00:00:00Z")).reason)
        self.assertIn("há mais de", ev(vaga("Suporte Jr", "x", published="2026-06-01T00:00:00Z")).reason)

    def test_horario_fixo_vira_aviso(self):
        d = ev(vaga("Analista de Atendimento Júnior", "Disponibilidade das 13h40 às 20h00, segunda a sexta."))
        self.assertTrue(d.ok)
        self.assertIn("horário fixo", d.warnings)

    def test_salario_beneficio_nao_conta_como_salario(self):
        d = ev(vaga("Analista de Suporte Jr", "Vale-refeição de R$ 950,00. Plano de saúde."))
        self.assertTrue(d.ok, d.reason)

    def test_salario_baixo_efetivo_rejeita(self):
        self.assertFalse(ev(vaga("Analista de Suporte Jr", "Salário: R$ 1.500,00 por mês.")).ok)


class TestColetor(unittest.TestCase):
    def test_normalize_e_clean(self):
        raw = {"id": "12732048", "name": "12732048 - Analista QA Júnior", "careerPageName": "MTP", "jobUrl": "https://a/b?x=1",
               "description": "A&nbsp;MTP &amp; <b>teste</b>", "workplaceType": "remote", "type": "vacancy_type_effective",
               "publishedDate": "2026-10-15T18:06:35.298Z", "applicationDeadline": "2026-12-14T00:00:00.000Z"}
        j = gupy.normalize(raw)
        self.assertEqual(j["title"], "Analista QA Júnior")
        self.assertEqual(j["url"], "https://a/b")
        self.assertEqual(j["description"], "A MTP & teste")
        self.assertEqual(j["kind"], "efetivo")

    def test_parse_page_estrutura_mudou(self):
        with self.assertRaises(ValueError):
            gupy.parse_page("<html>sem dados</html>")


class TestPipeline(unittest.TestCase):
    def test_dedupe_empresa_e_ids(self):
        con = db.connect(":memory:")
        a = vaga("Suporte Jr N1", "Ensino superior em andamento.", company="Stefanini")
        b = vaga("Atendimento Jr", "Superior cursando.", company="Outra")
        s = process([a, b], con, CFG, applied={norm_company("Stefanini")})
        self.assertEqual(s["aprovadas"], 1)
        self.assertEqual(s["rejeitadas"], 1)
        for jid in (a["id"], b["id"]):
            db.set_status(con, jid, "notified")
        s2 = process([a, b], con, CFG, applied=set())
        self.assertEqual(s2["ja_vistas"], 2)  # já notificadas: não reprocessa nem reenvia
        self.assertEqual(s2["novas"], 0)


class TestErrosCorrigidos(unittest.TestCase):
    def test_anos_de_mercado_da_empresa_nao_e_experiencia(self):
        d = ev(vaga("Analista de Suporte Jr", "Somos uma empresa com mais de 20 anos de mercado. Ensino superior em andamento."))
        self.assertTrue(d.ok, d.reason)

    def test_anos_de_experiencia_colados_rejeitam(self):
        self.assertFalse(ev(vaga("Analista de Suporte Jr", "Requisito: experiência mínima de 2 anos em suporte.")).ok)
        self.assertFalse(ev(vaga("Analista de Suporte Jr", "Pelo menos 3 anos de experiência com helpdesk.")).ok)

    def test_frases_coladas_sem_espaco(self):
        # "Todas as nossas vagas são para todos.Requisitos..." não pode virar uma frase só
        d = ev(vaga("Suporte Jr", "Todas as vagas são para todos.Bacana se você tiver Jira. Ensino superior em andamento."))
        self.assertTrue(d.ok, d.reason)

    def test_assistente_generico_fora_do_foco(self):
        for t in ("Assistente de Planejamento", "Assistente de Mídia - Opusmúltipla", "Assistente de Processos Logísticos"):
            self.assertEqual(ev(vaga(t, "x")).reason, "fora do foco (título)", t)

    def test_dedupe_por_nome_parecido_e_subdominio(self):
        from jobhunter.run import ja_aplicada
        aplicadas = {norm_company("Zenvia"), norm_company("Stefanini"), norm_company("Quality Digital")}
        j1 = dict(vaga("x", "x", company="Zenvia Jobs"))
        j2 = dict(vaga("x", "x", company="ADMINISTRADOR DE REDES"), url="https://vagasstefanini.gupy.io/job/1")
        j3 = dict(vaga("x", "x", company="Outra Empresa"), url="https://outra.gupy.io/job/1")
        self.assertTrue(ja_aplicada(j1, aplicadas))
        self.assertTrue(ja_aplicada(j2, aplicadas))
        self.assertFalse(ja_aplicada(j3, aplicadas))

    def test_nome_curto_nao_gera_falso_positivo(self):
        from jobhunter.run import ja_aplicada
        self.assertFalse(ja_aplicada(vaga("x", "x", company="Banco XYZ"), {"xy"}))

    def test_reavalia_vaga_ja_vista_quando_regra_muda(self):
        con = db.connect(":memory:")
        a = vaga("Suporte Jr N1", "Ensino superior em andamento. Inglês avançado.", company="Acme")
        process([a], con, CFG, applied=set())
        self.assertEqual(con.execute("SELECT status FROM jobs").fetchone()[0], "rejected")
        a["description"] = "Ensino superior em andamento."  # descrição editada pela empresa
        s = process([a], con, CFG, applied=set())
        self.assertEqual(s["reavaliadas"], 1)
        self.assertEqual(con.execute("SELECT status FROM jobs").fetchone()[0], "shortlisted")


class TestRevisao(unittest.TestCase):
    """Erros achados na revisão antes da Fase 3."""

    def test_palavra_dentro_de_palavra_no_titulo(self):
        # (a palavra inteira "Lead" é ambígua — líder técnico ou lead de vendas — e continua sendo rejeitada por segurança)
        for t in ("Analista de Suporte - Leads", "Suporte Técnico Misleading", "Analista de Suporte SRE"):
            self.assertTrue(ev(vaga(t, "Ensino superior em andamento.")).ok, t)
        for t in ("Analista de Suporte Sr", "Analista de Suporte Lead", "Analista de Suporte PL", "Líder de Suporte"):
            self.assertFalse(ev(vaga(t, "x")).ok, t)

    def test_sigla_curta_em_faixa(self):
        self.assertEqual(rules.faixa("Estágio em Aquário", CFG), 1)         # 'estágio' conta, mas...
        self.assertIsNone(rules.faixa("Vendedor de Aquários", CFG))         # ...'qa' dentro de palavra não conta
        self.assertEqual(rules.faixa("Analista de TI", CFG), 1)
        self.assertIsNone(rules.faixa("Assistente de Planejamento", CFG))

    def test_jovem_aprendiz_rejeita(self):
        self.assertIn("aprendiz", ev(vaga("Jovem Aprendiz Suporte", "x", kind="aprendiz")).reason)

    def test_dedupe_nao_confunde_nomes_parecidos(self):
        from jobhunter.run import ja_aplicada
        log = {"Omie", "Gera Sales Ecosystem", "Quality Digital"}
        for emp in ("Gerais Mineração", "Homie", "Generali Seguros", "Quality Assurance Corp"):
            self.assertFalse(ja_aplicada(dict(vaga("x", "x", company=emp), url="https://z.gupy.io/job/1"), log), emp)
        self.assertTrue(ja_aplicada(dict(vaga("x", "x", company="Omie Brasil"), url="https://z.gupy.io/job/1"), log))
        self.assertTrue(ja_aplicada(dict(vaga("x", "x", company="Gera Sales Ecosystem"), url="https://z.gupy.io/job/1"), log))
        self.assertTrue(ja_aplicada(dict(vaga("x", "x", company="ADMINISTRADOR DE REDES"), url="https://vagasstefanini.gupy.io/job/1"), {"Stefanini"}))

    def test_anotacao_entre_parenteses_no_log_e_ignorada(self):
        from jobhunter.run import ja_aplicada
        log = {"Vagas Confidenciais (consórcio)", "Domo Inovação (Banco Mercantil)"}
        self.assertTrue(ja_aplicada(dict(vaga("x", "x", company="Vagas Confidenciais"), url="https://c.gupy.io/job/1"), log))
        self.assertTrue(ja_aplicada(dict(vaga("x", "x", company="Domo Inovação"), url="https://domo.gupy.io/job/1"), log))
        self.assertFalse(ja_aplicada(dict(vaga("x", "x", company="Banco Mercantil do Brasil"), url="https://m.gupy.io/job/1"), {"Domo Inovação (Banco Mercantil)"}))

    def test_decisao_humana_nao_e_sobrescrita_pela_reavaliacao(self):
        con = db.connect(":memory:")
        a = vaga("Suporte Jr N1", "Ensino superior em andamento.", company="Acme")
        process([a], con, CFG, applied=set())
        for status in ("offered", "approved", "skipped", "notified"):
            db.set_status(con, a["id"], status)
            s = process([a], con, CFG, applied=set())
            self.assertEqual(db.get_job(con, a["id"])["status"], status, status)
            self.assertEqual(s["ja_vistas"], 1)
            self.assertEqual(s["reavaliadas"], 0)

    def test_novas_aprovadas_so_lista_quem_entrou_agora(self):
        con = db.connect(":memory:")
        a = vaga("Suporte Jr N1", "Ensino superior em andamento.", company="Acme")
        s1 = process([a], con, CFG, applied=set())
        self.assertEqual(s1["novas_aprovadas"], [a["id"]])
        s2 = process([a], con, CFG, applied=set())              # continua shortlisted: não repete no resumo
        self.assertEqual(s2["novas_aprovadas"], [])
        a["description"] = "Inglês avançado."                    # rejeitada ...
        process([a], con, CFG, applied=set())
        a["description"] = "Ensino superior em andamento."       # ... e volta a passar: conta como nova
        s3 = process([a], con, CFG, applied=set())
        self.assertEqual(s3["novas_aprovadas"], [a["id"]])

    def test_retry_da_coleta(self):
        from unittest import mock
        import requests
        from jobhunter.collectors import gupy

        class R:
            def __init__(self, code, text=""):
                self.status_code, self.text = code, text

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(str(self.status_code))

        sessao = mock.Mock()
        sessao.get.side_effect = [R(429), R(503), R(200, "ok")]
        with mock.patch("jobhunter.collectors.gupy.time.sleep"):
            self.assertEqual(gupy._get(sessao, "u", {}).text, "ok")
        sessao.get.side_effect = [R(404)]
        with mock.patch("jobhunter.collectors.gupy.time.sleep"), self.assertRaises(requests.HTTPError):
            gupy._get(sessao, "u", {})   # 404 não é transitório: não insiste


if __name__ == "__main__":
    unittest.main()
