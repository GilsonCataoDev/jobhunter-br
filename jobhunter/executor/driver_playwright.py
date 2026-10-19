"""Driver Playwright para a Gupy. Usa um perfil persistente: você faz login UMA vez numa janela real
(`python -m jobhunter.executor.driver_playwright --login`) e o robô reutiliza a sessão. Nenhuma senha é guardada em código.

Interface esperada pelo fluxo (flow.py): goto, page_text, has_captcha, click_button, set_additional_no,
read_questions, fill, wait_idle, screenshot.
"""
import os
import re
import sys
import time

JS = os.path.join(os.path.dirname(__file__), "gupy_dom.js")
PERFIL = os.environ.get("JOBHUNTER_PROFILE", os.path.join(os.path.expanduser("~"), ".jobhunter", "browser-profile"))


class PlaywrightDriver:
    def __init__(self, headless=False, profile=PERFIL):
        from playwright.sync_api import sync_playwright  # import tardio: o resto do projeto não exige Playwright
        os.makedirs(profile, exist_ok=True)
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(profile, headless=headless, locale="pt-BR",
                                                               viewport={"width": 1280, "height": 900})
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.set_default_timeout(20000)
        self._js = open(JS, encoding="utf-8").read()

    # --- navegação e leitura ---
    def goto(self, url):
        self.page.goto(url, wait_until="domcontentloaded")
        self.wait_idle()
        self.dispensar_cookies()

    def dispensar_cookies(self):
        """O banner de cookies das páginas de carreira é fixo e pode cobrir botões. Escolhe a opção mais privada
        ('Rejeitar Todos'). Não faz nada se não houver banner."""
        try:
            b = self.page.get_by_role("button", name=re.compile(r"^\s*(Rejeitar Todos|Rejeitar todos|Recusar todos)\s*$"))
            if b.count():
                b.first.click(timeout=3000)
                self.page.wait_for_timeout(500)
        except Exception:  # noqa: BLE001 - banner é opcional; nunca deve derrubar a candidatura
            pass

    def wait_idle(self, ms=1500):
        try:
            self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001 - páginas com polling nunca ficam "idle"; segue
            pass
        self.page.wait_for_timeout(ms)

    def page_text(self):
        return self.page.inner_text("body")

    def precisa_login(self):
        """A Gupy redireciona para login.gupy.io quando a sessão não existe ou expirou."""
        return "login.gupy.io" in self.page.url or "/signin" in self.page.url

    def persistir_cookies(self, dias=30):
        """Cookies de SESSÃO (sem validade) somem quando o navegador fecha. Reescreve-os com validade para ficarem
        gravados no perfil. Devolve quantos foram convertidos."""
        n = 0
        for c in self.ctx.cookies():
            if c.get("expires", -1) in (-1, 0, None):
                c = dict(c, expires=time.time() + dias * 86400)
                self.ctx.add_cookies([c])
                n += 1
        return n

    def has_captcha(self):
        if any(re.search(r"captcha|challenge", f.url, re.I) for f in self.page.frames):
            return True
        return self.page.locator("iframe[src*='captcha'], iframe[title*='captcha' i]").count() > 0

    def screenshot(self, path):
        # o Python grava o arquivo: o processo do navegador pode não enxergar pastas virtualizadas do Windows
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(self.page.screenshot(full_page=True))

    # --- ações ---
    def click_button(self, rotulo):
        # nome EXATO: "Continuar" não pode casar com "Continuar com Google" etc.
        loc = self.page.get_by_role("button", name=re.compile(r"^\s*" + re.escape(rotulo) + r"\s*$", re.I))
        if loc.count() == 0:
            return False
        loc.first.click()
        return True

    def set_additional_no(self):
        """Tela 'Dados adicionais': garante 'Não' em 'indicado por funcionário' e 'trabalha na empresa'."""
        self.page.evaluate("document.querySelectorAll('input[type=radio][value=no]').forEach(e => { if(!e.checked) e.click(); })")

    def read_questions(self):
        self.page.evaluate(self._js)
        return self.page.evaluate("window.__jh.read()")

    def fill(self, key, kind, value):
        """Preenche UM campo. Devolve False se não achou o campo/opção (o fluxo então para)."""
        self.page.evaluate(self._js)
        if self.page.evaluate("([k, t, v]) => window.__jh.mark(k, t, v)", [key, kind, value]) != 1:
            return False
        alvo = self.page.locator("[data-jh=target]")
        if kind == "text":
            alvo.fill(str(value))
        elif kind == "select":
            alvo.select_option(label=str(value))
        else:  # radio/checkbox: clicar o <label> (o input costuma ser estilizado/oculto)
            alvo.locator("xpath=ancestor::label").click()
        return True

    def close(self):
        self.ctx.close()
        self._pw.stop()


def login():
    """Abre a Gupy numa janela real para VOCÊ entrar. Enquanto a janela está aberta, grava os cookies com validade.
    Quando aparecer 'Minhas candidaturas', aguarde alguns segundos e feche a janela."""
    d = PlaywrightDriver(headless=False)
    d.goto("https://portal.gupy.io/my/applications")
    print("Entre na sua conta Gupy nesta janela. Quando ver 'Minhas candidaturas', aguarde ~10 s e feche a janela.")
    try:
        while True:  # a cada 3 s: se já está logado, persiste os cookies de sessão; sai quando a janela fechar
            d.page.wait_for_timeout(3000)
            if not d.precisa_login():
                d.persistir_cookies()
    except Exception:  # noqa: BLE001 - janela fechada pelo usuário
        pass
    finally:
        try:
            d.close()
        except Exception:  # noqa: BLE001
            pass
        print("Sessão gravada em", PERFIL)


if __name__ == "__main__":
    if "--login" in sys.argv:
        login()
    else:
        print(__doc__)
