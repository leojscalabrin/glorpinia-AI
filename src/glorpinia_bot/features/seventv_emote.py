import random
import string
import threading
import logging

import requests

GQL_URL = "https://7tv.io/v3/gql"

SEARCH_QUERY = """
query SearchEmotes($query: String!, $page: Int, $limit: Int, $sort: Sort) {
  emotes(query: $query, page: $page, limit: $limit, sort: $sort) {
    count
    items {
      id
      name
      host { url }
    }
  }
}
"""

PAGE_SIZE = 100
MAX_PAGE = 100
MAX_TENTATIVAS = 5

SORT_POPULAR = {"value": "popularity", "order": "DESCENDING"}


class SevenTVEmote:
    """
    Puxa um emote "aleatório" (ponderado por popularidade) da base do 7TV.
    Gera um termo curto aleatório, busca quantos
    resultados existem pra ele, sorteia uma página dentro desse total e
    pega um item aleatório da página (sempre ordenado por popularidade).
    """

    def __init__(self, bot):
        self.bot = bot
        print("[Feature] SevenTVEmote Initialized.")

    def get_random_emote(self, channel, author):
        t = threading.Thread(target=self._fetch_and_send, args=(channel, author))
        t.daemon = True
        t.start()

    def _buscar(self, query, page, limit):
        payload = {
            "operationName": "SearchEmotes",
            "query": SEARCH_QUERY,
            "variables": {"query": query, "page": page, "limit": limit, "sort": SORT_POPULAR},
        }
        r = requests.post(GQL_URL, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(str(data["errors"]))
        return data["data"]["emotes"]

    def _emote_aleatorio(self):
        for _ in range(MAX_TENTATIVAS):
            termo = "".join(random.choices(string.ascii_lowercase, k=random.randint(1, 2)))

            primeiro = self._buscar(termo, 1, 1)
            total = primeiro["count"]
            if total == 0:
                continue

            last_page = min(MAX_PAGE, max(1, -(-total // PAGE_SIZE)))
            page = random.randint(1, last_page)

            items = self._buscar(termo, page, PAGE_SIZE)["items"]
            if not items:
                continue

            emote = random.choice(items)
            emote_url = self._humanize_link(f"https://7tv.app/emotes/{emote['id']}")
            return emote["name"], emote_url, termo, total

        raise RuntimeError("Nenhum emote encontrado após várias tentativas.")

    def _humanize_link(self, url):
      """
      Remove o esquema http(s):// e insere um espaço só no ponto do domínio
      (ex.: 7tv.app/emotes/ID -> 7tv . app/emotes/ID), pra não virar link
      clicável no chat.
      """
      no_scheme = url.replace("https://", "").replace("http://", "")
      domain, _, path = no_scheme.partition("/")
      domain = domain.replace(".", " . ")
      return f"{domain}/{path}" if path else domain

    def _fetch_and_send(self, channel, author):
        try:
            nome, url, termo, total = self._emote_aleatorio()
            self.bot.send_message(channel, f"@{author} glorp {nome} -> {url}")
        except Exception as e:
            logging.error(f"[SevenTVEmote] Falha ao buscar emote: {e}")
            self.bot.send_message(channel, f"@{author}, o 7TV não respondeu direito agora Sadge")