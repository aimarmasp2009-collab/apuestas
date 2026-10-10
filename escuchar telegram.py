#!/usr/bin/env python3
"""
=============================================================
  ESCUCHAR TELEGRAM — Lanza el análisis cuando se lo pides
  Escribe /picks a tu bot desde el móvil y recibirás el informe.
  Revisa Telegram UNA vez y termina (pensado para GitHub Actions).
=============================================================
"""

import sys

import requests

import value_betting_analyzer as vba

COMANDOS_ANALISIS = {"/picks", "picks", "/apuestas", "apuestas", "/analisis", "analisis", "análisis"}
COMANDOS_AYUDA    = {"/start", "/ayuda", "ayuda", "/help"}


def api(method: str, **params) -> dict:
    r = requests.post(
        f"https://api.telegram.org/bot{vba.TELEGRAM_TOKEN}/{method}",
        json=params, timeout=20,
    )
    return r.json()


def responder(texto: str) -> None:
    try:
        api("sendMessage", chat_id=vba.TELEGRAM_CHAT_ID, text=texto)
    except Exception as e:
        print(f"No se pudo responder: {e}")


def main() -> None:
    if not vba.TELEGRAM_TOKEN or not vba.TELEGRAM_CHAT_ID:
        print("❌ Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")
        sys.exit(1)

    data = api("getUpdates", timeout=0)
    if not data.get("ok"):
        print(f"❌ Telegram respondió con error: {str(data)[:200]}")
        sys.exit(1)

    updates = data.get("result", [])
    if not updates:
        print("Sin mensajes nuevos.")
        return

    # Confirma todos los mensajes leídos para no procesarlos dos veces
    api("getUpdates", offset=updates[-1]["update_id"] + 1, timeout=0)

    autorizado = str(vba.TELEGRAM_CHAT_ID)
    pedir_analisis = False
    pedir_ayuda = False
    for upd in updates:
        msg = upd.get("message")
        if not msg or "text" not in msg:
            continue
        if str(msg["chat"]["id"]) != autorizado:
            continue                      # solo obedece a tu chat
        texto = msg["text"].strip().lower().split("@")[0]
        if texto in COMANDOS_ANALISIS:
            pedir_analisis = True
        elif texto in COMANDOS_AYUDA:
            pedir_ayuda = True

    if pedir_analisis:
        print("Análisis pedido desde Telegram")
        responder("🔎 Analizando partidos, en un minuto tienes el informe...")
        vba.main()
    elif pedir_ayuda:
        responder("Escríbeme /picks y te mando el análisis de apuestas con valor. "
                  "Puede tardar unos minutos en empezar. Además lo recibes solo cada día a las 9:00.")
    else:
        print("Mensajes recibidos, ninguno es un comando.")


if __name__ == "__main__":
    main()
