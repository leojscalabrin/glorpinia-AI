import random
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
TRENDING_PAGE_LIMIT = 5

SORT_TRENDING = {"value": "trending", "order": "DESCENDING"}


class SevenTVEmote:
    """
    Puxa um emote aleatório da lista de trending atual do 7TV.
    A API GraphQL do 7TV expõe a busca de emotes com ordenação por
    trending; o comando usa uma query vazia para pegar o ranking atual
    e sorteia um item entre as primeiras páginas desse ranking.
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
            "variables": {"query": query, "page": page, "limit": limit, "sort": SORT_TRENDING},
        }
        r = requests.post(GQL_URL, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(str(data["errors"]))
        return data["data"]["emotes"]

    def _emote_aleatorio(self):
        primeiro = self._buscar("", 1, 1)
        total = primeiro["count"]
        if total == 0:
            raise RuntimeError("Nenhum emote trending encontrado.")

        last_page = min(TRENDING_PAGE_LIMIT, max(1, -(-total // PAGE_SIZE)))
        page = random.randint(1, last_page)

        items = self._buscar("", page, PAGE_SIZE)["items"]
        if not items:
            raise RuntimeError("Página de trending vazia no 7TV.")

        emote = random.choice(items)
        emote_url = self._humanize_link(f"https://7tv.app/emotes/{emote['id']}")
        return emote["name"], emote_url

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
            nome, url = self._emote_aleatorio()
            self.bot.send_message(channel, f"@{author} glorp {nome} -> {url}")
        except Exception as e:
            logging.error(f"[SevenTVEmote] Falha ao buscar emote: {e}")
            self.bot.send_message(channel, f"@{author}, o 7TV não respondeu direito agora Sadge")