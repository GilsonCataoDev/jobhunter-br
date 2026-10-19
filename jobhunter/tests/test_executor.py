"""Executor com um Gupy FALSO que reproduz as telas reais. Rodar: python -m unittest jobhunter.tests.test_executor"""
import csv
import os
import tempfile
import unittest

import yaml

from jobhunter import answers, db
from jobhunter.executor import flow, run_apply

CFG = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config.yml"), encoding="utf-8"))
ACFG = answers.load(answers.EXEMPLO)

SN = ["Sim", "Não"]
Q_OK = [{"key": "r:q1", "kind": "radio", "locked": False, "text": "Você já trabalhou na Acme?", "options": SN},
        {"key": "t:sal", "kind": "text", "locked": False, "text": "Qual é o seu salário atual?", "options": []},
        {"key": "c:p", "kind": "checkbox", "locked": False, "text": "Qual é a sua pretensão salarial?",
         "options": ["R$ 2.500,00 - R$ 3.000,00", "Acima de R$ 3.000,00"]}]


def tela(texto, botoes=(), campos=()):
    return {"texto": texto, "botoes": list(botoes), "campos": [dict(c) for c in campos]}


def telas_felizes(campos=Q_OK):
    return [tela("Olá Maria, vamos continuar sua candidatura?", ["Continuar"]),
            tela("Dados adicionais Alguém indicou você? Você trabalha na empresa?", ["Salvar e continuar"]),
            tela("Perguntas criadas pela empresa Atenção: as respostas não poderão ser editadas depois. Responder agora", ["Responder agora"]),
            tela("Perguntas criadas pela empresa Acme 1. ...", ["Salvar e continuar"], campos),
            tela("Apresente-se! Personalizar candidatura Finalizar candidatura", ["Finalizar candidatura"]),
            tela("Candidatura finalizada! Fique de olho no seu e-mail")]


class FakeDriver:
    def __init__(self, telas, captcha=False, nao_preenche=(), login=False):
        self.telas, self.i, self.captcha, self.nao_preenche, self.login = telas, 0, captcha, set(nao_preenche), login
        self.cliques, self.preenchidos, self.prints, self.urls, self.adicional_no = [], [], [], [], 0

    def goto(self, url): self.urls.append(url)
    def wait_idle(self, ms=0): pass
    def page_text(self): return self.telas[self.i]["texto"]
    def has_captcha(self): return self.captcha
    def precisa_login(self): return self.login
    def screenshot(self, path):
        self.prints.append(path)
        if os.path.isdir(os.path.dirname(path)):
            with open(path, "wb") as f:
                f.write(b"png")
    def set_additional_no(self): self.adicional_no += 1
    def read_questions(self): return self.telas[self.i]["campos"]

    def click_button(self, rotulo):
        if rotulo not in self.telas[self.i]["botoes"]:
            return False
        self.cliques.append(rotulo)
        if self.i < len(self.telas) - 1:
            self.i += 1
        return True

    def fill(self, key, kind, value):
        if key in self.nao_preenche:
            return False
        self.preenchidos.append((key, value))
        return True


def vaga(jid="gupy:12345", company="Acme", status="approved", tier=1):
    return {"id": jid, "source": "gupy", "title": "Analista de Suporte Jr", "company": company,
            "url": f"https://acme.gupy.io/job/xyz{jid[-3:]}", "description": "x", "workplace": "remote", "kind": "efetivo",
            "published": "2026-10-15T00:00:00Z", "deadline": "2026-12-01T00:00:00Z"}, status, tier


def banco(*vagas):
    con = db.connect(":memory:")
    for d, st, tier in vagas:
        db.insert(con, d, st, "", "", tier)
    con.commit()
    return con


def job(con, jid="gupy:12345"):
    return db.get_job(con, jid)


class TestFluxo(unittest.TestCase):
    def test_apply_url(self):
        self.assertEqual(flow.apply_url({"url": "https://carreirasomie.gupy.io/job/abc", "id": "gupy:12621758"}),
                         "https://carreirasomie.gupy.io/candidates/jobs/12621758/apply")
        with self.assertRaises(ValueError):
            flow.apply_url({"url": "lixo", "id": "gupy:1"})

    def test_caminho_feliz_envia(self):
        con = banco(vaga())
        d = FakeDriver(telas_felizes())
        o = flow.run_application(d, con, job(con), dry_run=False, cfg=ACFG)
        self.assertEqual(o.status, "sent", o.detail)
        self.assertEqual(d.cliques, ["Continuar", "Salvar e continuar", "Responder agora", "Salvar e continuar", "Finalizar candidatura"])
        self.assertEqual(d.preenchidos, [("r:q1", "Não"), ("t:sal", "2500"), ("c:p", "R$ 2.500,00 - R$ 3.000,00")])
        self.assertEqual(d.adicional_no, 1)
        self.assertTrue(d.urls[0].endswith("/candidates/jobs/12345/apply"))

    def test_dry_run_preenche_mas_nao_salva_respostas(self):
        con = banco(vaga())
        d = FakeDriver(telas_felizes())
        o = flow.run_application(d, con, job(con), dry_run=True, cfg=ACFG)
        self.assertEqual(o.status, "dry_run_ready")
        self.assertEqual(len(d.preenchidos), 3)
        # as respostas da Gupy são irreversíveis: o dry-run NUNCA clica no "Salvar e continuar" do formulário nem em Finalizar
        self.assertEqual(d.cliques, ["Continuar", "Salvar e continuar", "Responder agora"])

    def test_pergunta_desconhecida_para_sem_preencher_e_cria_pendencia(self):
        campos = Q_OK + [{"key": "t:x", "kind": "text", "locked": False, "text": "Por que quer trabalhar aqui?", "options": []}]
        con = banco(vaga())
        d = FakeDriver(telas_felizes(campos))
        o = flow.run_application(d, con, job(con), dry_run=False, cfg=ACFG)
        self.assertEqual(o.status, "pending")
        self.assertEqual(d.preenchidos, [])                       # nada preenchido
        self.assertNotIn("Finalizar candidatura", d.cliques)
        self.assertEqual(len(db.open_pending(con, "gupy:12345")), 1)

    def test_documento_para_e_nao_e_gravado(self):
        campos = [{"key": "t:rg", "kind": "text", "locked": False, "text": "RG", "options": []}]
        con = banco(vaga())
        o = flow.run_application(FakeDriver(telas_felizes(campos)), con, job(con), dry_run=False, cfg=ACFG)
        self.assertEqual(o.status, "pending")
        self.assertIn("sensitive", o.detail)
        self.assertTrue(db.open_pending(con)[0]["reason"].startswith("SENSÍVEL"))

    def test_campos_bloqueados_viram_already_applied(self):
        bloqueados = [dict(c, locked=True) for c in Q_OK]
        con = banco(vaga())
        d = FakeDriver(telas_felizes(bloqueados))
        o = flow.run_application(d, con, job(con), dry_run=False, cfg=ACFG)
        self.assertEqual(o.status, "already_applied")
        self.assertEqual(d.preenchidos, [])

    def test_captcha_para_e_tira_print(self):
        con = banco(vaga())
        pasta = tempfile.mkdtemp()
        shot = os.path.join(pasta, "c.png")
        d = FakeDriver(telas_felizes(), captcha=True)
        o = flow.run_application(d, con, job(con), dry_run=False, cfg=ACFG, shot=shot)
        self.assertEqual(o.status, "needs_human")
        self.assertIn("CAPTCHA", o.detail)
        self.assertEqual(d.cliques, [])
        self.assertEqual(d.prints, [shot])

    def test_tela_desconhecida_para(self):
        con = banco(vaga())
        d = FakeDriver([tela("Complete seu cadastro: envie o RG e comprovante de endereço", ["Enviar documentos"])])
        o = flow.run_application(d, con, job(con), dry_run=False, cfg=ACFG)
        self.assertEqual(o.status, "needs_human")
        self.assertEqual(d.cliques, [])

    def test_nao_consegue_preencher_para(self):
        con = banco(vaga())
        d = FakeDriver(telas_felizes(), nao_preenche={"t:sal"})
        o = flow.run_application(d, con, job(con), dry_run=False, cfg=ACFG)
        self.assertEqual(o.status, "needs_human")
        self.assertNotIn("Finalizar candidatura", d.cliques)

    def test_botao_ausente_vira_erro_sem_levantar(self):
        con = banco(vaga())
        d = FakeDriver([tela("Olá Maria, vamos continuar sua candidatura?", [])])
        o = flow.run_application(d, con, job(con), dry_run=False, cfg=ACFG)
        self.assertEqual(o.status, "error")

    def test_tela_que_nao_avanca_nao_gira_para_sempre(self):
        class Preso(FakeDriver):
            def click_button(self, rotulo):
                return True  # clica, mas a tela nunca muda
        con = banco(vaga())
        o = flow.run_application(Preso([tela("Olá Maria, vamos continuar sua candidatura?", ["Continuar"])]), con, job(con), cfg=ACFG)
        self.assertEqual(o.status, "needs_human")
        self.assertIn(str(flow.MAX_PASSOS), o.detail)

    def test_url_invalida_vira_erro(self):
        con = banco(vaga())
        row = dict(job(con), url="nada")
        self.assertEqual(flow.run_application(FakeDriver(telas_felizes()), con, row, cfg=ACFG).status, "error")


class TestRevisaoFase3(unittest.TestCase):
    def test_sessao_expirada_para_com_mensagem_clara(self):
        con = banco(vaga())
        d = FakeDriver(telas_felizes(), login=True)
        o = flow.run_application(d, con, job(con), dry_run=False, cfg=ACFG)
        self.assertEqual(o.status, "needs_human")
        self.assertIn("LOGIN", o.detail)
        self.assertEqual(d.cliques, [])

    def test_runner_para_o_lote_inteiro_quando_a_sessao_expira(self):
        con = banco(vaga("gupy:111"), vaga("gupy:222"), vaga("gupy:333"))
        with tempfile.TemporaryDirectory() as tmp:
            r = run_apply.run(con, FakeDriver(telas_felizes(), login=True), CFG, dry_run=False,
                              sleep=lambda s: None, log_path=os.path.join(tmp, "l.csv"), shots=tmp)
        self.assertEqual(r["tentadas"], 1)           # não insiste nas outras
        self.assertIn("--login", r["parou"])
        self.assertEqual(db.get_job(con, "gupy:111")["status"], "approved")   # nada enviado: volta para a fila

    def test_formulario_que_reaparece_para(self):
        # após "Salvar e continuar" a Gupy devolve o MESMO formulário (validação): não pode salvar de novo em loop
        voltando = [tela("Olá Maria, vamos continuar sua candidatura?", ["Continuar"]),
                    tela("Dados adicionais", ["Salvar e continuar"]),
                    tela("Perguntas criadas pela empresa Responder agora", ["Responder agora"]),
                    tela("Perguntas criadas pela empresa Acme", ["Salvar e continuar"], Q_OK)]
        class Volta(FakeDriver):
            def click_button(self, rotulo):
                super().click_button(rotulo)
                if rotulo == "Salvar e continuar" and self.i == 3:
                    self.i = 3   # continua no formulário
                return True
        con = banco(vaga())
        d = Volta(voltando)
        o = flow.run_application(d, con, job(con), dry_run=False, cfg=ACFG)
        self.assertEqual(o.status, "needs_human")
        self.assertIn("reapareceu", o.detail)
        self.assertEqual(d.cliques.count("Salvar e continuar"), 2)   # um do "Dados adicionais" + UM do formulário (não 15)


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "log.csv")
        self.pausas = []

    def ler_log(self):
        with open(self.log, encoding="utf-8", newline="") as f:
            return list(csv.reader(f))

    def rodar(self, con, driver, **kw):
        kw.setdefault("dry_run", False)
        return run_apply.run(con, driver, CFG, sleep=self.pausas.append, log_path=self.log, shots=self.tmp, **kw)

    def test_envia_so_aprovadas_sem_pendencia_e_registra(self):
        con = banco(vaga("gupy:111"), vaga("gupy:222"), vaga("gupy:333", status="shortlisted"))
        from jobhunter.answers import Question as Q
        from jobhunter import approval
        approval.prepare_questions(con, job(con, "gupy:222"), [Q("Por que aqui?", [])], ACFG)  # 222 tem pendência
        class Multi(FakeDriver):
            def goto(self, url):
                super().goto(url); self.i = 0
        d = Multi(telas_felizes())
        r = self.rodar(con, d)
        self.assertEqual((r["tentadas"], r["sent"]), (1, 1))
        self.assertEqual(db.get_job(con, "gupy:111")["status"], "sent")
        self.assertEqual(db.get_job(con, "gupy:222")["status"], "approved")
        self.assertEqual(db.get_job(con, "gupy:333")["status"], "shortlisted")
        linhas = self.ler_log()
        self.assertEqual(linhas[0][1:], ["Acme", "Analista de Suporte Jr", "gupy", "enviada"])
        self.assertEqual(db.sent_today(con), 1)

    def test_dry_run_nao_marca_como_enviada_nem_conta_no_limite(self):
        con = banco(vaga("gupy:111"))
        r = self.rodar(con, FakeDriver(telas_felizes()), dry_run=True)
        self.assertEqual(r["dry_run_ready"], 1)
        self.assertEqual(db.get_job(con, "gupy:111")["status"], "approved")
        self.assertEqual(db.sent_today(con), 0)
        self.assertFalse(os.path.exists(self.log))

    def test_limite_diario(self):
        con = banco(*[vaga(f"gupy:{i}00") for i in range(1, 4)])
        for i in range(CFG["executor"]["limite_diario"]):
            db.log_attempt(con, f"gupy:old{i}", "sent", dry_run=False)
        r = self.rodar(con, FakeDriver(telas_felizes()))
        self.assertEqual(r["tentadas"], 0)
        self.assertEqual(r["parou"], "limite diário atingido")

    def test_para_no_captcha(self):
        con = banco(vaga("gupy:111"), vaga("gupy:222"))
        r = self.rodar(con, FakeDriver(telas_felizes(), captcha=True))
        self.assertEqual(r["tentadas"], 1)
        self.assertIn("CAPTCHA", r["parou"])

    def test_para_apos_falhas_seguidas(self):
        con = banco(*[vaga(f"gupy:{i}00") for i in range(1, 6)])
        r = self.rodar(con, FakeDriver([tela("tela estranha", [])]))
        self.assertEqual(r["tentadas"], CFG["executor"]["falhas_seguidas_max"])
        self.assertIn("falhas seguidas", r["parou"])

    def test_ja_aplicada_marca_status_e_log(self):
        con = banco(vaga("gupy:111"))
        r = self.rodar(con, FakeDriver(telas_felizes([dict(c, locked=True) for c in Q_OK])))
        self.assertEqual(r["already_applied"], 1)
        self.assertEqual(db.get_job(con, "gupy:111")["status"], "applied_before")
        self.assertEqual(self.ler_log()[0][4], "ja_enviada")

    def test_trava_anti_duplicidade(self):
        con = banco(vaga("gupy:111"), vaga("gupy:222"))
        # uma execução anterior caiu no meio de 111: ela fica 'sending' e NADA é reenviado automaticamente
        db.set_status(con, "gupy:111", "sending")
        d = FakeDriver(telas_felizes())
        r = self.rodar(con, d)
        self.assertEqual(r["tentadas"], 0)
        self.assertEqual(r["travadas"], ["gupy:111"])
        self.assertIn("interrompida", r["parou"])
        self.assertEqual(d.urls, [])

    def test_falha_devolve_a_vaga_para_a_fila_e_envio_nao(self):
        con = banco(vaga("gupy:111"))
        self.rodar(con, FakeDriver([tela("tela estranha", [])]))
        self.assertEqual(db.get_job(con, "gupy:111")["status"], "approved")   # não ficou presa em 'sending'

    def test_vaga_fica_sending_durante_a_tentativa(self):
        con = banco(vaga("gupy:111"))
        vistos = []
        class Espia(FakeDriver):
            def goto(self_, url):
                vistos.append(db.get_job(con, "gupy:111")["status"]); super().goto(url)
        self.rodar(con, Espia(telas_felizes()))
        self.assertEqual(vistos, ["sending"])

    def test_pausa_humana_entre_vagas_mas_nao_depois_da_ultima(self):
        con = banco(vaga("gupy:111"), vaga("gupy:222"))
        class Multi(FakeDriver):
            def goto(self, url):
                super().goto(url); self.i = 0
        self.rodar(con, Multi(telas_felizes()))
        self.assertEqual(len(self.pausas), 1)
        self.assertTrue(CFG["executor"]["pausa_min_s"] <= self.pausas[0] <= CFG["executor"]["pausa_max_s"])


if __name__ == "__main__":
    unittest.main()
