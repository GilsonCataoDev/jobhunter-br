"""Resumo diário. Telegram se TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID existirem; senão só imprime."""
import os

import requests

TIER = {1: "TI/Suporte/QA", 2: "Administrativo", 3: "Atendimento"}
LIMITE_TELEGRAM = 4000  # a API aceita 4096 caracteres por mensagem


def format_summary(rows, stats):
    linhas = [f"Vagas novas que passaram: {len(rows)}",
              f"Coletadas {stats['coletadas']} | novas {stats['novas']} | rejeitadas {stats['rejeitadas']}"]
    for tier in (1, 2, 3):
        grupo = [r for r in rows if r["tier"] == tier]
        if not grupo:
            continue
        linhas.append(f"\n{TIER[tier]}")
        for r in grupo:
            aviso = f"\n   ⚠ {r['warnings']}" if r["warnings"] else ""
            linhas.append(f"• {r['title']} — {r['company']} ({r['kind']}){aviso}\n  {r['url']}")
    if stats.get("erros"):
        linhas.append("\nFalhas na coleta: " + " | ".join(stats["erros"][:5]))
    return "\n".join(linhas)


def chunks(texto, tamanho=LIMITE_TELEGRAM):
    """Quebra em mensagens menores, sempre em quebra de linha."""
    partes, atual = [], ""
    for ln in texto.split("\n"):
        if len(atual) + len(ln) + 1 > tamanho and atual:
            partes.append(atual)
            atual = ""
        atual += ln[:tamanho] + "\n"
    if atual.strip():
        partes.append(atual)
    return partes


def send(texto):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print(texto)
        print("\n[notify] Telegram não configurado: resumo impresso acima.")
        return False
    for parte in chunks(texto):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": parte, "disable_web_page_preview": True}, timeout=20)
        r.raise_for_status()
    return True
