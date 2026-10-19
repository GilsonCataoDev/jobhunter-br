"""Executor: envia as vagas APROVADAS (e sem pendência) pela Gupy.

  python -m jobhunter.executor.run_apply            # DRY-RUN (padrão): preenche, não salva as respostas, não finaliza
  python -m jobhunter.executor.run_apply --send     # envia de verdade
Opções: --limit N  --headless  --db caminho

Guardas: limite diário, pausa entre vagas, para em CAPTCHA, para após falhas seguidas, nunca envia vaga com pendência.
"""
import argparse
import csv
import os
import random
import sys
import time
from datetime import datetime

from .. import answers, db
from ..run import APPLIED_LOG, load_cfg
from . import flow

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.normpath(os.path.join(HERE, "..", "data", "shots"))


def registrar_no_log(job, status="enviada", path=APPLIED_LOG):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([datetime.now().date().isoformat(), job["company"], job["title"], "gupy", status])


def run(con, driver, cfg, dry_run=True, limit=None, sleep=time.sleep, log_path=APPLIED_LOG, shots=SHOTS):
    ex = cfg["executor"]
    restante = ex["limite_diario"] - db.sent_today(con)
    if limit is not None:
        restante = min(restante, limit)
    travadas = [r["id"] for r in db.jobs_with_status(con, "sending")]
    resumo = {"tentadas": 0, "sent": 0, "dry_run_ready": 0, "pending": 0, "already_applied": 0, "needs_human": 0,
              "error": 0, "parou": "", "travadas": travadas}
    if travadas:  # uma execução anterior caiu no meio: NÃO reenviar sem um humano conferir na Gupy
        resumo["parou"] = f"{len(travadas)} vaga(s) em 'sending' de uma execução interrompida: confira na Gupy"
        return resumo
    if restante <= 0:
        resumo["parou"] = "limite diário atingido"
        return resumo
    acfg = answers.load()
    falhas = 0
    fila = db.approved_ready(con)[:restante]
    for n, job in enumerate(fila):
        shot = os.path.join(shots, f"{job['id'].replace(':', '_')}_{datetime.now():%H%M%S}.png")
        # Trava anti-duplicidade: grava 'sending' ANTES de mexer na Gupy. Se o processo cair, a vaga fica travada
        # (e não é reenviada por outra execução) até um humano conferir.
        db.set_status(con, job["id"], "sending")
        con.commit()
        out = flow.run_application(driver, con, job, dry_run, acfg, shot)
        if out.status not in ("sent", "already_applied"):
            db.set_status(con, job["id"], "approved")  # nada foi enviado: volta para a fila
        resumo["tentadas"] += 1
        resumo[out.status] += 1
        db.log_attempt(con, job["id"], out.status, out.detail, shot if os.path.exists(shot) else "", dry_run)
        if out.status == "sent":
            db.set_status(con, job["id"], "sent")
            registrar_no_log(job, "enviada", log_path)
            falhas = 0
        elif out.status == "already_applied":
            db.set_status(con, job["id"], "applied_before")
            registrar_no_log(job, "ja_enviada", log_path)
            falhas = 0
        elif out.status in ("needs_human", "error"):
            falhas += 1
            if "CAPTCHA" in out.detail or "LOGIN" in out.detail:
                resumo["parou"] = ("CAPTCHA: parei para você resolver" if "CAPTCHA" in out.detail
                                   else "sessão da Gupy expirada: rode python -m jobhunter.executor.driver_playwright --login")
                con.commit()
                break
        else:  # pending, dry_run_ready
            falhas = 0
        con.commit()
        if falhas >= ex["falhas_seguidas_max"]:
            resumo["parou"] = f"{falhas} falhas seguidas"
            break
        if n < len(fila) - 1:
            sleep(random.uniform(ex["pausa_min_s"], ex["pausa_max_s"]))
    return resumo


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="envia de verdade (sem isto é dry-run)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--db")
    args = ap.parse_args(argv)

    from .driver_playwright import PlaywrightDriver
    cfg = load_cfg()
    con = db.connect(args.db)
    driver = PlaywrightDriver(headless=args.headless)
    try:
        resumo = run(con, driver, cfg, dry_run=not args.send, limit=args.limit)
    finally:
        driver.close()
    print(("ENVIO REAL" if args.send else "DRY-RUN"), resumo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
