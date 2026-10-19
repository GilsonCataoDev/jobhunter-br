"""Fila de aprovação e pendências. Sem dependência de Telegram: o bot só traduz mensagens para estas funções.

Fluxo de status: shortlisted -> offered -> approved | skipped        (Fase 3 envia as 'approved')
Regra de ouro: vaga aprovada com pergunta pendente NÃO é enviada (a Fase 3 só envia 'approved' sem pendência
aberta); dado sensível o usuário preenche sozinho e nunca é gravado.
"""
import json

from . import answers, db

SENSIVEL = "SENSÍVEL"


def prepare_questions(con, job, questions, cfg=None):
    """Resolve as perguntas de uma vaga. Perguntas sem resposta segura viram pendências no banco.
    Devolve (resultados, completo). `questions`: lista de answers.Question."""
    cfg = cfg or answers.load()
    kind = "farmaceutico" if "farmac" in answers.norm(job["title"]) else job["kind"]
    res, completo = answers.resolve_all(questions, kind, cfg, lambda qn: db.learned(con, qn), job["company"],
                                        remoto=job["workplace"] == "remote")
    for i, (q, r) in enumerate(zip(questions, res)):
        if r.kind == "sensitive":  # você confirmou esta pergunta, NESTA vaga, direto ao assistente (ver confirmar_sensivel)
            v = db.learned(con, _chave_vaga(job["id"], answers.norm(q.text)))
            ok = answers.pick_option(v, q.options) if (v and q.options) else v
            if ok:
                res[i] = r = answers.Result("answer", ok, "confirmada por você nesta vaga", "confirmada")
        if r.kind == "answer":
            continue
        motivo = f"{SENSIVEL}: {r.reason}" if r.kind == "sensitive" else r.reason
        db.add_pending(con, job["id"], q.text, answers.norm(q.text), list(q.options), motivo)
    return res, all(r.kind == "answer" for r in res)


def _chave_vaga(job_id, qnorm):
    return f"{job_id}|{qnorm}"


def confirmar_sensivel(con, pending_id, resposta):
    """Grava, SÓ PARA A VAGA DA PENDÊNCIA, a resposta que o usuário ditou ao assistente para uma pergunta sensível.
    Nunca é reaproveitada em outra vaga nem passa pelo /r do bot (que recusa dado sensível). Devolve a resposta usada."""
    row = con.execute("SELECT * FROM pending_questions WHERE id=?", (pending_id,)).fetchone()
    if not row or row["status"] != "open":
        return None
    opcoes = json.loads(row["options"])
    if opcoes:
        resposta = answers.pick_option(resposta, opcoes)
        if resposta is None:
            return None
    db.answer_pending(con, pending_id, resposta, learn=False)
    con.execute("INSERT OR REPLACE INTO learned_answers (qnorm, answer, created) VALUES (?,?,?)",
                (_chave_vaga(row["job_id"], row["qnorm"]), resposta, db.now()))
    con.commit()
    return resposta


def offer_text(job):
    faixa = {1: "TI/Suporte/QA", 2: "Administrativo", 3: "Atendimento"}.get(job["tier"], "")
    linhas = [f"{job['title']}", f"{job['company']} · {job['kind']} · remoto · {faixa}"]
    if job["warnings"]:
        linhas.append(f"⚠ {job['warnings']}")
    linhas.append(job["url"])
    return "\n".join(linhas)


def keyboard(job_id):
    return {"inline_keyboard": [[{"text": "✅ Aprovar", "callback_data": f"a:{job_id}"},
                                 {"text": "⏭ Pular", "callback_data": f"s:{job_id}"}]]}


def offer_next(con, limit=10):
    """Passa até `limit` vagas 'shortlisted' para 'offered' e devolve [(texto, teclado)]."""
    out = []
    for job in db.jobs_with_status(con, "shortlisted", limit):
        db.set_status(con, job["id"], "offered")
        out.append((offer_text(job), keyboard(job["id"])))
    return out


def on_callback(con, data):
    """'a:<id>' aprova, 's:<id>' pula. Devolve o texto de resposta."""
    try:
        acao, job_id = data.split(":", 1)
    except ValueError:
        return "Ação inválida."
    job = db.get_job(con, job_id)
    if not job:
        return "Vaga não encontrada."
    if job["status"] not in ("offered", "shortlisted", "approved", "skipped"):
        return f"Esta vaga já está '{job['status']}'."
    if acao == "s":
        db.set_status(con, job_id, "skipped")
        con.commit()
        return f"Pulada: {job['title']}"
    if acao == "a":
        abertas = db.open_pending(con, job_id)
        db.set_status(con, job_id, "approved")
        con.commit()
        extra = f"\n⚠ {len(abertas)} pergunta(s) pendente(s): use /pendencias." if abertas else ""
        return f"Aprovada: {job['title']} ({job['company']}). Entra na fila de envio.{extra}"
    return "Ação inválida."


def pendencias_text(con):
    rows = db.open_pending(con)
    if not rows:
        return "Nenhuma pergunta pendente."
    linhas = [f"{len(rows)} pergunta(s) pendente(s):"]
    for r in rows:
        job = db.get_job(con, r["job_id"])
        opcoes = json.loads(r["options"])
        sens = r["reason"].startswith(SENSIVEL)
        linhas.append(f"\n#{r['id']} — {job['company'] if job else '?'}\n{r['question']}")
        if opcoes:
            linhas.append("Opções: " + " | ".join(opcoes))
        linhas.append(("Preencha você mesmo na vaga, depois /feito %d" % r["id"]) if sens
                      else f"Motivo: {r['reason']}\nResponder: /r {r['id']} sua resposta")
    return "\n".join(linhas)


def on_answer(con, pending_id, resposta):
    """/r <id> <resposta>. Dado sensível é recusado e NUNCA gravado."""
    row = con.execute("SELECT * FROM pending_questions WHERE id=?", (pending_id,)).fetchone()
    if not row or row["status"] != "open":
        return "Pergunta não encontrada ou já respondida."
    if row["reason"].startswith(SENSIVEL):
        return "Dado sensível: não guardo isso. Preencha você mesmo na vaga e use /feito %d." % pending_id
    opcoes = json.loads(row["options"])
    if opcoes:
        escolhida = answers.pick_option(resposta, opcoes)
        if escolhida is None:
            return "Resposta deve ser uma destas: " + " | ".join(opcoes)
        resposta = escolhida
    db.answer_pending(con, pending_id, resposta, learn=True)
    con.commit()
    return f"Anotado: {resposta}. Vou reaproveitar em perguntas iguais."


def on_done(con, pending_id):
    """/feito <id>: o usuário preencheu um dado sensível por conta própria."""
    row = con.execute("SELECT * FROM pending_questions WHERE id=?", (pending_id,)).fetchone()
    if not row or row["status"] != "open":
        return "Pergunta não encontrada ou já resolvida."
    db.answer_pending(con, pending_id, "(preenchido pelo usuário)", learn=False)
    con.commit()
    return "Ok, marcada como feita."
