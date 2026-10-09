"""Persistent user tags for the Glorpinia Twitch bot."""
import json
import logging
import os
import re
import threading


class UserTagManager:
    MAX_TAGS = 5
    MAX_TAG_LENGTH = 40
    DEFAULT_FILE = "user_tags.json"

    def __init__(self, path=None):
        self.path = path or os.getenv("USER_TAGS_FILE", self.DEFAULT_FILE)
        self._lock = threading.RLock()
        self._tags = {}
        self._load()

    @staticmethod
    def _normalize_nick(nick):
        return re.sub(r"[^a-zA-Z0-9_]", "", (nick or "").lstrip("@")).lower()

    @staticmethod
    def _normalize_tag(tag):
        return re.sub(r"\s+", " ", (tag or "").strip())

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("Formato inválido")
            for nick, tags in data.items():
                normalized_nick = self._normalize_nick(nick)
                if not normalized_nick or not isinstance(tags, list):
                    continue
                unique = []
                for tag in tags:
                    clean = self._normalize_tag(tag)
                    if clean and len(clean) <= self.MAX_TAG_LENGTH and clean.casefold() not in {x.casefold() for x in unique}:
                        unique.append(clean)
                    if len(unique) >= self.MAX_TAGS:
                        break
                self._tags[normalized_nick] = unique
        except Exception as exc:
            logging.error("[Tags] Falha ao carregar %s: %s", self.path, exc)

    def _save(self):
        temp_path = self.path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(self._tags, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, self.path)

    def get_tags(self, nick):
        key = self._normalize_nick(nick)
        with self._lock:
            return list(self._tags.get(key, []))

    def add_tag(self, nick, tag):
        key = self._normalize_nick(nick)
        clean = self._normalize_tag(tag)
        if not key or not clean or len(clean) > self.MAX_TAG_LENGTH:
            return False, "invalid"
        with self._lock:
            tags = self._tags.setdefault(key, [])
            if any(existing.casefold() == clean.casefold() for existing in tags):
                return False, "exists"
            if len(tags) >= self.MAX_TAGS:
                return False, "limit"
            tags.append(clean)
            try:
                self._save()
            except Exception as exc:
                tags.pop()
                if not tags:
                    self._tags.pop(key, None)
                logging.error("[Tags] Falha ao salvar tags: %s", exc)
                return False, "invalid"
            return True, "added"

    def remove_tag(self, nick, tag):
        key = self._normalize_nick(nick)
        clean = self._normalize_tag(tag)
        if not key or not clean:
            return False, "invalid"
        with self._lock:
            tags = self._tags.get(key, [])
            match = next((item for item in tags if item.casefold() == clean.casefold()), None)
            if match is None:
                return False, "missing"
            tags.remove(match)
            if not tags:
                self._tags.pop(key, None)
            try:
                self._save()
            except Exception as exc:
                self._tags.setdefault(key, []).append(match)
                logging.error("[Tags] Falha ao salvar tags: %s", exc)
                return False, "invalid"
            return True, "removed"
