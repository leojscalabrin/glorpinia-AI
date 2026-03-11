import os
import random
import re
from collections import defaultdict, deque


class EmoteManager:
    """Gerencia emotes por contexto com anti-repetição global e por canal."""

    DEFAULT_EMOTE = "glorp"

    def __init__(self, base_path=None, history_size=8):
        self.base_path = base_path or os.getcwd()
        self.history_size = history_size

        self.global_emote_history = deque(maxlen=history_size)
        self.channel_emote_history = defaultdict(lambda: deque(maxlen=history_size))
        self.channel_phrase_history = defaultdict(lambda: deque(maxlen=history_size))

        self.global_emote_map = self._load_emote_map(os.path.join(self.base_path, "emotes_global.txt"))
        self.channel_emote_map = self._load_channel_maps(os.path.join(self.base_path, "emotes_channels.txt"))
        self.glitch_lines = self._load_list(os.path.join(self.base_path, "glitches.txt"))

    def _load_list(self, file_path):
        if not os.path.exists(file_path):
            return []

        rows = []
        with open(file_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                rows.append(line)
        return rows

    def _load_emote_map(self, file_path):
        emote_map = defaultdict(list)
        if not os.path.exists(file_path):
            emote_map["neutral"] = [self.DEFAULT_EMOTE]
            return dict(emote_map)

        with open(file_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                emotion, emotes = line.split(":", 1)
                emotion = emotion.strip().lower()
                parsed = [e.strip() for e in emotes.split(",") if e.strip()]
                if parsed:
                    emote_map[emotion].extend(parsed)

        if not emote_map:
            emote_map["neutral"] = [self.DEFAULT_EMOTE]

        return dict(emote_map)

    def _load_channel_maps(self, file_path):
        channel_maps = {}
        if not os.path.exists(file_path):
            return channel_maps

        current_channel = None
        temp_map = defaultdict(list)

        with open(file_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue

                if line.startswith("[") and line.endswith("]"):
                    if current_channel and temp_map:
                        channel_maps[current_channel] = dict(temp_map)
                    current_channel = line[1:-1].strip().lower()
                    temp_map = defaultdict(list)
                    continue

                if ":" in line and current_channel:
                    emotion, emotes = line.split(":", 1)
                    emotion = emotion.strip().lower()
                    parsed = [e.strip() for e in emotes.split(",") if e.strip()]
                    if parsed:
                        temp_map[emotion].extend(parsed)

        if current_channel and temp_map:
            channel_maps[current_channel] = dict(temp_map)

        return channel_maps

    def strip_trailing_emote(self, message):
        tokens = message.split()
        if not tokens:
            return message
        last = tokens[-1]
        if last in self.get_all_emotes():
            return " ".join(tokens[:-1]).strip()
        return message

    def get_all_emotes(self):
        pool = set()
        for values in self.global_emote_map.values():
            pool.update(values)
        for cmap in self.channel_emote_map.values():
            for values in cmap.values():
                pool.update(values)
        pool.add(self.DEFAULT_EMOTE)
        return pool

    def infer_emotion(self, text):
        t = text.lower()
        if any(k in t for k in ["kkk", "haha", "rs", "engra", "zuera", "piada"]):
            return "laugh"
        if any(k in t for k in ["triste", "pena", "medo", "droga", "poxa", "que ruim"]):
            return "sad"
        if any(k in t for k in ["raiva", "ódio", "irrit", "burro", "ridículo", "calado"]):
            return "angry"
        if any(k in t for k in ["bora", "vamo", "boa", "top", "insano", "brabo"]):
            return "hype"
        if any(k in t for k in ["fofo", "amo", "lindo", "obg", "valeu", "querid"]):
            return "cute"
        return "neutral"

    def _candidate_pool(self, channel, emotion):
        channel_map = self.channel_emote_map.get(channel.lower(), {})
        candidates = []

        for key in (emotion, "neutral"):
            candidates.extend(channel_map.get(key, []))
            candidates.extend(self.global_emote_map.get(key, []))

        unique = []
        seen = set()
        for e in candidates:
            if e not in seen:
                seen.add(e)
                unique.append(e)

        return unique or [self.DEFAULT_EMOTE]

    def choose_emote(self, channel, text):
        emotion = self.infer_emotion(text)
        candidates = self._candidate_pool(channel, emotion)

        channel_hist = self.channel_emote_history[channel.lower()]
        blocked = set(channel_hist) | set(self.global_emote_history)

        non_repeated = [e for e in candidates if e not in blocked]
        if not non_repeated:
            non_repeated = [e for e in candidates if not channel_hist or e != channel_hist[-1]]
        if not non_repeated:
            non_repeated = [self.DEFAULT_EMOTE]

        chosen = random.choice(non_repeated)
        if chosen in blocked:
            alternatives = [e for e in candidates if e not in blocked and e != chosen]
            if alternatives:
                chosen = random.choice(alternatives)
            elif candidates:
                chosen = candidates[0]
            else:
                chosen = self.DEFAULT_EMOTE

        self.global_emote_history.append(chosen)
        channel_hist.append(chosen)
        return chosen

    def ensure_unique_phrase(self, channel, message):
        normalized = re.sub(r"\s+", " ", message.strip().lower())
        hist = self.channel_phrase_history[channel.lower()]

        if normalized in hist:
            variants = [
                "tô variando o script cósmico aqui",
                "isso foi recalculado pela nave",
                "nova timeline ativada",
                "versão turbo dessa resposta",
            ]
            message = f"{message.rstrip('.!?')} ({random.choice(variants)})"
            normalized = re.sub(r"\s+", " ", message.strip().lower())

        hist.append(normalized)
        return message
