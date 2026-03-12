import os
import random
import re
import logging
from collections import defaultdict, deque


class EmoteManager:
    """Gerencia emotes por contexto com anti-repetição global e por canal."""

    DEFAULT_EMOTE = "glorp"
    MOOD_TO_EMOTION = {
        "happy": "hype",
        "angry": "angry",
        "curious": "attention",
        "chaotic": "laugh",
        "tsundere": "mockery",
        "neutral": "neutral",
    }

    def __init__(self, base_path=None, history_size=8):
        self.base_path = base_path or os.getcwd()
        self.history_size = history_size

        self.global_emote_history = deque(maxlen=history_size)
        self.channel_emote_history = defaultdict(lambda: deque(maxlen=history_size))
        self.channel_phrase_history = defaultdict(lambda: deque(maxlen=history_size))
        self.last_selected_emote_by_channel = {}

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

        all_emotes = self.get_all_emotes()
        while tokens:
            last = tokens[-1]
            normalized = self._normalize_token(last)
            if normalized in all_emotes:
                tokens.pop()
                continue
            break

        return " ".join(tokens).strip()

    def remove_known_emotes(self, message):
        """Remove emotes gerados pelo modelo para manter apenas o emote final do sistema."""
        tokens = message.split()
        if not tokens:
            return message

        all_emotes = self.get_all_emotes()
        cleaned_tokens = [token for token in tokens if self._normalize_token(token) not in all_emotes]
        cleaned = " ".join(cleaned_tokens).strip()
        return cleaned if cleaned else message.strip()

    def _normalize_token(self, token):
        return token.strip(".,!?;:()[]{}\"'`*_~").strip()

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

    def _candidate_pool(self, channel, emotion, secondary_emotion=None):
        channel_map = self.channel_emote_map.get(channel.lower(), {})
        candidates = []

        emotions = [emotion]
        if secondary_emotion and secondary_emotion not in (emotion, "neutral"):
            emotions.append(secondary_emotion)
        emotions.append("neutral")

        for key in emotions:
            channel_emotes = channel_map.get(key, [])
            global_emotes = self.global_emote_map.get(key, [])

            # Canal sempre tem prioridade quando houver a mesma emoção disponível.
            if channel_emotes:
                candidates.extend(channel_emotes)
                candidates.extend([e for e in global_emotes if e not in channel_emotes])
            else:
                candidates.extend(global_emotes)

        unique = []
        seen = set()
        for e in candidates:
            if e not in seen:
                seen.add(e)
                unique.append(e)

        return unique or [self.DEFAULT_EMOTE]

    def _resolve_emotions(self, text, mood=None):
        inferred = self.infer_emotion(text)
        mood_emotion = self.MOOD_TO_EMOTION.get((mood or "").lower())

        # O mood "neutral" nunca deve forçar a emoção da mensagem.
        if mood_emotion == "neutral":
            mood_emotion = None

        if inferred == "neutral" and mood_emotion:
            return mood_emotion, None

        return inferred, mood_emotion

    def choose_emote(self, channel, text, mood=None):
        emotion, secondary_emotion = self._resolve_emotions(text, mood=mood)
        candidates = self._candidate_pool(channel, emotion, secondary_emotion=secondary_emotion)

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

        last_channel_emote = channel_hist[-1] if channel_hist else None
        last_global_emote = self.global_emote_history[-1] if self.global_emote_history else None

        self.global_emote_history.append(chosen)
        channel_hist.append(chosen)
        self.last_selected_emote_by_channel[channel.lower()] = chosen

        logging.debug(
            "[Emote] canal=%s mood=%s emotion=%s ultimo_canal=%s ultimo_global=%s candidatos=%s escolhido=%s hist_canal=%s hist_global=%s",
            channel,
            mood,
            f"{emotion}|{secondary_emotion}" if secondary_emotion else emotion,
            last_channel_emote,
            last_global_emote,
            candidates,
            chosen,
            list(channel_hist),
            list(self.global_emote_history),
        )
        return chosen

    def get_debug_state(self, channel):
        normalized_channel = channel.lower()
        channel_hist = list(self.channel_emote_history[normalized_channel])
        return {
            "last_selected_channel": self.last_selected_emote_by_channel.get(normalized_channel),
            "last_channel_emote": channel_hist[-1] if channel_hist else None,
            "last_global_emote": self.global_emote_history[-1] if self.global_emote_history else None,
            "channel_history": channel_hist,
            "global_history": list(self.global_emote_history),
        }

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
            logging.debug("[Emote] Mensagem repetida detectada em #%s, variante aplicada: %s", channel, message)

        hist.append(normalized)
        logging.debug("[Emote] Histórico de frases #%s: %s", channel, list(hist))
        return message
