import logging
import random
import threading
import time

import requests

GQL_URL = "https://7tv.io/v4/gql"

SEARCH_QUERY = """
query SearchEmotes($page: Int!, $perPage: Int!, $sort: Sort!) {
  emotes {
    search(page: $page, perPage: $perPage, sort: $sort) {
      items {
        id
        defaultName
        deleted
        flags {
          private
          nsfw
          publicListed
        }
        scores {
          trendingWeek
        }
        channels(page: 1, perPage: 1) {
          totalCount
        }
      }
      totalCount
    }
  }
}
"""

CANDIDATE_PAGE_SIZE = 50
MIN_CHANNELS = 50
CACHE_TTL_SECONDS = 3 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 12

SORT_TRENDING = {"sortBy": "TRENDING_WEEKLY", "order": "DESCENDING"}
SORT_POPULAR = {"sortBy": "TOP_WEEKLY", "order": "DESCENDING"}


class SevenTVEmote:
    """
    Sorteia emotes conhecidos do 7TV, combinando trending semanal e
    popularidade (mínimo de 50 canais). A pontuação de trending aumenta
    proporcionalmente a chance de seleção.
    """

    def __init__(self, bot):
        self.bot = bot
        self._candidate_cache = []
        self._cache_expires_at = 0
        self._cache_lock = threading.Lock()
        print("[Feature] SevenTVEmote Initialized.")

    def get_random_emote(self, channel, author):
        thread = threading.Thread(
            target=self._fetch_and_send,
            args=(channel, author),
            daemon=True,
        )
        thread.start()

    def _search_emotes(self, sort):
        payload = {
            "operationName": "SearchEmotes",
            "query": SEARCH_QUERY,
            "variables": {
                "page": 1,
                "perPage": CANDIDATE_PAGE_SIZE,
                "sort": sort,
            },
        }
        response = requests.post(
            GQL_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("errors"):
            raise RuntimeError(f"7TV GraphQL errors: {data['errors']}")

        return data["data"]["emotes"]["search"]["items"]

    @staticmethod
    def _is_usable(emote):
        flags = emote.get("flags") or {}
        return (
            bool(emote.get("id"))
            and bool(emote.get("defaultName"))
            and not emote.get("deleted", False)
            and not flags.get("private", False)
            and not flags.get("nsfw", False)
            and flags.get("publicListed", True)
        )

    def _fetch_candidates(self):
        # A consulta retorna a pontuação semanal e o total de canais
        # para cada emote, evitando uma chamada HTTP por candidato.
        trending_items = self._search_emotes(SORT_TRENDING)
        popular_items = self._search_emotes(SORT_POPULAR)

        candidates_by_id = {}

        for emote in trending_items + popular_items:
            if not self._is_usable(emote):
                continue

            scores = emote.get("scores") or {}
            channels = emote.get("channels") or {}
            trending_score = max(0, int(scores.get("trendingWeek") or 0))
            channel_count = max(0, int(channels.get("totalCount") or 0))

            # Trending semanal OU presença em pelo menos 50 canais.
            if trending_score <= 0 and channel_count < MIN_CHANNELS:
                continue

            candidate = {
                "id": emote["id"],
                "name": emote["defaultName"],
                "trending_score": trending_score,
                "channel_count": channel_count,
            }

            previous = candidates_by_id.get(candidate["id"])
            if previous:
                previous["trending_score"] = max(
                    previous["trending_score"], trending_score
                )
                previous["channel_count"] = max(
                    previous["channel_count"], channel_count
                )
            else:
                candidates_by_id[candidate["id"]] = candidate

        candidates = list(candidates_by_id.values())
        if not candidates:
            raise RuntimeError("Nenhum emote atende aos critérios de trending/popularidade.")

        return candidates

    def _get_candidates(self):
        now = time.monotonic()
        with self._cache_lock:
            if self._candidate_cache and now < self._cache_expires_at:
                return self._candidate_cache

        try:
            candidates = self._fetch_candidates()
        except Exception:
            # Se a API oscilar, ainda podemos usar o último conjunto válido.
            with self._cache_lock:
                if self._candidate_cache:
                    logging.warning(
                        "[SevenTVEmote] Falha ao atualizar cache; usando candidatos anteriores.",
                        exc_info=True,
                    )
                    return self._candidate_cache
            raise

        with self._cache_lock:
            self._candidate_cache = candidates
            self._cache_expires_at = time.monotonic() + CACHE_TTL_SECONDS
            logging.info(
                "[SevenTVEmote] Cache atualizado: %s candidatos (mínimo %s canais ou trending semanal).",
                len(candidates),
                MIN_CHANNELS,
            )
            return self._candidate_cache

    @staticmethod
    def _selection_weight(candidate):
        # O peso base mantém emotes populares fora do trending elegíveis.
        # A raiz suaviza diferenças extremas sem apagar a vantagem do trending.
        score = candidate["trending_score"]
        return 1.0 + (score ** 0.5)

    def _emote_aleatorio(self):
        candidates = self._get_candidates()
        weights = [self._selection_weight(item) for item in candidates]
        emote = random.choices(candidates, weights=weights, k=1)[0]
        emote_url = self._humanize_link(
            f"https://7tv.app/emotes/{emote['id']}"
        )
        return emote["name"], emote_url

    @staticmethod
    def _humanize_link(url):
        """Evita que o link fique clicável automaticamente no chat."""
        no_scheme = url.replace("https://", "").replace("http://", "")
        domain, _, path = no_scheme.partition("/")
        domain = domain.replace(".", " . ")
        return f"{domain}/{path}" if path else domain

    def _fetch_and_send(self, channel, author):
        try:
            name, url = self._emote_aleatorio()
            self.bot.send_message(channel, f"@{author} glorp {name} -> {url}")
        except Exception as error:
            logging.error(
                "[SevenTVEmote] Falha ao buscar emote: %s",
                error,
                exc_info=True,
            )
            self.bot.send_message(
                channel,
                f"@{author}, o 7TV não respondeu direito agora Sadge",
            )
