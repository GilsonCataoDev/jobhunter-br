"""Lote pontual de vagas PRESENCIAIS/HÍBRIDAS por estado (a coleta normal busca só remoto).

Busca na Gupy por termo + estado, mantém só vagas efetivas cujo título contenha `--titulo`, coloca na fila como
'approved' e roda o executor. SEM --send é dry-run: preenche, não salva. Você assume a aprovação ao usar este script
(as vagas não passam pelo /fila do bot), então confira a lista impressa antes de enviar.

Exemplo:
  python -m jobhunter.lote_por_estado --estados Pernambuco Alagoas --termos "farmacêutico" --titulo farmac
  python -m jobhunter.lote_por_estado --estados Pernambuco Alagoas --termos "farmacêutico" --titulo farmac --send
"""
import argparse
import sys
import time
from urllib.parse import quote

import requests

from . import db
from .collectors import gupy
from .executor import run_apply
from .run import load_cfg


def coletar(estados, termos, titulo, max_paginas=5, pausa=1.2):
    s, out = requests.Session(), {}
    for uf in estados:
        for termo in termos:
            for page in range(1, max_paginas + 1):
                params = {"state": uf}
                if page > 1:
                    params["page"] = page
                r = gupy._get(s, gupy.BASE.format(term=quote(termo)), params)
                r.encoding = "utf-8"
                rows, pg = gupy.parse_page(r.text)
                for raw in rows:
                    j = gupy.normalize(raw)
                    if raw.get("state") in estados and titulo.lower() in j["title"].lower() and j["kind"] == "efetivo" \
                            and j["source"] == "gupy":
                        out[j["id"]] = (j, raw.get("city") or "")
                if not rows or pg.get("offset", 0) + pg.get("limit", 12) >= pg.get("total", 0):
                    break
                time.sleep(pausa)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--estados", nargs="+", required=True, help="nomes completos, ex.: Pernambuco Alagoas")
    ap.add_argument("--termos", nargs="+", required=True)
    ap.add_argument("--titulo", required=True, help="trecho obrigatório no título da vaga (ex.: farmac)")
    ap.add_argument("--limite", type=int, default=60, help="máximo de envios nesta execução")
    ap.add_argument("--send", action="store_true", help="envia de verdade (sem isto, dry-run)")
    args = ap.parse_args(argv)

    con = db.connect()
    achadas = coletar(args.estados, args.termos, args.titulo)
    conhecidas = db.known_status(con)
    for jid, (j, cidade) in sorted(achadas.items(), key=lambda kv: kv[1][1]):
        st = conhecidas.get(jid)
        print(f"- {cidade:28} {j['company'][:28]:28} {j['title'][:50]}  [{st or 'nova'}]")
        if st is None:
            db.insert(con, j, "approved", "", f"lote por estado ({cidade})", 4)
        elif st in ("rejected", "shortlisted", "offered", "skipped"):
            db.set_status(con, jid, "approved")
    con.commit()
    print(f"{len(achadas)} vaga(s) na fila. {'ENVIO REAL' if args.send else 'DRY-RUN (use --send para enviar)'}", flush=True)

    cfg = load_cfg()
    cfg["executor"]["limite_diario"] = max(cfg["executor"]["limite_diario"], args.limite)
    from .executor.driver_playwright import PlaywrightDriver
    d = PlaywrightDriver(headless=True)
    try:
        resumo = run_apply.run(con, d, cfg, dry_run=not args.send, limit=args.limite)
    finally:
        d.close()
    print({k: v for k, v in resumo.items() if v})
    return 0


if __name__ == "__main__":
    sys.exit(main())
