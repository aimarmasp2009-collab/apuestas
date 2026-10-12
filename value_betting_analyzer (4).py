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
    "soccer_epl",                   # Premier League (clave oficial en The Odds API)
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
#  MERCADOS EXTRA (se piden partido a partido)
# ─────────────────────────────────────────────
# Cada mercado extra gasta 1 crédito de The Odds API por partido.
# Plan gratuito = 500 créditos al MES, así que hay que elegir pocos mercados.
ENABLE_EXTRA_MARKETS      = True   # False = no pide ningún mercado extra
MIN_CREDITS_FOR_EXTRAS    = 100    # Si quedan menos créditos que esto, se omiten los extras
MAX_EXTRA_CREDITS_PER_RUN = 30     # Tope de créditos extra por ejecución (súbelo si tienes plan de pago)

# Catálogo de mercados de fútbol que sabe analizar el bot:
#   clave de la API  ->  (tipo de cálculo, nombre en el informe)
CATALOGO_MERCADOS = {
    "btts":                          ("twoway",      "Ambos marcan"),
    "btts_h1":                       ("twoway",      "Ambos marcan 1ª parte"),
    "draw_no_bet":                   ("twoway",      "Empate no apuesta"),
    "to_qualify":                    ("twoway",      "Se clasifica"),
    "double_chance":                 ("dc",          "Doble oportunidad"),
    "h2h_3_way_h1":                  ("threeway",    "1X2 1ª parte"),
    "corners_1x2":                   ("threeway",    "Más córners"),
    "alternate_totals":              ("totals",      "O/U"),
    "alternate_totals_h1":           ("totals",      "Goles 1ª parte"),
    "alternate_totals_corners":      ("totals",      "Córners"),
    "alternate_totals_cards":        ("totals",      "Tarjetas"),
    "alternate_team_totals":         ("team_totals", "Goles por equipo"),
    "alternate_team_totals_corners": ("team_totals", "Córners por equipo"),
    "alternate_spreads":             ("spreads",     "Hándicap goles"),
    "alternate_spreads_corners":     ("spreads",     "Hándicap córners"),
    "alternate_spreads_cards":       ("spreads",     "Hándicap tarjetas"),
}

# Mercados que SE PIDEN. Para activar uno, quítale el # del principio;
# para desactivarlo, ponle # delante. Cada uno activo = 1 crédito por partido.
MERCADOS_ACTIVOS = [
    "alternate_totals_corners",      # Córners Over/Under
    "alternate_totals_cards",        # Tarjetas Over/Under
    "btts",                          # Ambos marcan
    "double_chance",                 # Doble oportunidad
    "draw_no_bet",                   # Empate no apuesta
    # "alternate_totals",            # Goles: otras líneas Over/Under
    # "alternate_totals_h1",         # Goles 1ª parte
    # "alternate_team_totals",       # Goles por equipo
    # "alternate_spreads",           # Hándicap de goles (otras líneas)
    # "btts_h1",                     # Ambos marcan 1ª parte
    # "h2h_3_way_h1",                # 1X2 de la 1ª parte
    # "corners_1x2",                 # Equipo con más córners
    # "alternate_team_totals_corners",
    # "alternate_spreads_corners",
    # "alternate_spreads_cards",
    # "to_qualify",                  # Quién se clasifica (eliminatorias)
]

# Contadores internos (no tocar)
EXTRA_CREDITS_USED = 0

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
#  MERCADOS EXTRA (petición por partido)
# ─────────────────────────────────────────────

# tipo -> (nº de resultados por grupo, suma de probabilidades)
_REQUISITOS = {
    "twoway": (2, 1), "threeway": (3, 1), "dc": (3, 2),
    "totals": (2, 1), "team_totals": (2, 1), "spreads": (2, 1),
}
_TRADUCE = {"Yes": "Sí", "No": "No"}


def _motivo_omitir_extras():
    """Devuelve el motivo para no pedir más mercados extra, o None si se puede."""
    if CREDITS_REMAINING is not None and CREDITS_REMAINING < MIN_CREDITS_FOR_EXTRAS:
        return f"quedan {CREDITS_REMAINING} créditos (menos de {MIN_CREDITS_FOR_EXTRAS})"
    if EXTRA_CREDITS_USED + len(_mercados_validos()) > MAX_EXTRA_CREDITS_PER_RUN:
        return f"tope de {MAX_EXTRA_CREDITS_PER_RUN} créditos extra por ejecución"
    return None


def _mercados_validos() -> list[str]:
    return [m for m in MERCADOS_ACTIVOS if m in CATALOGO_MERCADOS]


def get_event_extra_odds(league_key: str, event_id: str):
    """Descarga los mercados extra activos de UN partido (endpoint /events/{id}/odds)."""
    global ENABLE_EXTRA_MARKETS, EXTRA_CREDITS_USED
    markets = _mercados_validos()
    if not markets:
        return None
    url = f"https://api.the-odds-api.com/v4/sports/{league_key}/events/{event_id}/odds"
    params = {
        "apiKey":     ODDS_API_KEY,
        "regions":    "eu",
        "markets":    ",".join(markets),
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
    except Exception as e:
        print(f"    ✗ mercados extra — {e}")
        return None

    _update_credits(r)
    if r.status_code == 200:
        try:
            EXTRA_CREDITS_USED += int(float(r.headers.get("x-requests-last")))
        except (TypeError, ValueError):
            EXTRA_CREDITS_USED += len(markets)   # estimación prudente
        return r.json()
    if r.status_code in (401, 403):
        print("    ✗ Tu plan de The Odds API no permite estos mercados → extras desactivados")
        ENABLE_EXTRA_MARKETS = False
    elif r.status_code == 429:
        print("    ✗ Límite de velocidad de la API (429) — se omite este partido")
    elif r.status_code not in (404, 422):
        print(f"    ✗ mercados extra — error {r.status_code}")
    return None


def _agrupar(outcomes: list, tipo: str) -> dict:
    """Agrupa los resultados de un mercado en grupos mutuamente excluyentes."""
    grupos: dict = {}
    for o in outcomes:
        price, name, p = o.get("price"), o.get("name"), o.get("point")
        if not price or not name:
            continue
        if tipo in ("twoway", "threeway", "dc"):
            g, k = "-", name
        elif tipo == "totals":
            if p is None or p % 1 != 0.5:       # solo líneas .5 (sin devolución)
                continue
            g, k = p, name
        elif tipo == "team_totals":
            equipo = o.get("description")
            if p is None or p % 1 != 0.5 or not equipo:
                continue
            g, k = (equipo, p), name
        elif tipo == "spreads":
            if p is None or abs(p) % 1 != 0.5:  # solo hándicaps .5
                continue
            g, k = abs(p), (name, p)
        else:
            continue
        grupos.setdefault(g, {})[k] = price
    return grupos


def _grupo_valido(grupo: dict, tipo: str) -> bool:
    n, _ = _REQUISITOS[tipo]
    if len(grupo) != n:
        return False
    if tipo == "spreads":
        (n1, p1), (n2, p2) = list(grupo.keys())
        return n1 != n2 and abs(p1 + p2) < 1e-9
    if tipo in ("totals", "team_totals"):
        return set(grupo.keys()) == {"Over", "Under"}
    return True


def _etiquetas(tipo: str, label: str, g, k) -> tuple[str, str]:
    """Devuelve (mercado, selección) para el informe."""
    noun = "" if label == "O/U" else label.replace(" por equipo", "").lower()
    if tipo in ("twoway", "threeway", "dc"):
        k = _TRADUCE.get(k, k).replace(" or ", " o ").replace("Draw", "Empate")
        return label, f"{label}: {k}"
    if tipo == "totals":
        return f"{label} {g}", f"{k} {g}" + (f" {noun}" if noun else "")
    if tipo == "team_totals":
        equipo, linea = g
        return f"{label} {equipo} {linea}", f"{equipo} {k} {linea} {noun}".strip()
    nombre, punto = k
    return f"{label} {g}", f"{label}: {nombre} {punto:+g}"


def analyze_extra_markets(event: dict):
    """
    Calcula el EV de los mercados extra usando Pinnacle como referencia (sin margen).
    Devuelve (lista de apuestas con valor, conjunto de mercados que Pinnacle sí ofrece).
    """
    bm_map = {bm["key"]: bm for bm in event.get("bookmakers", [])}
    if SHARP_BOOK not in bm_map:
        return [], set()

    pin_markets = {m["key"]: m.get("outcomes", []) for m in bm_map[SHARP_BOOK].get("markets", [])}
    pin_tiene: set = set()
    value_bets: list[dict] = []

    for mkt_key in _mercados_validos():
        tipo, label = CATALOGO_MERCADOS[mkt_key]
        if mkt_key not in pin_markets:
            continue
        pin_grupos = _agrupar(pin_markets[mkt_key], tipo)
        if not pin_grupos:
            continue
        pin_tiene.add(mkt_key)
        n_res, suma = _REQUISITOS[tipo]

        for g, pin_g in pin_grupos.items():
            if not _grupo_valido(pin_g, tipo):
                continue
            implicitas = {k: 1 / pr for k, pr in pin_g.items() if pr > 1}
            if len(implicitas) != n_res:
                continue
            total = sum(implicitas.values())
            justas = {k: v / total * suma for k, v in implicitas.items()}
            if any(v >= 1 for v in justas.values()):
                continue

            for book_key in VALUE_BOOKS:
                if book_key not in bm_map:
                    continue
                bm_mkts = {m["key"]: m.get("outcomes", []) for m in bm_map[book_key].get("markets", [])}
                if mkt_key not in bm_mkts:
                    continue
                bm_g = _agrupar(bm_mkts[mkt_key], tipo).get(g)
                if not bm_g:
                    continue
                for k, fair_p in justas.items():
                    if k not in bm_g:
                        continue
                    ev_val = ev(fair_p, bm_g[k])
                    if ev_val > MIN_EV:
                        mercado, seleccion = _etiquetas(tipo, label, g, k)
                        value_bets.append({
                            "market":    mercado,
                            "category":  label,
                            "selection": seleccion,
                            "bookmaker": book_key,
                            "odds":      bm_g[k],
                            "fair_prob": fair_p,
                            "ev":        ev_val,
                            "pin_odds":  1 / fair_p,   # cuota justa sin margen
                        })

    return dedupe_bets(value_bets), pin_tiene


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

def build_message(all_results: list[tuple], markets_used: list[str], nota_extra: str = "") -> str:
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
            cat = bet.get("category") or market_category(bet["market"])
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

    if nota_extra:
        msg += f"<i>{h(nota_extra)}</i>\n\n"

    msg += "<i>Cuota mín = probabilidad real Pinnacle sin margen. "
    msg += "Si Retabet/Kirolbet/Bet365 ofrecen más → hay valor.</i>"

    return msg


# ─────────────────────────────────────────────
#  ENVÍO TELEGRAM
# ─────────────────────────────────────────────

def _split_message(message: str, limit: int = 3800) -> list[str]:
    """Divide el informe en trozos < límite de Telegram, cortando entre bloques."""
    chunks, current = [], ""
    for block in message.split("\n\n"):
        if current and len(current) + len(block) + 2 > limit:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        chunks.append(current)
    return chunks


def send_telegram(message: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    all_ok = True
    for chunk in _split_message(message):
        data = {
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       chunk,
            "parse_mode": "HTML",
        }
        try:
            r = requests.post(url, json=data, timeout=15)
            if r.status_code != 200:
                print(f"  ✗ Telegram error {r.status_code}: {r.text[:200]}")
                all_ok = False
        except Exception as e:
            print(f"  ✗ Telegram exception: {e}")
            all_ok = False
    return all_ok


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
    extras_checked = 0
    cobertura: dict[str, int] = {}

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
                          .replace("epl", "Premier League")
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

            # ── Mercados extra (1 petición por partido) ──────────────────
            if ENABLE_EXTRA_MARKETS and _mercados_validos():
                motivo = _motivo_omitir_extras()
                if motivo:
                    if not extras_skipped:
                        print(f"  ⚠ Se omiten los mercados extra del resto de partidos: {motivo}")
                        extras_skipped = True
                elif game.get("id"):
                    ev_data = get_event_extra_odds(league_key, game["id"])
                    time.sleep(0.3)   # evita el límite de velocidad de la API
                    if ev_data:
                        extras_checked += 1
                        extra_bets, pin_mkts = analyze_extra_markets(ev_data)
                        if pin_mkts:
                            extras_with_pinnacle += 1
                        for mk in pin_mkts:
                            cobertura[mk] = cobertura.get(mk, 0) + 1
                        bets = sorted(bets + extra_bets, key=lambda x: x["ev"], reverse=True)
            all_results.append((game_info, bets))

    # Filtra los None (sin Pinnacle) para el mensaje
    clean_results = [(g, b) for g, b in all_results if b is not None]

    print(f"\n📊 Análisis completado:")
    print(f"   Partidos con Pinnacle analizado: {len(clean_results)}")
    print(f"   Partidos con valor encontrado:   {sum(1 for _, b in clean_results if b)}")
    total_picks = sum(len(b) for _, b in clean_results if b)
    print(f"   Total picks con EV positivo:     {total_picks}")
    if ENABLE_EXTRA_MARKETS and _mercados_validos():
        print(f"   Partidos con mercados extra revisados: {extras_checked}")
        print(f"   Partidos con algún mercado extra de Pinnacle: {extras_with_pinnacle}")
        for mk in _mercados_validos():
            print(f"     · {CATALOGO_MERCADOS[mk][1]:<24} Pinnacle lo ofrece en {cobertura.get(mk, 0)} partidos")
        print(f"   Créditos extra gastados en esta ejecución: {EXTRA_CREDITS_USED}")
    if CREDITS_REMAINING is not None:
        print(f"   Créditos The Odds API restantes: {CREDITS_REMAINING}")

    print("\n📤 Enviando informe a Telegram...")
    markets_used = ["1X2", "Over/Under", "Hándicap"]
    nota_extra = ""
    if ENABLE_EXTRA_MARKETS and _mercados_validos():
        for mk in _mercados_validos():
            nombre = CATALOGO_MERCADOS[mk][1]
            if nombre not in markets_used:
                markets_used.append(nombre)
        if extras_checked < len(clean_results):
            nota_extra = (f"Mercados extra revisados en {extras_checked} de "
                          f"{len(clean_results)} partidos (límite de créditos).")
    msg = build_message(clean_results, markets_used, nota_extra)
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
