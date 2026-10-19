"""Regras determinísticas (sem IA) com o que aprendemos lendo vagas reais.

evaluate(job, cfg) -> Decision(ok, reason, warnings, tier)
Rejeita só com motivo claro. Dúvida vira aviso (warnings), para o humano decidir.
"""
import re
from collections import namedtuple
from datetime import datetime, timezone

Decision = namedtuple("Decision", "ok reason warnings tier")

DESEJAVEL = re.compile(
    r"desej[aá]ve(?:l|is)|diferencia(?:l|is)|bacana|ser[ií]a interessante|se tiver|opcional|ser[aá] um plus|n[aã]o [eé] obrigat|"
    r"n[aã]o obrigat|voc[eê] ir[aá] se diferenciar|ou desej", re.I)
SEM_EXP = re.compile(r"sem experi[eê]ncia|n[aã]o (?:[eé] )?(?:necess[aá]ri|exig)|n[aã]o precisa de experi", re.I)

RE_INGLES = re.compile(r"ingl[eê]s (?:avan[cç]ado|fluente)|fluent english|advanced english|english (?:fluency|advanced)|"
                       r"flu[eê]ncia (?:em|no) ingl[eê]s", re.I)
RE_ESPANHOL = re.compile(r"espanhol|espa[nñ]ol|spanish", re.I)
RE_EXP = re.compile(r"experi[eê]ncia (?:comprovada|pr[eé]via|anterior|m[ií]nima|s[oó]lida|consolidada|"
                    r"(?:profissional )?(?:em|na|no|como|com|de)\b)", re.I)
# Só conta anos colados em "experiência" (evita "20 anos de mercado" da empresa).
RE_ANOS = re.compile(r"experi[eê]ncia[^.\n]{0,50}?(\d{1,2})\s*(?:a\s*\d{1,2}\s*)?\+?\s*(?:anos?|years?)\b|"
                     r"(\d{1,2})\s*(?:a\s*\d{1,2}\s*)?\+?\s*(?:anos?|years?)\s*(?:de|em)\s*(?:experi[eê]ncia|atua[cç][aã]o profissional)",
                     re.I)
RE_SUPERIOR_COMPLETO = re.compile(r"(?:ensino )?superior completo|gradua[cç][aã]o completa|bacharel(?:ado)? completo", re.I)
RE_EM_CURSO = re.compile(r"cursando|em andamento|incompleto|em fase|ou cursando|cursa", re.I)
RE_AREA_FORA = re.compile(r"(?:superior|gradua[cç][aã]o|cursando|forma[cç][aã]o)[^.\n]{0,80}"
                          r"(contabilidade|ci[eê]ncias cont[aá]beis|administra[cç][aã]o|engenharia|direito|economia|"
                          r"gest[aã]o financeira|pedagogia|marketing)", re.I)
RE_AREA_OK = re.compile(r"tecnologia|computa[cç][aã]o|sistemas|an[aá]lise e desenvolvimento|\bti\b|inform[aá]tica|ou [aá]reas? (?:afins|correlat)", re.I)
RE_PRESENCIAL = re.compile(
    r"necess[aá]rio presencial|presencial\w*\s*(?:\d+\s*x|2x|duas|2 vezes|uma vez)|(?:visitas?|reuni[oõ]es?)\s+presenciais?\s+"
    r"(?:semanais|quinzenais|mensais)|posto de atendimento|caixas? eletr[oô]nic|atendimento (?:ao cooperado|em ag[eê]ncia)",
    re.I)
RE_GOLPE = re.compile(r"taxa de inscri|pagamento antecipado|investimento inicial|renda extra|ganhe at[eé]|depósito prévio", re.I)
RE_HORARIO = re.compile(r"(\d{1,2})\s*(?:h|:)\s*(\d{2})?\s*(?:[àa]s|a|-|at[eé])\s*(\d{1,2})\s*(?:h|:)\s*(\d{2})?", re.I)
RE_SALARIO = re.compile(r"(?:sal[aá]rio|remunera[cç][aã]o|bolsa[- ]aux[ií]lio)[^R\n]{0,40}R\$\s*([\d.]+)", re.I)


def _linhas(texto):
    """Frases/linhas curtas, para saber se 'experiência' está em requisito ou em item desejável."""
    # quebra também frases coladas sem espaço ("diferenças.Realizar")
    partes = re.split(r"[\n;•]|(?<=[.!?])\s*(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])", texto)
    return [p.strip() for p in partes if p.strip()]


# Cabeçalho de seção desejável ("Requisitos Desejáveis -", "Diferenciais:"): tudo o que vem depois, até o próximo
# bloco (benefícios, informações adicionais…), é desejável mesmo que a frase em si não repita a palavra.
HEADER_DESEJ = re.compile(r"(?:requisitos|qualifica[cç][õo]es|conhecimentos|itens)\s+(?:desej[aá]ve(?:l|is)|diferenciais)"
                          r"|diferenciais\s*[:\-–]|desej[aá]ve(?:l|is)\s*[:\-–]", re.I)
FIM_SECAO = re.compile(r"informa[cç][õo]es adicionais|benef[ií]cios|sobre a empresa|etapas do processo|remunera[cç][aã]o", re.I)


def _exigencias(texto):
    """Linhas que podem ser EXIGÊNCIA: descarta as de itens desejáveis e as que seguem um cabeçalho de desejáveis."""
    em_desejavel = False
    for ln in _linhas(texto):
        if FIM_SECAO.search(ln):
            em_desejavel = False
        if HEADER_DESEJ.search(ln):
            em_desejavel = True
        if em_desejavel or DESEJAVEL.search(ln) or SEM_EXP.search(ln):
            continue
        yield ln


def obrigatorio(texto, padrao):
    """Algum trecho casa o padrão e NÃO é item desejável/diferencial?"""
    for ln in _exigencias(texto):
        m = padrao.search(ln)
        if m and not _fala_da_empresa(ln[:m.start()]):
            return ln[:90]
    return ""


def _fala_da_empresa(antes):
    """'A X, empresa com mais de 20 anos de experiência…' descreve a empresa, não pede nada ao candidato."""
    return bool(re.search(r"(empresa|companhia|grupo|institui[cç][aã]o|somos|temos)\b[^.]{0,40}$", antes, re.I))


_CACHE_KW = {}


def _palavras(lista):
    """Regex de palavras do título: começo de palavra sempre; fim de palavra só para termos curtos (<=4),
    assim 'lead' não pega 'Leads/Misleading' e 'sr' não pega 'SRE', mas 'jurídic' ainda pega 'jurídico'."""
    chave = tuple(lista)
    if chave not in _CACHE_KW:
        partes = []
        for k in lista:
            k = k.strip().lower()
            if not k:
                continue
            fim = r"(?![a-zà-ú0-9])" if len(k) <= 4 else ""
            partes.append(r"(?<![a-zà-ú0-9])" + re.escape(k) + fim)
        _CACHE_KW[chave] = re.compile("|".join(partes))
    return _CACHE_KW[chave]


def faixa(titulo, cfg):
    t = titulo.lower()
    for tier in sorted(cfg["faixas"]):
        if _palavras(cfg["faixas"][tier]).search(t):
            return tier
    return None


def _idade_dias(iso, agora):
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if d.tzinfo is None:  # InfoJobs/vaga-ja publicam datas sem fuso: trata como UTC
            d = d.replace(tzinfo=timezone.utc)
        return (agora - d).days
    except (ValueError, AttributeError):
        return 0


def evaluate(job, cfg, agora=None):
    agora = agora or datetime.now(timezone.utc)
    titulo = job["title"].lower()
    texto = f"{job['title']}\n{job['description']}"
    avisos = []

    if job["kind"] == "pj":
        return Decision(False, "PJ", "", None)
    if job["kind"] == "banco_talentos":
        return Decision(False, "banco de talentos (vaga não aberta)", "", None)
    if job["kind"] == "aprendiz":
        return Decision(False, "jovem aprendiz (programa até 24 anos)", "", None)
    if _palavras(cfg["titulo_proibido"]).search(titulo):
        return Decision(False, "título: senioridade/área/exclusiva", "", None)
    tier = faixa(job["title"], cfg)
    if tier is None:
        return Decision(False, "fora do foco (título)", "", None)

    if job.get("deadline"):
        d = _idade_dias(job["deadline"], agora)
        if d > 0:
            return Decision(False, "inscrições encerradas", "", tier)
    limite = cfg["gupy"]["dias_maximos"]
    if job.get("published") and _idade_dias(job["published"], agora) > limite:
        return Decision(False, f"publicada há mais de {limite} dias", "", tier)

    if RE_GOLPE.search(texto):
        return Decision(False, "possível golpe", "", tier)
    if RE_INGLES.search(texto) and obrigatorio(texto, RE_INGLES):
        return Decision(False, "inglês avançado/fluente", "", tier)
    if obrigatorio(texto, RE_ESPANHOL):
        return Decision(False, "espanhol", "", tier)

    ln = obrigatorio(texto, RE_PRESENCIAL)
    if ln:
        return Decision(False, f"presencial disfarçado: {ln}", "", tier)

    # superior completo / área de formação
    for linha in _linhas(texto):
        if RE_SUPERIOR_COMPLETO.search(linha) and not RE_EM_CURSO.search(linha) and not DESEJAVEL.search(linha):
            return Decision(False, "exige superior completo", "", tier)
        m = RE_AREA_FORA.search(linha)
        if m and not RE_AREA_OK.search(linha) and not DESEJAVEL.search(linha):
            return Decision(False, f"formação exigida: {m.group(1).lower()}", "", tier)

    # experiência
    anos = 0
    for linha in _exigencias(texto):
        for m in RE_ANOS.finditer(linha):
            # "empresa com mais de 20 anos de experiência" fala da EMPRESA, não do candidato
            if _fala_da_empresa(linha[:m.start()]):
                continue
            anos = max(anos, int(m.group(1) or m.group(2)))
    if anos > 1:
        return Decision(False, f"pede {anos} anos de experiência", "", tier)
    ln = obrigatorio(texto, RE_EXP)
    if ln:
        return Decision(False, f"experiência exigida: {ln}", "", tier)

    # salário informado
    if job["kind"] == "efetivo":
        vals = [int(v.replace(".", "")) for v in RE_SALARIO.findall(texto) if v.replace(".", "").isdigit()]
        if vals and max(vals) < cfg["salario_minimo_efetivo"]:
            return Decision(False, f"salário informado R$ {max(vals)}", "", tier)

    # avisos (não rejeitam)
    m = RE_HORARIO.search(texto)
    if m:
        avisos.append(f"horário fixo {m.group(0).strip()}")
    if "presencial" in texto.lower():
        avisos.append("cita 'presencial' — confira")
    if job["kind"] == "temporario":
        avisos.append("temporário")
    return Decision(True, "", "; ".join(avisos), tier)
