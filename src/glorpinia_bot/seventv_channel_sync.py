import logging
import threading
import time

import requests

from .emote_classifier import classify_emote_name

TWITCH_USERS_URL = "https://api.twitch.tv/helix/users"
SEVENTV_USER_URL = "https://7tv.io/v3/users/twitch/{twitch_id}"
SEVENTV_GLOBAL_ALIAS_URL = "https://7tv.io/v3/emote-sets/global"
SEVENTV_GLOBAL_SET_FALLBACK_ID = "62cdd34e72a832540de95857"

REFRESH_INTERVAL_SECONDS = 6 * 60 * 60  # 6h


class SevenTVChannelSync:
    """
    Substitui a curadoria manual dos .txt: busca os emotes realmente
    ativos no canal (7TV) + o set global, classifica cada nome por
    emoção/intenção via emote_classifier, e injeta isso no EmoteManager
    através de load_from_seventv() -- sem alterar a API do EmoteManager,
    então choose_emote() e o resto do bot continuam iguais.
    """

    def __init__(self, bot):
        self.bot = bot
        self._last_sync = {}
        print("[Feature] SevenTVChannelSync Initialized.")


    def sync_channel_async(self, channel, force=False):
        t = threading.Thread(target=self._sync_channel, args=(channel, force))
        t.daemon = True
        t.start()

    def sync_global_async(self, force=False):
        t = threading.Thread(target=self._sync_global, args=(force,))
        t.daemon = True
        t.start()


    def _resolve_twitch_user_id(self, channel_login):
        headers = {
            "Client-Id": self.bot.auth.client_id,
            "Authorization": f"Bearer {self.bot.auth.access_token}",
        }
        r = requests.get(
            TWITCH_USERS_URL,
            headers=headers,
            params={"login": channel_login.lower()},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            raise RuntimeError(f"Usuário Twitch '{channel_login}' não encontrado.")
        return data[0]["id"]


    def _fetch_channel_emote_names(self, channel_login):
        twitch_id = self._resolve_twitch_user_id(channel_login)
        r = requests.get(SEVENTV_USER_URL.format(twitch_id=twitch_id), timeout=10)

        if r.status_code == 404:
            logging.info("[SevenTVSync] Canal %s não tem conta/emote-set no 7TV.", channel_login)
            return []

        r.raise_for_status()
        data = r.json()
        emote_set = data.get("emote_set") or {}
        emotes = emote_set.get("emotes") or []
        return [e["name"] for e in emotes if e.get("name")]

    def _fetch_global_emote_names(self):
        try:
            r = requests.get(SEVENTV_GLOBAL_ALIAS_URL, timeout=10)
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            logging.info("[SevenTVSync] Alias 'global' falhou, tentando ID fixo de fallback.")
            r = requests.get(
                f"https://7tv.io/v3/emote-sets/{SEVENTV_GLOBAL_SET_FALLBACK_ID}", timeout=10
            )
            r.raise_for_status()

        data = r.json()
        emotes = data.get("emotes") or []
        return [e["name"] for e in emotes if e.get("name")]


    def _classify_names(self, names):
        """emoção -> [nomes]; nomes sem classificação clara vão pra 'neutral'."""
        by_emotion = {}
        for name in names:
            emotion = classify_emote_name(name) or "neutral"
            by_emotion.setdefault(emotion, []).append(name)
        return by_emotion

    def _sync_channel(self, channel, force):
        normalized = channel.lower()
        if not force and self._recently_synced(normalized):
            return
        try:
            names = self._fetch_channel_emote_names(normalized)
            if not names:
                logging.info("[SevenTVSync] Nenhum emote 7TV encontrado pra #%s.", normalized)
                return
            by_emotion = self._classify_names(names)
            self.bot.emote_manager.load_from_seventv(normalized, by_emotion)
            self._last_sync[normalized] = time.time()
            logging.info(
                "[SevenTVSync] #%s sincronizado: %s emotes em %s categorias.",
                normalized, len(names), len(by_emotion),
            )
        except Exception as e:
            logging.error("[SevenTVSync] Falha ao sincronizar #%s: %s", normalized, e)

    def _sync_global(self, force):
        if not force and self._recently_synced("__global__"):
            return
        try:
            names = self._fetch_global_emote_names()
            by_emotion = self._classify_names(names)
            self.bot.emote_manager.load_from_seventv(None, by_emotion)
            self._last_sync["__global__"] = time.time()
            logging.info(
                "[SevenTVSync] Set global sincronizado: %s emotes em %s categorias.",
                len(names), len(by_emotion),
            )
        except Exception as e:
            logging.error("[SevenTVSync] Falha ao sincronizar set global: %s", e)

    def _recently_synced(self, key):
        last = self._last_sync.get(key)
        return last is not None and (time.time() - last) < REFRESH_INTERVAL_SECONDS