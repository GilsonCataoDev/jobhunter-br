"""Fluxo de candidatura na Gupy, independente do navegador (o driver faz a parte de clicar).

Telas mapeadas ao vivo nesta sessão:
  1. "Olá …, vamos continuar sua candidatura?"  [Continuar]
  2. "Dados adicionais" (indicado? funcionário? -> Não)  [Salvar e continuar]
  3. "Perguntas criadas pela empresa" [Responder agora]  -> formulário -> [Salvar e continuar]
  4. Modal "Apresente-se!" [Finalizar candidatura]
  5. "Candidatura finalizada!"

Regras de segurança (todas testadas):
  - qualquer tela desconhecida, CAPTCHA ou pedido de documento  -> para (needs_human)
  - campos já bloqueados (candidatura anterior)                 -> para (already_applied)
  - pergunta sem resposta segura / sensível                     -> para (pending), sem salvar nada
  - dry_run: preenche, tira print e NÃO salva (as respostas da Gupy não podem ser editadas depois)
"""
import re
from collections import namedtuple

from .. import answers, approval

Outcome = namedtuple("Outcome", "status detail")
# status: sent | dry_run_ready | pending | already_applied | needs_human | error

MAX_PASSOS = 15
ESPERAS_CARREGANDO = 4
TELAS_CONHECIDAS = ("candidatura finalizada", "voce ja se candidatou", "vamos continuar sua candidatura",
                    "dados adicionais", "responder agora", "apresente-se")
RE_CAPTCHA = re.compile(r"captcha|nao sou um robo|verifique que voce e humano|verify you are human|cloudflare", re.I)


def apply_url(job):
    """https://<empresa>.gupy.io/candidates/jobs/<id>/apply  (o id da vaga é o do nosso registro 'gupy:<id>')."""
    host = re.match(r"https?://([^/]+)", job["url"])
    jid = job["id"].split(":", 1)[1]
    if not host or not jid.isdigit():
        raise ValueError(f"vaga sem host/id válidos: {job['url']} / {job['id']}")
    return f"https://{host.group(1)}/candidates/jobs/{jid}/apply"


def run_application(driver, con, job, dry_run=True, cfg=None, shot=None):
    """Executa UMA candidatura. `job`: linha do banco (sqlite3.Row ou dict). Nunca levanta por tela estranha."""
    cfg = cfg or answers.load()
    formularios = []  # assinaturas dos formulários já salvos: se o mesmo reaparecer, algo falhou (validação)
    try:
        driver.goto(apply_url(job))
        for _ in range(MAX_PASSOS):
            texto = answers.norm(driver.page_text())
            if driver.precisa_login():
                return _parar(driver, shot, "needs_human", "LOGIN: sessão da Gupy expirada (rode --login)")
            if driver.has_captcha() or RE_CAPTCHA.search(texto):
                return _parar(driver, shot, "needs_human", "CAPTCHA/verificação humana")
            if "candidatura finalizada" in texto:
                return Outcome("sent", "Gupy mostrou 'Candidatura finalizada'")
            if "voce ja se candidatou" in texto:
                return Outcome("already_applied", "Gupy informa candidatura anterior")

            if "vamos continuar sua candidatura" in texto:
                _clicar(driver, "Continuar", shot)
            elif "dados adicionais" in texto:
                driver.set_additional_no()
                _clicar(driver, "Salvar e continuar", shot)
            elif "responder agora" in texto:
                _clicar(driver, "Responder agora", shot)
            elif "apresente-se" in texto:
                if dry_run:
                    return Outcome("dry_run_ready", "tudo salvo até o modal final; não finalizei (dry-run)")
                _clicar(driver, "Finalizar candidatura", shot)
            else:
                fim = _formulario(driver, con, job, dry_run, cfg, shot, formularios)
                if fim:
                    return fim
        return _parar(driver, shot, "needs_human", f"mais de {MAX_PASSOS} passos sem concluir")
    except Exception as e:  # noqa: BLE001 - o runner decide o que fazer; aqui só registramos
        return Outcome("error", f"{type(e).__name__}: {e}")


def _clicar(driver, rotulo, shot):
    if not driver.click_button(rotulo):
        raise RuntimeError(f"botão '{rotulo}' não encontrado")
    driver.wait_idle()


def _parar(driver, shot, status, detalhe):
    _print(driver, shot)
    return Outcome(status, detalhe)


def _print(driver, shot):
    """Print é evidência, não etapa: se falhar (pasta virtualizada do Windows etc.), a candidatura segue."""
    if not shot:
        return
    try:
        driver.screenshot(shot)
    except OSError:
        pass


def _formulario(driver, con, job, dry_run, cfg, shot, formularios):
    """Tela de perguntas (ou tela desconhecida). Devolve Outcome para encerrar, ou None para seguir."""
    campos = driver.read_questions()
    for _ in range(ESPERAS_CARREGANDO):  # SPA: a tela pode ser só um spinner por alguns segundos
        if campos:
            break
        driver.wait_idle(2500)
        texto = answers.norm(driver.page_text())
        if any(m in texto for m in TELAS_CONHECIDAS):
            return None  # carregou numa tela de botões: o laço principal trata
        campos = driver.read_questions()
    if not campos:
        return _parar(driver, shot, "needs_human", "tela desconhecida (sem botões nem perguntas mapeadas)")
    if any(c["locked"] for c in campos):
        return Outcome("already_applied", "campos bloqueados: as perguntas já foram respondidas antes")
    assinatura = tuple(c["key"] for c in campos)
    if assinatura in formularios:
        return _parar(driver, shot, "needs_human", "o mesmo formulário reapareceu após salvar (erro de validação?)")
    formularios.append(assinatura)

    qs = [answers.Question(c["text"], c["options"]) for c in campos]
    res, completo = approval.prepare_questions(con, job, qs, cfg)
    if not completo:
        faltam = [f"{q.text[:45]} ({r.kind})" for q, r in zip(qs, res) if r.kind != "answer"]
        return _parar(driver, shot, "pending", "falta resposta segura: " + "; ".join(faltam))

    for c, r in zip(campos, res):
        if not driver.fill(c["key"], c["kind"], r.value):
            return _parar(driver, shot, "needs_human", f"não consegui preencher: {c['text'][:45]}")
    if dry_run:
        _print(driver, shot)
        return Outcome("dry_run_ready", f"{len(campos)} pergunta(s) preenchida(s), nada salvo (dry-run)")
    _clicar(driver, "Salvar e continuar", shot)
    return None
