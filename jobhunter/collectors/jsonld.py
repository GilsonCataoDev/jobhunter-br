"""Leitor do padrão schema.org JobPosting (JSON-LD), usado por vaga-ja.com, InfoJobs e muitos outros sites."""
import json
import re

from .gupy import clean

_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
RE_REMOTO = re.compile(r"100\s*%\s*remot|home[\s-]?office|teletrabalho|trabalho remoto|totalmente remot|full remote", re.I)
RE_HIBRIDO = re.compile(r"h[ií]brid|presencial", re.I)


def job_posting(page_html):
    """Primeiro objeto JobPosting da página (ou None)."""
    for bloco in _LD.findall(page_html):
        try:
            dado = json.loads(bloco)
        except ValueError:
            continue
        for d in dado if isinstance(dado, list) else dado.get("@graph", [dado]):
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                return d
    return None


def _salario(jp):
    v = (jp.get("baseSalary") or {}).get("value") or {}
    if isinstance(v, (int, float)):
        return v
    return v.get("minValue") or v.get("value") or v.get("maxValue")


def kind(jp, texto):
    """efetivo | estagio | pj | temporario | aprendiz, pelo employmentType e pelo texto."""
    tipo = str(jp.get("employmentType") or "").lower()
    t = texto.lower()
    if "intern" in tipo or re.search(r"\best[aá]gi", t[:200]):
        return "estagio"
    if re.search(r"jovem aprendiz|\baprendiz\b", t[:200]):
        return "aprendiz"
    if "contractor" in tipo or re.search(r"\(pj\)|regime[^.\n]{0,30}\bpj\b|presta[cç][aã]o de servi[cç]os|prestador de servi", t):
        return "pj"
    if "temporary" in tipo or re.search(r"\btempor[aá]ri", t[:300]):
        return "temporario"
    return "efetivo"


def workplace(jp, texto):
    if str(jp.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        return "remote"
    if RE_REMOTO.search(texto):
        return "hybrid" if re.search(r"h[ií]brid", texto, re.I) else "remote"
    return "on-site"


def normalize(jp, source, jid, url):
    """JobPosting -> formato interno (o mesmo do coletor da Gupy). O salário vai para a descrição, onde as regras o leem."""
    titulo = clean(jp.get("title", "")).replace("\xa0", " ")
    desc = clean(re.sub(r"<br\s*/?>|</(?:p|li|h\d)>", "\n", jp.get("description", ""), flags=re.I))
    sal = _salario(jp)
    if sal:
        desc = f"Salário: R$ {sal:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + "\n" + desc
    texto = f"{titulo}\n{desc}"
    return {
        "id": f"{source}:{jid}",
        "source": source,
        "title": re.sub(r"\s+", " ", titulo).strip(),
        "company": clean(((jp.get("hiringOrganization") or {}).get("name")) or "").strip(),
        "url": url,
        "description": desc,
        "workplace": workplace(jp, texto),
        "kind": kind(jp, texto),
        "published": (jp.get("datePosted") or "")[:19],
        "deadline": (jp.get("validThrough") or "")[:19],
    }
