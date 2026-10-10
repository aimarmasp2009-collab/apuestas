#!/usr/bin/env python3
"""
=============================================================
  VALUE BETTING ANALYZER — Análisis diario de apuestas con valor
  Mercados: 1X2 · Over/Under · Hándicap · Córners · Tarjetas
  Ligas: Premier League · La Liga · Serie A · Bundesliga · UCL · UEL · Brasileirão
  Envío: Telegram Bot
=============================================================
"""

import requests
import json
import math
import os
import sys
import time
from datetime import date, datetime, timezone

# ─────────────────────────────────────────────
#  CONFIGURACIÓN — rellena estos 4 valores
# ─────────────────────────────────────────────
# Si existen como variables de entorno (por ejemplo, en GitHub Actions) se usan
# esas; si no, se usan los valores que escribas aquí entre las comillas.
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN")    or ""   # ← Tu token de Telegram (@BotFather)
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID")  or ""   # ← Tu Chat ID (ejecuta setup.py para obtenerlo)
FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY") or ""   # ← Tu API Key de football-data.org (gratis)
ODDS_API_KEY      = os.environ.get("ODDS_API_KEY")      or ""   # ← Tu API Key de the-odds-api.com (gratis)

# ─────────────────────────────────────────────
#  LIGAS A ANALIZAR
# ─────────────────────────────────────────────
LEAGUES_ODDS_API = [
    "soccer_england_premier_league",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_brazil_campeonato",     # Brasileirão Série A
]

# Casa de referencia (la más afilada del mercado, mínimo margen)
SHARP_BOOK = "pinnacle"

# Casas en las que buscar valor — todas las disponibles en región EU según diagnóstico
# El sistema mostrará la que tenga MAYOR EV en cada selección
VALUE_BOOKS = [
    "betfair_ex_eu",   # Betfair Exchange EU (suele tener las mejores cuotas)
    "williamhill",     # William Hill
    "unibet_fr",       # Unibet (versión EU)
    "unibet_nl",
    "unibet_se",
    "betsson",         # Betsson
    "marathonbet",     # Marathonbet
    "nordicbet",       # NordicBet
    "codere_it",       # Codere (disponible en España como Codere.es)
    "tipico_de",       # Tipico
    "matchbook",       # Matchbook Exchange
    "leovegas_se",     # LeoVegas
    "sport888",        # 888sport
    "betonlineag",     # BetOnline
    "coolbet",         # Coolbet
    "betclic_fr",      # Betclic
    "suprabets",       # Suprabets
    "everygame",       # Everygame
    "onexbet",         # 1xBet
    "winamax_fr",      # Winamax
    "gtbets",          # GTbets
    "bet365",          # Bet365 (ver nota: The Odds API NO lo ofrece para fútbol en región EU,
                       #  así que de momento no devolverá cuotas; queda preparado por si lo añaden)
]

# ─────────────────────────────────────────────
#  MERCADOS EXTRA: CÓRNERS Y TARJETAS
# ─────────────────────────────────────────────
# Cada mercado extra se pide partido a partido y gasta créditos de The Odds API
# (1 crédito por mercado y partido). El plan gratuito tiene 500 créditos/mes.
ENABLE_EXTRA_MARKETS   = True   # Pon False para desactivar córners y tarjetas
MIN_CREDITS_FOR_EXTRAS = 100    # Si quedan menos créditos que esto, se omiten los extras

# clave API  ->  (etiqueta del mercado, nombre en el pick)
EXTRA_TOTALS_MARKETS = {
    "alternate_totals_corners": ("Córners",   "córners"),
    "alternate_totals_cards":   ("Tarjetas",  "tarjetas"),
}

# Mínimo EV para mencionar una apuesta en el informe (0 = cualquier valor positivo)
MIN_EV = 0.00


# ─────────────────────────────────────────────
#  FUNCIONES MATEMÁTICAS
# ─────────────────────────────────────────────

def remove_vig(decimal_odds_list: list[float]) -> list[float]:
    """Elimina el margen del bookmaker para obtener probabilidades reales."""
    implied = [1 / o for o in decimal_odds_list if o > 1]
    if len(implied) != len(decimal_odds_list):
        return []
    total = sum(implied)
    return [p / total for p in implied]


def ev(true_prob: float, decimal_odds: float) -> float:
    """Valor esperado: (P_real × cuota_decimal) - 1"""
    return (true_prob * decimal_odds) - 1


# ─────────────────────────────────────────────
#  OBTENCIÓN DE DATOS
# ─────────────────────────────────────────────

CREDITS_REMAINING = None   # se actualiza con la cabecera x-requests-remaining


def _update_credits(resp) -> None:
    """Guarda los créditos restantes de The Odds API según la respuesta."""
    global CREDITS_REMAINING
    try:
        CREDITS_REMAINING = int(float(resp.headers.get("x-requests-remaining")))
    except (TypeError, ValueError):
        pass


def get_odds_for_league(league_key: str) -> list[dict]:
    """
    Descarga cuotas de The-Odds-API para los 3 mercados en una sola llamada por liga.
    Devuelve lista de partidos con sus cuotas por casa de apuestas.
    """
    url = f"https://api.the-odds-api.com/v4/sports/{league_key}/odds/"
    today = date.today().isoformat()
    params = {
        "apiKey":      ODDS_API_KEY,
        "regions":     "eu",
        "markets":     "h2h,totals,spreads",
        "oddsFormat":  "decimal",
        "dateFormat":  "iso",
        # Solo partidos de hoy: si no hay ninguno, la petición no consume créditos
        "commenceTimeFrom": f"{today}T00:00:00Z",
        "commenceTimeTo":   f"{today}T23:59:59Z",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            _update_credits(r)
            remaining = r.headers.get("x-requests-remaining", "?")
            games = r.json()
            print(f"  ✓ {league_key} — {len(games)} partidos en API  (peticiones restantes: {remaining})")
            return games
        elif r.status_code in (404, 422):
            # 422: no hay partidos próximos · 404: liga sin actividad (parón, fuera de temporada)
            print(f"  · {league_key} — sin partidos hoy")
            return []
        else:
            print(f"  ✗ {league_key} — error {r.status_code}")
            return []
    except Exception as e:
        print(f"  ✗ {league_key} — {e}")
        return []


# ─────────────────────────────────────────────
#  ANÁLISIS DE VALOR
# ─────────────────────────────────────────────

def analyze_match(game: dict) -> list[dict]:
    """
    Para un partido concreto, calcula el EV de cada selección
    usando Pinnacle como referencia de probabilidades reales.
    Devuelve lista de apuestas con valor positivo (EV > MIN_EV).
    """
    bm_map = {bm["key"]: bm for bm in game.get("bookmakers", [])}

    if SHARP_BOOK not in bm_map:
        return []   # Sin Pinnacle no podemos calcular probabilidades fiables

    pin = bm_map[SHARP_BOOK]
    pin_markets = {mkt["key"]: mkt["outcomes"] for mkt in pin.get("markets", [])}

    value_bets = []

    # ── 1X2 ────────────────────────────────
    if "h2h" in pin_markets:
        outcomes = pin_markets["h2h"]
        home_name = game["home_team"]
        away_name = game["away_team"]
        order = [home_name, "Draw", away_name]
        pin_odds = {o["name"]: o["price"] for o in outcomes}

        if all(k in pin_odds for k in order):
            fair_probs = remove_vig([pin_odds[k] for k in order])
            if fair_probs:
                for book_key in VALUE_BOOKS:
                    if book_key not in bm_map:
                        continue
                    bm_mkts = {m["key"]: m["outcomes"] for m in bm_map[book_key].get("markets", [])}
                    if "h2h" not in bm_mkts:
                        continue
                    bm_odds = {o["name"]: o["price"] for o in bm_mkts["h2h"]}
                    for i, sel in enumerate(order):
                        if sel in bm_odds:
                            ev_val = ev(fair_probs[i], bm_odds[sel])
                            if ev_val > MIN_EV:
                                label = "Local" if sel == home_name else ("Empate" if sel == "Draw" else "Visitante")
                                value_bets.append({
                                    "market":    "1X2",
                                    "selection": f"{label} ({sel})",
                                    "bookmaker": book_key,
                                    "odds":      bm_odds[sel],
                                    "fair_prob": fair_probs[i],
                                    "ev":        ev_val,
                                    "pin_odds":  pin_odds[sel],
                                })

    # ── OVER / UNDER ───────────────────────
    if "totals" in pin_markets:
        # Agrupa por línea (ej: 2.5, 1.5, 3.5)
        pin_lines: dict[float, dict] = {}
        for o in pin_markets["totals"]:
            line = o.get("point", 2.5)
            pin_lines.setdefault(line, {})[o["name"]] = o["price"]

        for line, sides in pin_lines.items():
            if "Over" not in sides or "Under" not in sides:
                continue
            fair_probs = remove_vig([sides["Over"], sides["Under"]])
            if not fair_probs:
                continue
            fair_over, fair_under = fair_probs

            for book_key in VALUE_BOOKS:
                if book_key not in bm_map:
                    continue
                bm_mkts = {m["key"]: m["outcomes"] for m in bm_map[book_key].get("markets", [])}
                if "totals" not in bm_mkts:
                    continue
                bm_lines: dict[float, dict] = {}
                for o in bm_mkts["totals"]:
                    l = o.get("point", 2.5)
                    bm_lines.setdefault(l, {})[o["name"]] = o["price"]

                if line not in bm_lines:
                    continue
                for name, fair_p in [("Over", fair_over), ("Under", fair_under)]:
                    if name in bm_lines[line]:
                        ev_val = ev(fair_p, bm_lines[line][name])
                        if ev_val > MIN_EV:
                            value_bets.append({
                                "market":    f"O/U {line}",
                                "selection": f"{name} {line}",
                                "bookmaker": book_key,
                                "odds":      bm_lines[line][name],
                                "fair_prob": fair_p,
                                "ev":        ev_val,
                                "pin_odds":  sides[name],
                            })

    # ── HÁNDICAP ASIÁTICO (spreads) ────────────
    if "spreads" in pin_markets:
        # Agrupa por línea: { -0.5: {"Home": 1.92, "Away": 1.99}, ... }
        pin_spreads: dict[float, dict] = {}
        for o in pin_markets["spreads"]:
            line = o.get("point", 0)
            pin_spreads.setdefault(line, {})[o["name"]] = o["price"]

        for line, sides in pin_spreads.items():
            home_name = game["home_team"]
            away_name = game["away_team"]
            if home_name not in sides or away_name not in sides:
                continue
            fair_probs = remove_vig([sides[home_name], sides[away_name]])
            if not fair_probs:
                continue
            fair_home_h, fair_away_h = fair_probs

            for book_key in VALUE_BOOKS:
                if book_key not in bm_map:
                    continue
                bm_mkts = {m["key"]: m["outcomes"] for m in bm_map[book_key].get("markets", [])}
                if "spreads" not in bm_mkts:
                    continue
                bm_spreads: dict[float, dict] = {}
                for o in bm_mkts["spreads"]:
                    l = o.get("point", 0)
                    bm_spreads.setdefault(l, {})[o["name"]] = o["price"]

                if line not in bm_spreads:
                    continue
                sign = f"+{line}" if line > 0 else str(line)
                for name, fair_p in [(home_name, fair_home_h), (away_name, fair_away_h)]:
                    if name in bm_spreads[line]:
                        bm_odd = bm_spreads[line][name]
                        ev_val = ev(fair_p, bm_odd)
                        if ev_val > MIN_EV:
                            label = f"{'Local' if name == home_name else 'Visitante'} ({sign})"
                            value_bets.append({
                                "market":    f"Hándicap {sign}",
                                "selection": label,
                                "bookmaker": book_key,
                                "odds":      bm_odd,
                                "fair_prob": fair_p,
                                "ev":        ev_val,
                                "pin_odds":  sides[name],
                            })

    # BTTS: no disponible en el plan gratuito de The Odds-API

    return dedupe_bets(value_bets)


def dedupe_bets(value_bets: list[dict]) -> list[dict]:
    """Agrupa por selección: guarda la de mayor EV y añade lista de todas las casas con valor."""
    seen: dict[str, dict] = {}
    all_books_with_value: dict[str, list] = {}
    for bet in value_bets:
        key = f"{bet['market']}|{bet['selection']}"
        book_label = BOOK_NAMES_INLINE.get(bet["bookmaker"], bet["bookmaker"])
        all_books_with_value.setdefault(key, []).append(
            f"{book_label} {bet['odds']:.2f}"
        )
        if key not in seen or bet["ev"] > seen[key]["ev"]:
            seen[key] = bet

    for key, best in seen.items():
        best["all_books"] = all_books_with_value.get(key, [])

    return sorted(seen.values(), key=lambda x: x["ev"], reverse=True)


# ─────────────────────────────────────────────
#  CÓRNERS Y TARJETAS (petición por partido)
# ─────────────────────────────────────────────

def get_event_extra_odds(league_key: str, event_id: str):
    """Descarga córners y tarjetas de UN partido (endpoint /events/{id}/odds)."""
    global ENABLE_EXTRA_MARKETS
    url = f"https://api.the-odds-api.com/v4/sports/{league_key}/events/{event_id}/odds"
    params = {
        "apiKey":     ODDS_API_KEY,
        "regions":    "eu",
        "markets":    ",".join(EXTRA_TOTALS_MARKETS.keys()),
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
    except Exception as e:
        print(f"    ✗ córners/tarjetas — {e}")
        return None

    _update_credits(r)
    if r.status_code == 200:
        return r.json()
    if r.status_code in (401, 403):
        print("    ✗ Tu plan de The Odds API no permite córners/tarjetas → desactivados")
        ENABLE_EXTRA_MARKETS = False
    elif r.status_code == 429:
        print("    ✗ Límite de velocidad de la API (429) — se omite este partido")
    elif r.status_code not in (404, 422):
        print(f"    ✗ córners/tarjetas — error {r.status_code}")
    return None


def analyze_extra_markets(event: dict) -> list[dict]:
    """
    Calcula el EV de córners y tarjetas (Over/Under) usando Pinnacle como referencia.
    Solo usa líneas con .5 (sin devolución de apuesta) para no falsear la probabilidad.
    """
    bm_map = {bm["key"]: bm for bm in event.get("bookmakers", [])}
    if SHARP_BOOK not in bm_map:
        return []

    pin_markets = {m["key"]: m["outcomes"] for m in bm_map[SHARP_BOOK].get("markets", [])}
    value_bets = []

    for mkt_key, (label, noun) in EXTRA_TOTALS_MARKETS.items():
        if mkt_key not in pin_markets:
            continue

        pin_lines: dict[float, dict] = {}
        for o in pin_markets[mkt_key]:
            if "point" not in o:
                continue
            pin_lines.setdefault(o["point"], {})[o["name"]] = o["price"]

        for line, sides in pin_lines.items():
            if line % 1 != 0.5:
                continue
            if "Over" not in sides or "Under" not in sides:
                continue
            fair_probs = remove_vig([sides["Over"], sides["Under"]])
            if not fair_probs:
                continue
            fair_over, fair_under = fair_probs

            for book_key in VALUE_BOOKS:
                if book_key not in bm_map:
                    continue
                bm_mkts = {m["key"]: m["outcomes"] for m in bm_map[book_key].get("markets", [])}
                if mkt_key not in bm_mkts:
                    continue
                bm_lines: dict[float, dict] = {}
                for o in bm_mkts[mkt_key]:
                    if "point" in o:
                        bm_lines.setdefault(o["point"], {})[o["name"]] = o["price"]

                if line not in bm_lines:
                    continue
                for name, fair_p in (("Over", fair_over), ("Under", fair_under)):
                    if name in bm_lines[line]:
                        ev_val = ev(fair_p, bm_lines[line][name])
                        if ev_val > MIN_EV:
                            value_bets.append({
                                "market":    f"{label} {line}",
                                "selection": f"{name} {line} {noun}",
                                "bookmaker": book_key,
                                "odds":      bm_lines[line][name],
                                "fair_prob": fair_p,
                                "ev":        ev_val,
                                "pin_odds":  sides[name],
                            })

    return dedupe_bets(value_bets)


# Nombres cortos para uso interno en analyze_match (antes de definir BOOK_NAMES)
BOOK_NAMES_INLINE = {
    "betfair_ex_eu": "Betfair", "williamhill": "WilliamHill",
    "unibet_fr": "Unibet", "unibet_nl": "Unibet", "unibet_se": "Unibet",
    "betsson": "Betsson", "marathonbet": "Marathonbet", "nordicbet": "NordicBet",
    "codere_it": "Codere", "tipico_de": "Tipico", "matchbook": "Matchbook",
    "leovegas_se": "LeoVegas", "sport888": "888sport", "betonlineag": "BetOnline",
    "coolbet": "Coolbet", "betclic_fr": "Betclic", "suprabets": "Suprabets",
    "everygame": "Everygame", "onexbet": "1xBet", "winamax_fr": "Winamax",
    "gtbets": "GTbets", "pmu_fr": "PMU", "bet365": "Bet365",
}


# ─────────────────────────────────────────────
#  FORMATO DEL MENSAJE TELEGRAM
# ─────────────────────────────────────────────

BOOK_NAMES = {
    "betfair_ex_eu": "Betfair Exchange",
    "williamhill":   "William Hill",
    "unibet_fr":     "Unibet",
    "unibet_nl":     "Unibet",
    "unibet_se":     "Unibet",
    "betsson":       "Betsson",
    "marathonbet":   "Marathonbet",
    "nordicbet":     "NordicBet",
    "codere_it":     "Codere",
    "tipico_de":     "Tipico",
    "matchbook":     "Matchbook",
    "leovegas_se":   "LeoVegas",
    "sport888":      "888sport",
    "betonlineag":   "BetOnline",
    "coolbet":       "Coolbet",
    "betclic_fr":    "Betclic",
    "suprabets":     "Suprabets",
    "everygame":     "Everygame",
    "onexbet":       "1xBet",
    "winamax_fr":    "Winamax",
    "gtbets":        "GTbets",
    "pinnacle":      "Pinnacle",
    "pmu_fr":        "PMU",
    "bet365":        "Bet365",
}

LEAGUE_ORDER = [
    "Champions League", "Europa League",
    "Premier League", "La Liga", "Serie A", "Bundesliga", "Brasileirão",
]

LEAGUE_FLAGS = {
    "Champions League": "⭐",
    "Europa League":    "🟠",
    "Premier League":   "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "La Liga":          "🇪🇸",
    "Serie A":          "🇮🇹",
    "Bundesliga":       "🇩🇪",
    "Brasileirão":      "🇧🇷",
}

def build_message(all_results: list[tuple], markets_used: list[str]) -> str:
    today = date.today().strftime("%d/%m/%Y")

    def h(t: str) -> str:
        return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def market_category(market: str) -> str:
        """Agrupa variantes del mismo mercado para deduplicar por partido."""
        if market == "1X2":          return "1X2"
        if market.startswith("O/U"): return "O/U"
        if "ndicap" in market:       return "Hándicap"
        if market.startswith("Córners"):   return "Córners"
        if market.startswith("Tarjetas"):  return "Tarjetas"
        return market

    # ── Agrupa por liga → partido, queda solo el mejor EV por categoría ──
    no_value = [g for g, b in all_results if b is not None and not b]
    leagues: dict[str, list] = {}

    for game, bets in all_results:
        if not bets:
            continue
        best: dict[str, dict] = {}
        for bet in bets:
            cat = market_category(bet["market"])
            if cat not in best or bet["ev"] > best[cat]["ev"]:
                best[cat] = bet
        picks = sorted(best.values(), key=lambda x: x["ev"], reverse=True)
        leagues.setdefault(game["competition"], []).append((game, picks))

    total_analyzed = sum(1 for _, b in all_results if b is not None)
    total_picks    = sum(len(p) for ms in leagues.values() for _, p in ms)
    markets_str    = " · ".join(markets_used)

    # ── Cabecera ─────────────────────────────────────────────────────────
    msg  = f"<b>ANÁLISIS · {today}</b>\n"
    msg += f"<i>{total_analyzed} partidos revisados · {markets_str}</i>\n"
    msg += f"─────────────────────────\n\n"

    if total_picks == 0:
        msg += "<b>Sin valor hoy</b>\n"
        msg += "<i>Ningún mercado supera las probabilidades de Pinnacle.</i>\n\n"
    else:
        msg += f"<b>{total_picks} pick{'s' if total_picks > 1 else ''} con EV positivo</b>\n\n"

        sorted_comps = sorted(
            leagues.keys(),
            key=lambda c: (LEAGUE_ORDER.index(c) if c in LEAGUE_ORDER else 99, c)
        )

        for comp in sorted_comps:
            flag = LEAGUE_FLAGS.get(comp, "🏆")
            msg += f"{flag} <b>{h(comp)}</b>\n"
            for game, picks in leagues[comp]:
                msg += f"{h(game['home'])} vs {h(game['away'])}\n"
                for bet in picks:
                    ev_pct = bet["ev"] * 100
                    msg += (
                        f"  {h(bet['selection'])} · "
                        f"Cuota mín <code>{bet['pin_odds']:.2f}</code> · "
                        f"EV <b>+{ev_pct:.1f}%</b>\n"
                    )
                msg += "\n"

    # ── Partidos sin valor ────────────────────────────────────────────────
    if no_value:
        msg += "─────────────────────────\n"
        msg += f"<i>Sin valor ({len(no_value)}): "
        msg += ", ".join(f"{h(g['home'])} vs {h(g['away'])}" for g in no_value[:6])
        if len(no_value) > 6:
            msg += f" y {len(no_value) - 6} más"
        msg += "</i>\n\n"

    msg += "<i>Cuota mín = probabilidad real Pinnacle sin margen. "
    msg += "Si Retabet/Kirolbet/Bet365 ofrecen más → hay valor.</i>"

    return msg


# ─────────────────────────────────────────────
#  ENVÍO TELEGRAM
# ─────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, json=data, timeout=15)
        if r.status_code == 200:
            return True
        else:
            print(f"  ✗ Telegram error {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        print(f"  ✗ Telegram exception: {e}")
        return False


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    if not TELEGRAM_CHAT_ID:
        print("❌ ERROR: Falta TELEGRAM_CHAT_ID. Ejecuta setup.py primero.")
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f"  VALUE BETTING ANALYZER — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*55}\n")
    print("📡 Descargando cuotas...\n")

    today_iso = date.today().isoformat()
    all_results: list[tuple] = []
    extras_skipped = False
    extras_with_pinnacle = 0

    for league_key in LEAGUES_ODDS_API:
        games = get_odds_for_league(league_key)

        for game in games:
            # Filtra solo partidos de hoy
            match_date = game.get("commence_time", "")[:10]
            if match_date != today_iso:
                continue

            # Nombre bonito de la competición
            comp_label = (league_key
                          .replace("soccer_", "")
                          .replace("_", " ")
                          .replace("england premier league", "Premier League")
                          .replace("spain la liga", "La Liga")
                          .replace("italy serie a", "Serie A")
                          .replace("germany bundesliga", "Bundesliga")
                          .replace("uefa champs league", "Champions League")
                          .replace("uefa europa league", "Europa League")
                          .replace("brazil campeonato", "Brasileirão")
                          .title())

            game_info = {
                "home":        game["home_team"],
                "away":        game["away_team"],
                "competition": comp_label,
                "time":        game.get("commence_time", ""),
                "id":          game.get("id", ""),
                "league_key":  league_key,
            }

            # Comprueba si Pinnacle tiene este partido
            bm_keys = [bm["key"] for bm in game.get("bookmakers", [])]
            if SHARP_BOOK not in bm_keys:
                # Sin Pinnacle, no podemos calcular probabilidades fiables
                all_results.append((game_info, None))
                continue

            bets = analyze_match(game)

            # ── Córners y tarjetas (1 petición por partido) ──────────────
            if ENABLE_EXTRA_MARKETS:
                if CREDITS_REMAINING is not None and CREDITS_REMAINING < MIN_CREDITS_FOR_EXTRAS:
                    if not extras_skipped:
                        print(f"  ⚠ Quedan {CREDITS_REMAINING} créditos (<{MIN_CREDITS_FOR_EXTRAS}): "
                              f"se omiten córners y tarjetas")
                        extras_skipped = True
                elif game.get("id"):
                    ev_data = get_event_extra_odds(league_key, game["id"])
                    time.sleep(0.3)   # evita el límite de velocidad de la API
                    if ev_data:
                        pin_has_extra = any(
                            bm["key"] == SHARP_BOOK and
                            any(m["key"] in EXTRA_TOTALS_MARKETS for m in bm.get("markets", []))
                            for bm in ev_data.get("bookmakers", [])
                        )
                        if pin_has_extra:
                            extras_with_pinnacle += 1
                            bets = sorted(
                                bets + analyze_extra_markets(ev_data),
                                key=lambda x: x["ev"], reverse=True,
                            )
            all_results.append((game_info, bets))

    # Filtra los None (sin Pinnacle) para el mensaje
    clean_results = [(g, b) for g, b in all_results if b is not None]

    print(f"\n📊 Análisis completado:")
    print(f"   Partidos con Pinnacle analizado: {len(clean_results)}")
    print(f"   Partidos con valor encontrado:   {sum(1 for _, b in clean_results if b)}")
    total_picks = sum(len(b) for _, b in clean_results if b)
    print(f"   Total picks con EV positivo:     {total_picks}")
    if ENABLE_EXTRA_MARKETS:
        print(f"   Partidos con córners/tarjetas de Pinnacle: {extras_with_pinnacle}")
    if CREDITS_REMAINING is not None:
        print(f"   Créditos The Odds API restantes: {CREDITS_REMAINING}")

    print("\n📤 Enviando informe a Telegram...")
    markets_used = ["1X2", "Over/Under", "Hándicap"]
    if ENABLE_EXTRA_MARKETS:
        markets_used += ["Córners", "Tarjetas"]
    msg = build_message(clean_results, markets_used)
    ok = send_telegram(msg)

    if ok:
        print("✅ Informe enviado correctamente.\n")
    else:
        print("❌ Error al enviar. Revisa el token y el chat ID.\n")
        # Muestra el mensaje en consola como fallback
        print("─── INFORME (consola) ───")
        print(msg)

    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
