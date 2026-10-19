"""Bot do Telegram por long polling (sem dependência extra: só `requests`).

Configure: TELEGRAM_BOT_TOKEN (do @BotFather) e TELEGRAM_CHAT_ID (seu chat). Só esse chat é atendido.
Comandos: /fila  /pendencias  /r <id> <resposta>  /feito <id>  /aprovadas  /ajuda
Rodar:   python -m jobhunter.bot
"""
import os
import sys
import time

import requests

from . import approval, db

AJUDA = ("Comandos:\n/fila – mostra vagas novas para aprovar\n/pendencias – perguntas que preciso de você\n"
         "/r <id> <resposta> – responde uma pendência\n/feito <id> – você preencheu um dado sensível\n"
         "/aprovadas – vagas aprovadas")


class TelegramAPI:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}"

    def call(self, method, **params):
        r = requests.post(f"{self.base}/{method}", json=params, timeout=40)
        r.raise_for_status()
        return r.json()


class Bot:
    def __init__(self, api, con, chat_id):
        self.api, self.con, self.chat_id = api, con, str(chat_id)

    def send(self, text, markup=None):
        for i in range(0, max(len(text), 1), 3900):  # limite do Telegram: 4096
            params = {"chat_id": self.chat_id, "text": text[i:i + 3900], "disable_web_page_preview": True}
            if markup and i + 3900 >= len(text):
                params["reply_markup"] = markup
            self.api.call("sendMessage", **params)

    def process_update(self, upd):
        """Trata UMA atualização. Ignora qualquer chat que não seja o autorizado."""
        cb = upd.get("callback_query")
        msg = upd.get("message") or {}
        chat = str((cb["message"]["chat"]["id"]) if cb else (msg.get("chat") or {}).get("id", ""))
        if chat != self.chat_id:
            return
        if cb:
            self.api.call("answerCallbackQuery", callback_query_id=cb["id"])
            self.send(approval.on_callback(self.con, cb.get("data", "")))
            return
        self.on_message((msg.get("text") or "").strip())

    def on_message(self, text):
        cmd, _, resto = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        if cmd in ("/start", "/ajuda", "/help"):
            self.send(AJUDA)
        elif cmd == "/fila":
            itens = approval.offer_next(self.con)
            self.con.commit()
            if not itens:
                self.send("Nenhuma vaga nova na fila.")
            for texto, teclado in itens:
                self.send(texto, teclado)
        elif cmd == "/pendencias":
            self.send(approval.pendencias_text(self.con))
        elif cmd == "/r":
            pid, _, resposta = resto.strip().partition(" ")
            if not pid.isdigit() or not resposta.strip():
                self.send("Uso: /r <id> <resposta>")
            else:
                self.send(approval.on_answer(self.con, int(pid), resposta.strip()))
        elif cmd == "/feito":
            pid = resto.strip()
            self.send(approval.on_done(self.con, int(pid)) if pid.isdigit() else "Uso: /feito <id>")
        elif cmd == "/aprovadas":
            rows = db.jobs_with_status(self.con, "approved")
            self.send("\n".join(f"• {r['title']} — {r['company']}" for r in rows) or "Nenhuma aprovada ainda.")
        else:
            self.send("Não entendi. /ajuda")

    def run(self, poll=30):
        offset = 0
        print("[bot] ouvindo…")
        while True:
            try:
                resp = self.api.call("getUpdates", offset=offset, timeout=poll, allowed_updates=["message", "callback_query"])
                for upd in resp.get("result", []):
                    offset = upd["update_id"] + 1
                    try:
                        self.process_update(upd)
                    except Exception as e:  # noqa: BLE001 - um erro em um comando não derruba o bot
                        print("[bot] erro no update:", e, file=sys.stderr)
            except requests.RequestException as e:
                print("[bot] rede:", e, file=sys.stderr)
                time.sleep(5)


def main():
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        sys.exit("Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.")
    Bot(TelegramAPI(token), db.connect(), chat).run()


if __name__ == "__main__":
    main()
