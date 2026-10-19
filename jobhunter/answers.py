"""Banco de respostas: decide o que o robô responde sozinho e o que vira pendência para o humano.

resolve(question, job_kind, cfg) -> Result(kind, value, reason, rule)
  kind = 'answer'    : resposta segura vinda do answers.yml
         'pending'   : sem regra, ambígua ou arriscada -> perguntar ao usuário
         'sensitive' : documento/dado de família/dado sensível -> NUNCA preencher sozinho
"""
import os
import re
import unicodedata
from collections import namedtuple

import yaml

Question = namedtuple("Question", "text options")  # options: lista de textos (vazia = campo de texto)
Result = namedtuple("Result", "kind value reason rule")

HERE = os.path.dirname(os.path.abspath(__file__))
RE_HORA = re.compile(r"\d{1,2}\s*h\s*\d{0,2}\s*(?:as|a|ate|-)\s*\d{1,2}\s*h?|\d{1,2}:\d{2}")
RE_NUM = re.compile(r"\d[\d.]*(?:,\d{1,2})?")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


_CACHE = {}


_GENERICAS = {"grupo", "banco", "instituto", "empresa", "vagas", "vaga", "carreiras", "oportunidades", "cooperativa",
              "rede", "confidenciais", "confidencial", "brasil", "tecnologia", "servicos", "sistemas"}


def _nomes(empresa):
    """Nome completo + primeira palavra distintiva ('Alper Carreiras' -> alper|alper carreiras). Vazio = nunca casa."""
    nome = norm(empresa)
    if len(nome) < 3:
        return "(?!)"
    partes = [re.escape(nome)]
    for tok in re.findall(r"[a-z0-9]+", nome):
        if len(tok) >= 4 and tok not in _GENERICAS:
            partes.append(re.escape(tok))
            break
    return "(?:" + "|".join(dict.fromkeys(partes)) + ")"


def _regex(pattern, empresa):
    """{empresa} vira o nome da empresa da vaga (sem acento)."""
    nome = _nomes(empresa)
    chave = (pattern, nome)
    if chave not in _CACHE:
        _CACHE[chave] = re.compile(pattern.replace("{empresa}", nome))
    return _CACHE[chave]


EXEMPLO = os.path.join(HERE, "answers.example.yml")


def load(path=None):
    """answers.yml (seu, fora do git) ou, se não existir, o modelo answers.example.yml."""
    meu = os.path.join(HERE, "answers.yml")
    with open(path or (meu if os.path.exists(meu) else EXEMPLO), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_sens"] = [re.compile(p) for p in cfg["sensivel"]]
    cfg["_regras"] = list(cfg["regras"])
    return cfg


def _numeros(texto):
    out = []
    for m in RE_NUM.findall(texto):
        v = m.replace(".", "").split(",")[0]
        if v.isdigit():
            out.append(int(v))
    return out


def pick_option(value, options):
    """Devolve o texto ORIGINAL da opção que corresponde ao valor, ou None."""
    nv = norm(str(value))
    for o in options:
        if norm(o) == nv:
            return o
    return None


def _faixa(opt):
    n, nums = norm(opt), _numeros(opt)
    if not nums:
        return None
    if n.startswith("ate") or " ate r" in n[:8]:
        return (0, nums[0])
    if "acima" in n or "mais de" in n:
        return (nums[0], float("inf"))
    if len(nums) >= 2:
        return (nums[0], nums[1])
    return None


def _alvo(job_kind, cfg):
    """Pretensão do perfil para o tipo de vaga. Farmacêutico tem faixa própria; sem ela -> None (vira pendência)."""
    chave = {"estagio": "estagio", "farmaceutico": "farmaceutico"}.get(job_kind, "junior")
    return cfg["perfil"]["pretensao"].get(chave)


def _pretensao(q, job_kind, cfg):
    alvo = _alvo(job_kind, cfg)
    if alvo is None:
        return Result("pending", None, f"sem pretensão definida para vagas de {job_kind}", "pretensao")
    if not q.options:
        return Result("answer", str(alvo), "pretensão do perfil", "pretensao")
    for o in q.options:
        f = _faixa(o)
        if f and f[0] <= alvo <= f[1]:
            return Result("answer", o, f"faixa que contém {alvo}", "pretensao")
    return Result("pending", None, f"nenhuma faixa contém R$ {alvo}", "pretensao")


def _sim_nao(options):
    return bool(options) and {norm(o) for o in options} <= {"sim", "nao"}


def resolve(q, job_kind="efetivo", cfg=None, learned=None, company="", remoto=False):
    """learned: função opcional qnorm -> resposta aprendida (respostas que o usuário já deu antes)."""
    cfg = cfg or load()
    n = norm(q.text)

    if any(p.search(n) for p in cfg["_sens"]):
        return Result("sensitive", None, "documento/dado pessoal sensível: o usuário preenche", None)
    if RE_HORA.search(n):
        if remoto and _sim_nao(q.options):  # decisão do usuário: vaga remota aceita qualquer horário
            return Result("answer", pick_option("Sim", q.options), "vaga remota: qualquer horário serve", "horario_remoto")
        return Result("pending", None, "pergunta sobre horário específico", None)

    # Sim/Não que embute um valor de salário: só responde "Sim" se o valor cobre a pretensão
    if _sim_nao(q.options) and re.search(r"pretens|salari|remuner", n):
        vals = [v for v in _numeros(n) if v >= 500]
        if vals:
            alvo = _alvo(job_kind, cfg)
            if alvo is None:
                return Result("pending", None, f"sem pretensão definida para vagas de {job_kind}", "pretensao_sim_nao")
            if max(vals) < alvo:
                return Result("pending", None, f"pergunta aceita até R$ {max(vals)}, abaixo da sua pretensão R$ {alvo}", "pretensao_sim_nao")
            return Result("answer", pick_option("Sim", q.options), "valor cobre a pretensão", "pretensao_sim_nao")

    for r in cfg["_regras"]:
        if not _regex(r["match"], company).search(n):
            continue
        if r.get("tipo") == "pretensao":
            return _pretensao(q, job_kind, cfg)
        valor = cfg["perfil"][r["responder_perfil"]] if "responder_perfil" in r else r["responder"]
        if q.options:
            opcao = pick_option(valor, q.options)
            if opcao is None:
                return Result("pending", None, f"regra '{r['id']}' sugere '{valor}', mas não há essa opção", r["id"])
            return Result("answer", opcao, "banco de respostas", r["id"])
        return Result("answer", str(valor), "banco de respostas", r["id"])

    if learned:
        antes = learned(n)
        if antes is not None:
            opcao = pick_option(antes, q.options) if q.options else antes
            if opcao is not None:
                return Result("answer", opcao, "resposta que você já deu antes", "aprendida")
    return Result("pending", None, "sem resposta salva para esta pergunta", None)


def resolve_all(questions, job_kind="efetivo", cfg=None, learned=None, company="", remoto=False):
    """Resolve uma lista. Devolve (resultados, completo): completo só se TODAS foram 'answer'."""
    cfg = cfg or load()
    res = [resolve(q, job_kind, cfg, learned, company, remoto) for q in questions]
    return res, all(r.kind == "answer" for r in res)
