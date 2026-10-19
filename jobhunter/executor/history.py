"""Histórico de candidaturas da Gupy (https://portal.gupy.io/my/applications), para o sistema saber onde você JÁ aplicou.

Estrutura real (validada ao vivo): um <article> por candidatura com empresa, vaga, progresso "2/6" e o id da candidatura.
LIMITE CONHECIDO: a página mostrou 12 candidaturas e não listou algumas antigas (Zenvia, DOMO, Omie Jr.). O rodapé tem
botões 1/2/3, mas clicar neles não trouxe páginas novas. Por isso o histórico COMPLEMENTA o applied_log.csv, não o substitui.

  python -m jobhunter.executor.history      # lista o que a Gupy mostra e o que falta no seu log
"""
import re
import sys

from ..run import applied_companies, ja_aplicada

JS_LISTA = """() => [...document.querySelectorAll('article')].map(a => {
  const t = a.innerText.split('\\n').map(s => s.trim()).filter(Boolean); const j = t.join(' ');
  return {empresa: t[0] || '', vaga: t[1] || '', progresso: (j.match(/(\\d+\\/\\d+)/) || [])[1] || '',
          id: (j.match(/andamento da candidatura(\\d+)/) || [])[1] || ''};
})"""


def parse_rows(rows):
    """Normaliza as linhas cruas do navegador. Descarta cartões sem empresa/vaga."""
    out = []
    for r in rows:
        if not r.get("empresa") or not r.get("vaga"):
            continue
        feito, _, total = (r.get("progresso") or "").partition("/")
        out.append({"empresa": r["empresa"].replace("💙", "").strip(), "vaga": r["vaga"].strip(), "id": r.get("id", ""),
                    "etapa": int(feito) if feito.isdigit() else 0, "etapas": int(total) if total.isdigit() else 0})
    return out


def faltando_no_log(rows, nomes_no_log):
    """Candidaturas que a Gupy mostra e o log NÃO conhece (casa por palavras inteiras do nome da empresa)."""
    faltam = []
    for r in rows:
        if not ja_aplicada({"company": r["empresa"], "url": ""}, nomes_no_log):
            faltam.append(r)
    return faltam


def ler(driver):
    driver.goto("https://portal.gupy.io/my/applications")
    if driver.precisa_login():
        raise RuntimeError("sessão da Gupy expirada: rode python -m jobhunter.executor.driver_playwright --login")
    driver.page.wait_for_selector("article", timeout=20000)
    return parse_rows(driver.page.evaluate(JS_LISTA))


def main():
    from .driver_playwright import PlaywrightDriver
    d = PlaywrightDriver(headless=False)
    try:
        rows = ler(d)
    finally:
        d.close()
    log = applied_companies()
    print(f"A Gupy mostra {len(rows)} candidaturas.")
    for r in faltando_no_log(rows, log):
        print(f"  NÃO está no log: {r['empresa']} — {r['vaga']} ({r['etapa']}/{r['etapas']}) id {r['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
