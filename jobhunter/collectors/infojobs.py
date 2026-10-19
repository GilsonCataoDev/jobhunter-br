"""Coletor do InfoJobs (as páginas de busca e de vaga são liberadas no robots.txt). Usa o filtro "home office" do
próprio site, ordenado por data; abre cada vaga para ler o JobPosting (JSON-LD). Sem login."""
import re
import time
from urllib.parse import quote_plus

import requests

from . import jsonld
from .gupy import _get

BASE = "https://www.infojobs.com.br"
BUSCA = BASE + "/vagas-de-emprego-{termo}-trabalho-home-office.aspx"
_CARD = re.compile(r'data-id="(\d+)" class="[^"]*js_vacancyLoad[^"]*" data-href="([^"]+)"')


def cards(page_html):
    """[(id, caminho)] dos cartões de vaga de uma página de busca."""
    return _CARD.findall(page_html)


def fetch_term(termo, max_paginas=2, pausa=1.2, session=None, vistos=None):
    s = session or requests.Session()
    vistos = vistos if vistos is not None else set()
    out = []
    for page in range(1, max_paginas + 1):
        params = {"campo": "griddate", "orden": "desc"}
        if page > 1:
            params["Page"] = page
        r = _get(s, BUSCA.format(termo=quote_plus(termo)), params)
        r.encoding = "utf-8"
        lista = cards(r.text)
        novos = [(i, c) for i, c in lista if i not in vistos]
        if not novos:
            break
        for jid, caminho in novos:
            vistos.add(jid)
            d = _get(s, BASE + caminho, {})
            d.encoding = "utf-8"
            jp = jsonld.job_posting(d.text)
            if jp:
                job = jsonld.normalize(jp, "infojobs", jid, BASE + caminho)
                if job["workplace"] == "on-site" and "Home office" in d.text:
                    job["workplace"] = "remote"  # selo "Home office" da própria página
                out.append(job)
            time.sleep(pausa)
    return out


def collect(termos, max_paginas=2, pausa=1.2):
    """Todos os termos; falha de um termo não derruba os outros. Devolve (vagas, erros)."""
    s, vistos, vagas, erros = requests.Session(), set(), [], []
    for termo in termos:
        try:
            vagas.extend(fetch_term(termo, max_paginas, pausa, s, vistos))
        except Exception as e:  # noqa: BLE001
            erros.append(f"infojobs {termo}: {e}")
    return vagas, erros
