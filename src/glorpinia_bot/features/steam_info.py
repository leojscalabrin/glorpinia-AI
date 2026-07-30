import logging
import threading
import time

import requests

STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
APP_REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"

CACHE_TTL_SECONDS = 15 * 60


class SteamInfo:
    """
    *steam <nome do jogo> -> resumo com preço (BRL), metacritic, data de
    lançamento, developer/gênero principal e % de reviews.
    Usa só endpoints públicos da própria Steam Store, sem API key.
    """

    def __init__(self, bot):
        self.bot = bot
        self._cache = {}  # query normalizada -> (timestamp, mensagem)
        print("[Feature] SteamInfo Initialized.")

    def lookup(self, channel, author, query):
        t = threading.Thread(target=self._fetch_and_send, args=(channel, author, query))
        t.daemon = True
        t.start()


    def _search_appid(self, query):
        r = requests.get(
            STORE_SEARCH_URL,
            params={"term": query, "l": "portuguese", "cc": "br"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or []
        if not items:
            return None, None
        top = items[0]
        return top.get("id"), top.get("name")

    def _fetch_details(self, appid):
        r = requests.get(
            APP_DETAILS_URL,
            params={"appids": appid, "cc": "br", "l": "portuguese"},
            timeout=10,
        )
        r.raise_for_status()
        payload = r.json().get(str(appid)) or {}
        if not payload.get("success"):
            return None
        return payload.get("data") or {}

    def _fetch_review_summary(self, appid):
        r = requests.get(
            APP_REVIEWS_URL.format(appid=appid),
            params={"json": 1, "language": "all", "purchase_type": "all", "num_per_page": 0},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("query_summary") or {}


    def _format_price(self, details):
        if details.get("is_free"):
            return "Grátis"

        price = details.get("price_overview")
        if not price:
            return "Preço indisponível"

        final = price.get("final_formatted", "?")
        discount = price.get("discount_percent", 0)
        if discount:
            initial = price.get("initial_formatted", "?")
            return f"{final} (-{discount}%, de {initial})"
        return final

    def _format_reviews(self, summary):
        total = summary.get("total_reviews") or 0
        positive = summary.get("total_positive") or 0
        desc = summary.get("review_score_desc")
        if not total or not desc:
            return None
        pct = round((positive / total) * 100)
        return f"{desc} ({pct}% de {total:,}".replace(",", ".") + ")"

    def _format_metacritic(self, details):
        meta = details.get("metacritic")
        if not meta:
            return None
        return f"Metacritic {meta.get('score')}"

    def _format_release_year(self, details):
        release = details.get("release_date") or {}
        date_str = release.get("date")
        if release.get("coming_soon"):
            return f"em breve ({date_str})" if date_str else "em breve"
        return date_str or None

    def _format_main_developer(self, details):
        devs = details.get("developers") or []
        return devs[0] if devs else None

    def _format_main_genre(self, details):
        genres = details.get("genres") or []
        return genres[0]["description"] if genres else None

    def _build_message(self, appid, details, review_summary):
        name = details.get("name", "?")
        parts = [name]

        release = self._format_release_year(details)
        if release:
            parts[0] = f"{name} ({release})"

        dev = self._format_main_developer(details)
        if dev:
            parts.append(dev)

        genre = self._format_main_genre(details)
        if genre:
            parts.append(genre)

        parts.append(self._format_price(details))

        meta = self._format_metacritic(details)
        if meta:
            parts.append(meta)

        reviews = self._format_reviews(review_summary)
        if reviews:
            parts.append(f"Reviews: {reviews}")

        return "glorp " + " | ".join(parts)


    def _fetch_and_send(self, channel, author, query):
        normalized = query.strip().lower()

        cached = self._cache.get(normalized)
        if cached and (time.time() - cached[0]) < CACHE_TTL_SECONDS:
            self.bot.send_message(channel, cached[1])
            return

        try:
            appid, matched_name = self._search_appid(query)
            if not appid:
                self.bot.send_message(channel, f"@{author} glorp Não achei nenhum jogo pra '{query}' na Steam.")
                return

            details = self._fetch_details(appid)
            if not details:
                self.bot.send_message(channel, f"@{author} glorp Achei '{matched_name}' mas a Steam não retornou detalhes agora.")
                return

            review_summary = {}
            try:
                review_summary = self._fetch_review_summary(appid)
            except Exception as e:
                logging.warning("[SteamInfo] Falha ao buscar reviews de %s: %s", appid, e)

            message = self._build_message(appid, details, review_summary)
            message = f"@{author} {message}"

            self._cache[normalized] = (time.time(), message)
            self.bot.send_message(channel, message)

        except Exception as e:
            logging.error("[SteamInfo] Falha ao buscar '%s': %s", query, e)
            self.bot.send_message(channel, f"@{author}, a Steam não respondeu direito agora Sadge")