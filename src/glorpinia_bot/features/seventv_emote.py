import json
import logging
import os
import random
import string
import threading
import time

import requests

GQL_URL = "https://7tv.io/v4/gql"

SEARCH_QUERY = """
query SearchEmotes($page: Int!, $perPage: Int!, $sort: Sort!, $query: String) {
  emotes {
    search(page: $page, perPage: $perPage, sort: $sort, query: $query) {
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

CANDIDATE_PAGE_SIZE = 30
RANDOM_PAGES_PER_SORT = 5
RANDOM_HASHES_PER_REFRESH = 4
RANDOM_PAGES_PER_HASH = 1  # Uma página por fragmento: limita a coleta a 4 buscas + trending.
MIN_CHANNELS = 10
MAX_CHANNELS = 100
CACHE_TTL_SECONDS = 3 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 12
MAX_STALE_CACHE_AGE_SECONDS = 7 * 24 * 60 * 60

SORT_TRENDING = {"sortBy": "TRENDING_WEEKLY", "order": "DESCENDING"}
SORT_POPULAR = {"sortBy": "TOP_WEEKLY", "order": "DESCENDING"}


class SevenTVRateLimitError(RuntimeError):
    def __init__(self, message, retry_after=60):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after or 60))


class SevenTVEmote:
    """
    Sorteia emotes conhecidos do 7TV com cache compartilhado, atualização única
    concorrente (single-flight) e fallback para o último cache válido.
    """

    def __init__(self, bot):
        self.bot = bot
        self._candidate_cache = []
        self._trending_candidate_cache = []
        self._cache_expires_at = 0
        self._cache_updated_at = 0
        self._cache_path = os.getenv("SEVENTV_EMOTE_CACHE_FILE", "seventv_emote_cache.json")
        self._condition = threading.Condition(threading.Lock())
        self._refreshing = False
        self._rate_limit_until = 0
        self._last_refresh_error = None
        self._load_cache()
        print("[Feature] SevenTVEmote Initialized.")

    def get_random_emote(self, channel, author, trending_only=False):
        thread = threading.Thread(
            target=self._fetch_and_send,
            args=(channel, author, trending_only),
            daemon=True,
        )
        thread.start()

    @staticmethod
    def _retry_after_from_error(error, response=None):
        retry_after = None
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if not retry_after:
                retry_after = response.headers.get("x-ratelimit-search-reset")
        if isinstance(error, dict):
            extensions = error.get("extensions") or {}
            headers = extensions.get("headers") or {}
            retry_after = retry_after or headers.get("x-ratelimit-search-reset")
        try:
            return max(1, int(float(retry_after)))
        except (TypeError, ValueError):
            return 60

    def _search_emotes(self, sort, page=1, query=None):
        payload = {
            "operationName": "SearchEmotes",
            "query": SEARCH_QUERY,
            "variables": {
                "page": page,
                "perPage": CANDIDATE_PAGE_SIZE,
                "sort": sort,
                "query": query,
            },
        }
        response = requests.post(
            GQL_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 429:
            raise SevenTVRateLimitError(
                "7TV HTTP 429 rate limit exceeded",
                self._retry_after_from_error({}, response),
            )
        response.raise_for_status()
        data = response.json()

        errors = data.get("errors") or []
        rate_limit_error = next(
            (
                error for error in errors
                if (error.get("extensions") or {}).get("code") == "RATE_LIMIT_EXCEEDED"
            ),
            None,
        )
        if rate_limit_error:
            raise SevenTVRateLimitError(
                rate_limit_error.get("message", "7TV search rate limit exceeded"),
                self._retry_after_from_error(rate_limit_error, response),
            )
        if errors:
            raise RuntimeError(f"7TV GraphQL errors: {errors}")

        return data["data"]["emotes"]["search"]

    def _search_emote_sample(self, sort, query=None, max_pages=None):
        """Busca páginas aleatórias do ranking, em vez de ficar preso à primeira página."""
        first_page = self._search_emotes(sort, page=1, query=query)
        total_count = max(0, int(first_page.get("totalCount") or 0))
        total_pages = max(1, (total_count + CANDIDATE_PAGE_SIZE - 1) // CANDIDATE_PAGE_SIZE)
        page_count = min(max_pages or RANDOM_PAGES_PER_SORT, total_pages)
        selected_pages = random.sample(range(1, total_pages + 1), page_count)

        sampled_items = []
        for page in selected_pages:
            result = first_page if page == 1 else self._search_emotes(sort, page=page, query=query)
            sampled_items.extend(result.get("items") or [])

        # Uma página pode mudar entre consultas; deduplicar pelo ID evita peso duplicado.
        unique_items = {}
        for emote in sampled_items:
            if emote.get("id"):
                unique_items[emote["id"]] = emote
        return list(unique_items.values())

    @staticmethod
    def _random_hash():
        """Gera um fragmento aleatório para explorar diferentes regiões da busca por nome."""
        return "".join(random.sample(string.ascii_lowercase + string.digits, 2))

    def _search_obscure_emotes(self):
        """Busca por fragmentos aleatórios, sem depender do ranking global de popularidade."""
        sampled = {}
        for _ in range(RANDOM_HASHES_PER_REFRESH):
            random_hash = self._random_hash()
            try:
                items = self._search_emote_sample(SORT_POPULAR, query=random_hash, max_pages=RANDOM_PAGES_PER_HASH)
            except SevenTVRateLimitError:
                raise
            except Exception as exc:
                logging.warning("[SevenTVEmote] Falha na busca aleatória '%s': %s", random_hash, exc)
                continue
            for emote in items:
                if emote.get("id"):
                    sampled[emote["id"]] = emote
        return list(sampled.values())

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
        """Retorna dois pools independentes: trending puro e emotes presentes em 10+ canais."""
        trending_items = self._search_emote_sample(SORT_TRENDING)
        obscure_items = self._search_obscure_emotes()

        trending_by_id = {}
        for emote in trending_items:
            if not self._is_usable(emote):
                continue
            scores = emote.get("scores") or {}
            channels = emote.get("channels") or {}
            candidate = {
                "id": emote["id"],
                "name": emote["defaultName"],
                "trending_score": max(0, int(scores.get("trendingWeek") or 0)),
                "channel_count": max(0, int(channels.get("totalCount") or 0)),
            }
            trending_by_id[candidate["id"]] = candidate

        popular_by_id = {}
        for emote in obscure_items:
            if not self._is_usable(emote):
                continue
            scores = emote.get("scores") or {}
            channels = emote.get("channels") or {}
            candidate = {
                "id": emote["id"],
                "name": emote["defaultName"],
                "trending_score": max(0, int(scores.get("trendingWeek") or 0)),
                "channel_count": max(0, int(channels.get("totalCount") or 0)),
            }
            if not MIN_CHANNELS <= candidate["channel_count"] <= MAX_CHANNELS:
                continue
            previous = popular_by_id.get(candidate["id"])
            if previous:
                previous["trending_score"] = max(previous["trending_score"], candidate["trending_score"])
                previous["channel_count"] = max(previous["channel_count"], candidate["channel_count"])
            else:
                popular_by_id[candidate["id"]] = candidate

        trending_candidates = list(trending_by_id.values())
        candidates = list(popular_by_id.values())
        return candidates, trending_candidates

    def _load_cache(self):
        try:
            with open(self._cache_path, encoding="utf-8") as cache_file:
                payload = json.load(cache_file)
            candidates = payload.get("candidates") or []
            trending_candidates = payload.get("trending_candidates") or []
            updated_at = float(payload.get("updated_at") or 0)
            age = max(0, time.time() - updated_at)
            schema_version = payload.get("schema_version", 1)
            if schema_version not in (1, 2) or not candidates or not trending_candidates or age > MAX_STALE_CACHE_AGE_SECONDS:
                return
            self._candidate_cache = candidates
            self._trending_candidate_cache = trending_candidates
            self._cache_updated_at = updated_at
            remaining = max(0, CACHE_TTL_SECONDS - age)
            # Cache legado continua como fallback, mas força uma atualização para
            # aplicar a nova descoberta por fragmentos aleatórios e o limite de canais.
            self._cache_expires_at = (
                time.monotonic() + remaining if schema_version == 2 else 0
            )
            logging.info(
                "[SevenTVEmote] Cache persistido carregado: %s candidatos (10+ canais), %s trending (idade=%ss).",
                len(candidates), len(trending_candidates), int(age),
            )
        except FileNotFoundError:
            return
        except Exception as exc:
            logging.warning("[SevenTVEmote] Não foi possível carregar cache persistido: %s", exc)

    def _save_cache(self, candidates, trending_candidates):
        try:
            temporary_path = self._cache_path + ".tmp"
            with open(temporary_path, "w", encoding="utf-8") as cache_file:
                json.dump(
                    {
                        "schema_version": 2,
                        "updated_at": time.time(),
                        "candidates": candidates,
                        "trending_candidates": trending_candidates,
                    },
                    cache_file,
                    ensure_ascii=False,
                )
            os.replace(temporary_path, self._cache_path)
        except Exception as exc:
            logging.warning("[SevenTVEmote] Não foi possível persistir cache: %s", exc)

    def _get_candidates(self, trending_only=False):
        with self._condition:
            now = time.monotonic()
            cache = self._trending_candidate_cache if trending_only else self._candidate_cache
            if cache and now < self._cache_expires_at:
                return cache

            if now < self._rate_limit_until:
                if cache:
                    logging.warning(
                        "[SevenTVEmote] Rate limit ativo; usando cache anterior por mais %ss.",
                        int(self._rate_limit_until - now),
                    )
                    return cache
                raise SevenTVRateLimitError(
                    "7TV rate limit ativo e nenhum cache disponível para o filtro solicitado.",
                    self._rate_limit_until - now,
                )

            if self._refreshing:
                deadline = now + REQUEST_TIMEOUT_SECONDS * 2 + 5
                while self._refreshing and time.monotonic() < deadline:
                    self._condition.wait(timeout=max(0.1, deadline - time.monotonic()))
                cache = self._trending_candidate_cache if trending_only else self._candidate_cache
                if cache:
                    return cache
                if self._last_refresh_error:
                    raise self._last_refresh_error
                raise RuntimeError("Atualização do cache 7TV não terminou a tempo.")

            self._refreshing = True

        try:
            candidates, trending_candidates = self._fetch_candidates()
        except Exception as exc:
            with self._condition:
                self._last_refresh_error = exc
                if isinstance(exc, SevenTVRateLimitError):
                    self._rate_limit_until = time.monotonic() + exc.retry_after
                self._refreshing = False
                self._condition.notify_all()
                cache = self._trending_candidate_cache if trending_only else self._candidate_cache
                if cache:
                    logging.warning(
                        "[SevenTVEmote] Falha ao atualizar; usando %s candidatos do cache anterior: %s",
                        len(cache), exc,
                    )
                    return cache
            raise

        with self._condition:
            self._candidate_cache = candidates
            self._trending_candidate_cache = trending_candidates
            self._cache_updated_at = time.time()
            self._cache_expires_at = time.monotonic() + CACHE_TTL_SECONDS
            self._rate_limit_until = 0
            self._last_refresh_error = None
            self._refreshing = False
            self._condition.notify_all()
        self._save_cache(candidates, trending_candidates)
        selected_pool = trending_candidates if trending_only else candidates
        if not selected_pool:
            if trending_only:
                raise RuntimeError("Nenhum emote disponível no ranking trending do 7TV.")
            raise RuntimeError(f"Nenhum emote encontrado entre {MIN_CHANNELS} e {MAX_CHANNELS} canais.")
        logging.info(
            "[SevenTVEmote] Cache atualizado: %s emotes entre %s e %s canais; %s emotes do trending sem filtro de canais.",
            len(candidates), MIN_CHANNELS, MAX_CHANNELS, len(trending_candidates),
        )
        return selected_pool

    def _emote_aleatorio(self, trending_only=False):
        candidates = self._get_candidates(trending_only=trending_only)
        emote = random.choice(candidates)
        emote_url = self._humanize_link(f"https://7tv.app/emotes/{emote['id']}")
        return emote["name"], emote_url

    @staticmethod
    def _humanize_link(url):
        """Evita que o link fique clicável automaticamente no chat."""
        no_scheme = url.replace("https://", "").replace("http://", "")
        domain, _, path = no_scheme.partition("/")
        domain = domain.replace(".", " . ")
        return f"{domain}/{path}" if path else domain

    def _fetch_and_send(self, channel, author, trending_only=False):
        try:
            name, url = self._emote_aleatorio(trending_only=trending_only)
            self.bot.send_message(channel, f"@{author} glorp {name} -> {url}")
        except SevenTVRateLimitError as error:
            logging.warning(
                "[SevenTVEmote] 7TV temporariamente limitado; retry em %ss: %s",
                error.retry_after, error,
            )
            self.bot.send_message(
                channel,
                f"@{author}, o 7TV está temporariamente limitado; tente novamente em instantes Sadge",
            )
        except Exception as error:
            logging.error("[SevenTVEmote] Falha ao buscar emote: %s", error)
            self.bot.send_message(
                channel,
                f"@{author}, o 7TV não respondeu direito agora Sadge",
            )
