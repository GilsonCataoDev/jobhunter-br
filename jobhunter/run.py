"""Fase 1: coleta (Gupy) -> deduplica -> regras -> banco -> resumo. NÃO envia candidatura.

Uso:  python -m jobhunter.run [--dry-run] [--no-notify]
"""
import argparse
import csv
import os
import re
import sys
import unicodedata
from collections import Counter

import yaml

from . import db, notify, rules
from .collectors import gupy, infojobs, vagaja

HERE = os.path.dirname(os.path.abspath(__file__))
APPLIED_LOG = os.path.join(HERE, "..", "auto_apply", "applied_log.csv")


def load_cfg(path=None):
    with open(path or os.path.join(HERE, "config.yml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def applied_companies(path=APPLIED_LOG):
    """Empresas em que já há candidatura (uma por empresa). Aceita CSV sem cabeçalho: data,empresa,vaga,..."""
    if not os.path.exists(path):
        return set()
    out = set()
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[1].strip():
                out.add(row[1].strip())
    return out


def norm_company(nome):
    return "".join(ch for ch in nome.lower() if ch.isalnum())


def host_slug(url):
    """'https://vagasstefanini.gupy.io/job/..' -> 'vagasstefanini' (a página de carreira revela a empresa)."""
    m = re.match(r"https?://([^./]+)\.gupy\.io", url or "")
    return m.group(1).lower() if m else ""


GENERICAS = {"grupo", "banco", "instituto", "empresa", "vagas", "vaga", "carreiras", "seguros", "farmacias", "farmacia",
             "drogaria", "drogarias", "servicos", "sistemas", "brasil", "jobs", "confidenciais", "confidencial", "rede",
             "saude", "de", "da", "do", "e"}


def _sem_parenteses(nome):
    """'Vagas Confidenciais (consórcio)' -> 'Vagas Confidenciais': anotações no log não fazem parte do nome."""
    return re.sub(r"\([^)]*\)", " ", nome)


def _tokens(nome):
    nome = _sem_parenteses(nome)
    return set(re.findall(r"[a-z0-9]+", "".join(c for c in unicodedata.normalize("NFKD", nome.lower())
                                                if not unicodedata.combining(c))))


def ja_aplicada(job, applied):
    """Já há candidatura nesta empresa? `applied` = nomes do log (qualquer grafia).
    Casa por PALAVRAS inteiras ('Omie' ⊂ 'Omie Brasil', mas NÃO 'Homie'); nomes longos (>=6) também casam por
    'contém' no subdomínio da vaga (stefanini ⊂ vagasstefanini)."""
    toks_vaga = _tokens(job["company"])
    host = host_slug(job["url"])
    for a in applied:
        # palavras genéricas do nome no LOG ("Seguros", "Farmácias", "Carreiras") não contam: o log diz
        # "Alper Seguros" e a Gupy diz "Alper Carreiras". Nome SÓ genérico ("Empresa confidencial") não identifica
        # empresa nenhuma: não serve para deduplicar (senão toda vaga anônima pareceria repetida).
        toks_a = _tokens(a) - GENERICAS
        if not toks_a:
            # exceção: na Gupy, "Vagas Confidenciais" é UMA página de carreira (um recrutador); lá o nome igual vale
            if host and _tokens(a) == toks_vaga:
                return True
            continue
        if toks_a <= toks_vaga:
            return True
        colado = norm_company(_sem_parenteses(a))
        if len(colado) >= 6 and (colado in host or (len(host) >= 5 and host in colado)
                                 or colado in norm_company(job["company"])):
            return True
    return False


# Só estes status são reavaliados. offered/approved/skipped/notified são decisões humanas ou da Fase 2: não mexer.
REAVALIAVEIS = ("rejected", "shortlisted")


def process(jobs, con, cfg, applied):
    """Dedupe + regras e grava. Vagas 'rejected/shortlisted' são REAVALIADAS (as regras evoluem);
    qualquer outro status é preservado. stats['novas_aprovadas'] = ids que ACABARAM de entrar na lista."""
    conhecidas = db.known_status(con)
    stats = Counter()
    stats["novas_aprovadas"] = []
    for job in jobs:
        status_antigo = conhecidas.get(job["id"])
        if status_antigo is not None and status_antigo not in REAVALIAVEIS:
            db.touch(con, job["id"])
            stats["ja_vistas"] += 1
            continue
        if status_antigo is None:
            stats["novas"] += 1
        else:
            stats["reavaliadas"] += 1
        if ja_aplicada(job, applied):
            decisao = ("rejected", "já há candidatura nesta empresa", "", None)
        else:
            d = rules.evaluate(job, cfg)
            decisao = ("shortlisted", "", d.warnings, d.tier) if d.ok else ("rejected", d.reason, "", d.tier)
        if status_antigo is None:
            db.insert(con, job, decisao[0], decisao[1], decisao[2], decisao[3])
        else:
            db.update_decision(con, job["id"], *decisao)
        if decisao[0] == "shortlisted":
            stats["aprovadas"] += 1
            if status_antigo != "shortlisted":
                stats["novas_aprovadas"].append(job["id"])
        else:
            stats["rejeitadas"] += 1
    con.commit()
    return stats


def coletar_tudo(cfg):
    """Gupy + fontes extras ligadas no config. Das extras só ficam vagas REMOTAS (a Gupy já busca só remoto).
    Uma fonte fora do ar não derruba as outras."""
    g = cfg["gupy"]
    jobs, errors = gupy.collect(g["termos"], g["max_paginas_por_termo"], g["pausa_segundos"])
    extras = []
    ij = cfg.get("infojobs") or {}
    if ij.get("ativo"):
        v, e = infojobs.collect(ij.get("termos") or g["termos"], ij.get("max_paginas_por_termo", 2), g["pausa_segundos"])
        extras += v
        errors += e
    vj = cfg.get("vagaja") or {}
    if vj.get("ativo"):
        palavras = list(g["termos"]) + [t for faixa in cfg["faixas"].values() for t in faixa]
        v, e = vagaja.collect(palavras, g["pausa_segundos"], vj.get("max_paginas", 60))
        extras += v
        errors += e
    vistos = {j["id"] for j in jobs}
    for j in extras:
        if j["workplace"] == "remote" and j["id"] not in vistos:
            vistos.add(j["id"])
            jobs.append(j)
    return jobs, errors


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="usa banco em memória e não notifica")
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_cfg()
    con = db.connect(":memory:" if args.dry_run else None)
    jobs, errors = coletar_tudo(cfg)
    if not jobs and errors:
        print("Coleta falhou em todos os termos:", errors, file=sys.stderr)
        return 1

    stats = process(jobs, con, cfg, applied_companies())
    novas = [db.get_job(con, i) for i in stats["novas_aprovadas"]]
    novas.sort(key=lambda r: (r["tier"] or 9, r["published"] or ""))
    texto = notify.format_summary(novas, {"coletadas": len(jobs), "novas": stats["novas"],
                                          "rejeitadas": stats["rejeitadas"], "erros": errors})
    if novas:
        texto += chr(10) * 2 + "Para aprovar: mande /fila ao bot."
    if args.dry_run or args.no_notify:
        print(texto)
    else:
        notify.send(texto)  # status continua 'shortlisted': quem muda é o /fila do bot
    return 0


if __name__ == "__main__":
    sys.exit(main())
