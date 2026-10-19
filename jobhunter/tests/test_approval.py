"""Fila de aprovação, pendências e bot (Telegram falso). Rodar: python -m unittest jobhunter.tests.test_approval"""
import unittest

from jobhunter import answers, approval, db
from jobhunter.answers import Question as Q
from jobhunter.bot import Bot

SN = ["Sim", "Não"]
CFG = answers.load(answers.EXEMPLO)
CHAT = "42"


def job(jid="gupy:1", status="shortlisted", kind="efetivo", tier=1):
    return {"id": jid, "source": "gupy", "title": "Analista de Suporte Jr", "company": "Acme", "url": f"https://acme.gupy.io/{jid}",
            "description": "x", "workplace": "remote", "kind": kind, "published": "2026-10-10T00:00:00Z",
            "deadline": "2026-12-01T00:00:00Z"}, status, tier


def novo_banco(*vagas):
    con = db.connect(":memory:")
    for j in vagas:
        d, status, tier = j
        db.insert(con, d, status, "", "", tier)
    con.commit()
    return con


class FakeAPI:
    def __init__(self):
        self.sent = []

    def call(self, method, **p):
        self.sent.append((method, p))
        return {"ok": True, "result": []}

    def texts(self):
        return [p["text"] for m, p in self.sent if m == "sendMessage"]


class TestPendencias(unittest.TestCase):
    def test_prepare_cria_pendencias_e_marca_sensivel(self):
        con = novo_banco(job())
        j = db.get_job(con, "gupy:1")
        qs = [Q("Já trabalhou na Acme?", SN), Q("RG", []), Q("Por que quer trabalhar aqui?", [])]
        res, completo = approval.prepare_questions(con, j, qs, CFG)
        self.assertFalse(completo)
        abertas = db.open_pending(con)
        self.assertEqual(len(abertas), 2)
        self.assertTrue(any(r["reason"].startswith(approval.SENSIVEL) for r in abertas))

    def test_pendencia_idempotente(self):
        con = novo_banco(job())
        j = db.get_job(con, "gupy:1")
        for _ in range(3):
            approval.prepare_questions(con, j, [Q("Por que quer trabalhar aqui?", [])], CFG)
        self.assertEqual(len(db.open_pending(con)), 1)

    def test_resposta_do_usuario_e_reaproveitada(self):
        con = novo_banco(job("gupy:1"), job("gupy:2"))
        q = Q("Tem conhecimento em Zendesk?", SN)
        approval.prepare_questions(con, db.get_job(con, "gupy:1"), [q], CFG)
        pid = db.open_pending(con)[0]["id"]
        self.assertIn("Anotado", approval.on_answer(con, pid, "sim"))
        res, completo = approval.prepare_questions(con, db.get_job(con, "gupy:2"), [q], CFG)  # mesma pergunta, outra vaga
        self.assertTrue(completo)
        self.assertEqual(res[0].value, "Sim")  # voltou com a grafia da opção

    def test_resposta_fora_das_opcoes_e_recusada(self):
        con = novo_banco(job())
        approval.prepare_questions(con, db.get_job(con, "gupy:1"), [Q("Conhece Zendesk?", SN)], CFG)
        pid = db.open_pending(con)[0]["id"]
        self.assertIn("uma destas", approval.on_answer(con, pid, "talvez"))
        self.assertEqual(len(db.open_pending(con)), 1)

    def test_dado_sensivel_nunca_e_gravado(self):
        con = novo_banco(job())
        approval.prepare_questions(con, db.get_job(con, "gupy:1"), [Q("RG", [])], CFG)
        pid = db.open_pending(con)[0]["id"]
        self.assertIn("Dado sensível", approval.on_answer(con, pid, "1234567"))
        row = con.execute("SELECT answer FROM pending_questions WHERE id=?", (pid,)).fetchone()
        self.assertIsNone(row["answer"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM learned_answers").fetchone()[0], 0)
        self.assertIn("feita", approval.on_done(con, pid))
        self.assertEqual(len(db.open_pending(con)), 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM learned_answers").fetchone()[0], 0)


class TestCallbacks(unittest.TestCase):
    def test_aprovar_e_pular(self):
        con = novo_banco(job("gupy:1", "offered"), job("gupy:2", "offered"))
        self.assertIn("Aprovada", approval.on_callback(con, "a:gupy:1"))
        self.assertIn("Pulada", approval.on_callback(con, "s:gupy:2"))
        self.assertEqual(db.get_job(con, "gupy:1")["status"], "approved")
        self.assertEqual(db.get_job(con, "gupy:2")["status"], "skipped")

    def test_callback_invalido(self):
        con = novo_banco(job())
        self.assertEqual(approval.on_callback(con, "lixo"), "Ação inválida.")
        self.assertEqual(approval.on_callback(con, "a:gupy:999"), "Vaga não encontrada.")
        self.assertEqual(approval.on_callback(con, "x:gupy:1"), "Ação inválida.")

    def test_aprovada_avisa_das_pendencias(self):
        con = novo_banco(job())
        approval.prepare_questions(con, db.get_job(con, "gupy:1"), [Q("Por quê?", [])], CFG)
        self.assertIn("pendente", approval.on_callback(con, "a:gupy:1"))


class TestBot(unittest.TestCase):
    def setUp(self):
        self.con = novo_banco(job("gupy:1"), job("gupy:2", tier=2))
        self.api = FakeAPI()
        self.bot = Bot(self.api, self.con, CHAT)

    def msg(self, texto, chat=CHAT):
        self.bot.process_update({"update_id": 1, "message": {"chat": {"id": int(chat)}, "text": texto}})

    def test_chat_nao_autorizado_e_ignorado(self):
        self.msg("/fila", chat="999")
        self.assertEqual(self.api.sent, [])
        self.assertEqual(db.get_job(self.con, "gupy:1")["status"], "shortlisted")  # nada mudou

    def test_fila_oferece_com_botoes_e_nao_repete(self):
        self.msg("/fila")
        enviados = [p for m, p in self.api.sent if m == "sendMessage"]
        self.assertEqual(len(enviados), 2)
        self.assertIn("reply_markup", enviados[0])
        self.assertEqual(db.get_job(self.con, "gupy:1")["status"], "offered")
        self.api.sent.clear()
        self.msg("/fila")
        self.assertIn("Nenhuma vaga nova", self.api.texts()[0])

    def test_clique_no_botao_aprova(self):
        self.msg("/fila")
        self.bot.process_update({"update_id": 2, "callback_query": {"id": "c1", "data": "a:gupy:1",
                                                                      "message": {"chat": {"id": int(CHAT)}}}})
        self.assertEqual(db.get_job(self.con, "gupy:1")["status"], "approved")
        self.assertTrue(any(m == "answerCallbackQuery" for m, _ in self.api.sent))

    def test_callback_de_outro_chat_e_ignorado(self):
        self.bot.process_update({"update_id": 2, "callback_query": {"id": "c1", "data": "a:gupy:1",
                                                                      "message": {"chat": {"id": 999}}}})
        self.assertEqual(db.get_job(self.con, "gupy:1")["status"], "shortlisted")

    def test_fluxo_pendencia_pelo_chat(self):
        approval.prepare_questions(self.con, db.get_job(self.con, "gupy:1"), [Q("Conhece Zendesk?", SN)], CFG)
        self.msg("/pendencias")
        self.assertIn("/r 1", self.api.texts()[-1])
        self.msg("/r 1 Não")
        self.assertIn("Anotado", self.api.texts()[-1])
        self.msg("/r x")
        self.assertIn("Uso:", self.api.texts()[-1])

    def test_mensagem_longa_e_dividida(self):
        self.bot.send("a" * 9000)
        partes = self.api.texts()
        self.assertEqual(len(partes), 3)
        self.assertTrue(all(len(p) <= 4096 for p in partes))

    def test_comando_desconhecido(self):
        self.msg("oi")
        self.assertIn("/ajuda", self.api.texts()[-1])


if __name__ == "__main__":
    unittest.main()
