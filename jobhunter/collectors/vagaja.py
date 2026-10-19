"""Coletor do vaga-ja.com (robots.txt libera tudo). O site é pequeno: lê o sitemap de vagas, filtra pelo título no
endereço (slug) e só então abre as páginas candidatas, que trazem o JobPosting em JSON-LD. Sem login."""
import re
import time
import unicodedata

import requests

from . import jsonld
from .gupy import _get

SITEMAP = "https://vaga-ja.com/sitemap-vagas.xml"
_URL = re.compile(r"<loc>(https://vaga-ja\.com/vagas/[^<]+)</loc>")


def _slug(texto):
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")


def candidatas(sitemap_xml, palavras):
    """URLs cujo slug do TÍTULO contém alguma palavra-chave (já em formato slug)."""
    out = []
    for url in _URL.findall(sitemap_xml):
        titulo = url.rstrip("/").rsplit("/", 1)[-1]
        if any(p in titulo for p in palavras):
            out.append(url)
    return out


def collect(palavras, pausa=1.0, max_paginas=60):
    """Devolve (vagas, erros). `palavras`: termos de busca (ex.: os das faixas do config)."""
    s, vagas, erros = requests.Session(), [], []
    try:
        xml = _get(s, SITEMAP, {}).text
    except Exception as e:  # noqa: BLE001
        return [], [f"vaga-ja sitemap: {e}"]
    chaves = {_slug(p) for p in palavras if len(_slug(p)) >= 3}
    for url in candidatas(xml, chaves)[:max_paginas]:
        try:
            r = _get(s, url, {})
            r.encoding = "utf-8"
            jp = jsonld.job_posting(r.text)
            if jp:
                jid = ((jp.get("identifier") or {}).get("value")) or url.rsplit("/", 1)[-1]
                vagas.append(jsonld.normalize(jp, "vagaja", jid, url))
        except Exception as e:  # noqa: BLE001
            erros.append(f"vaga-ja {url}: {e}")
        time.sleep(pausa)
    return vagas, erros
