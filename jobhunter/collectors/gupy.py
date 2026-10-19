"""Coletor da Gupy: lê o JSON embutido (__NEXT_DATA__) das páginas públicas de busca. Sem login."""
import html
import json
import re
import time
from urllib.parse import quote

import requests

BASE = "https://portal.gupy.io/job-search/term={term}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
           "Accept-Language": "pt-BR,pt;q=0.9"}
_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
KIND = {"vacancy_type_effective": "efetivo", "vacancy_type_internship": "estagio", "vacancy_type_pj": "pj",
        "vacancy_type_talent_pool": "banco_talentos", "vacancy_type_temporary": "temporario",
        "vacancy_type_apprentice": "aprendiz", "vacancy_legal_entity": "pj"}


def clean(text):
    """Remove tags/entidades HTML e normaliza espaços."""
    text = html.unescape(text or "").replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def parse_page(page_html):
    """Extrai (lista_de_vagas, paginação) do HTML. Levanta ValueError se a estrutura mudou."""
    m = _NEXT.search(page_html)
    if not m:
        raise ValueError("__NEXT_DATA__ não encontrado (a Gupy pode ter mudado o site ou bloqueado)")
    data = json.loads(m.group(1))
    try:
        lst = data["props"]["pageProps"]["initialJobList"]
        return lst["data"], lst.get("pagination", {})
    except KeyError as e:
        raise ValueError(f"estrutura inesperada: faltou {e}") from e


def normalize(raw):
    name = re.sub(r"^\d+\s*-\s*", "", raw.get("name", "")).strip()  # tira "12732048 - " do título
    url = (raw.get("jobUrl") or "").split("?")[0]
    # o portal da Gupy também lista vagas de OUTROS sites (ex.: vaga-ja.com); essas não usam o fluxo da Gupy
    externo = re.match(r"https?://(?:www\.)?([^/]+)", url)
    fonte = "gupy" if not externo or externo.group(1).endswith("gupy.io") else "gupy-ext"
    return {
        "id": f"gupy:{raw['id']}",
        "source": fonte,
        "title": name,
        "company": (raw.get("careerPageName") or "").strip(),
        "url": url,
        "description": clean(raw.get("description")),
        "workplace": raw.get("workplaceType") or "",
        "kind": KIND.get(raw.get("type"), raw.get("type") or ""),
        "published": raw.get("publishedDate") or "",
        "deadline": raw.get("applicationDeadline") or "",
    }


def _get(session, url, params, tentativas=3):
    """GET com nova tentativa em 429/5xx e erros de rede (espera 2s, 6s, 12s)."""
    ultimo = None
    for i in range(tentativas):
        try:
            r = session.get(url, params=params, headers=HEADERS, timeout=25)
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = requests.HTTPError(f"HTTP {r.status_code}")
            else:
                r.raise_for_status()
                return r
        except (requests.ConnectionError, requests.Timeout) as e:
            ultimo = e
        time.sleep((2, 6, 12)[min(i, 2)])
    raise ultimo


def fetch_term(term, max_pages=3, pause=1.5, session=None):
    """Busca um termo (somente remoto). Devolve vagas normalizadas, sem repetir id."""
    s = session or requests.Session()
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        params = {"workplaceTypes[]": "remote"}
        if page > 1:
            params["page"] = page
        r = _get(s, BASE.format(term=quote(term)), params)
        r.encoding = "utf-8"
        rows, pg = parse_page(r.text)
        for raw in rows:
            job = normalize(raw)
            if job["id"] not in seen:
                seen.add(job["id"])
                out.append(job)
        total, limit, offset = pg.get("total", 0), pg.get("limit", 12), pg.get("offset", 0)
        if not rows or offset + limit >= total:
            break
        time.sleep(pause)
    return out


def collect(terms, max_pages=3, pause=1.5):
    """Todos os termos; erros de um termo não derrubam os outros. Devolve (vagas, erros)."""
    jobs, errors, seen = [], [], set()
    s = requests.Session()
    for term in terms:
        try:
            for j in fetch_term(term, max_pages, pause, s):
                if j["id"] not in seen:
                    seen.add(j["id"])
                    jobs.append(j)
        except Exception as e:  # noqa: BLE001 - queremos seguir mesmo com falha pontual
            errors.append(f"{term}: {e}")
        time.sleep(pause)
    return jobs, errors
