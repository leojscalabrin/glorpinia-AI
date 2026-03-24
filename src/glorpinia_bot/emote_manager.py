import os
import random
import re
import logging
from collections import defaultdict, deque


class EmoteManager:
    """Gerencia emotes por contexto com anti-repetição global e por canal."""

    def __init__(self, base_path=None, history_size=8):
        self.base_path = base_path or os.getcwd()
        self.history_size = history_size

        self.global_emote_history = deque(maxlen=history_size)
        self.channel_emote_history = defaultdict(lambda: deque(maxlen=history_size))
        self.channel_phrase_history = defaultdict(lambda: deque(maxlen=history_size))
        self.channel_emotion_history = defaultdict(lambda: deque(maxlen=history_size))
        self.last_selected_emote_by_channel = {}
        self.last_resolved_emotion_by_channel = {}

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
            return {}

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

    def strip_trailing_emotion_label(self, message):
        """
        Remove rótulo textual de emoção no fim da mensagem.
        Exemplos:
          - "... código alterado! Suspicion" -> "... código alterado!"
          - "... código alterado! Suspicion Kappa" -> "... código alterado! Kappa"
        """
        tokens = (message or "").split()
        if not tokens:
            return message

        emotion_labels = self._get_known_emotion_labels()
        if not emotion_labels:
            return message

        last_token = tokens[-1]
        last_normalized = self._normalize_token(last_token).lower()
        if last_normalized in emotion_labels:
            logging.debug("[Emote] trailing_emotion_label_removed mode=label_only label=%s", last_normalized)
            return " ".join(tokens[:-1]).strip()

        if len(tokens) >= 2:
            penultimate_normalized = self._normalize_token(tokens[-2]).lower()
            final_emote_normalized = self._normalize_token(tokens[-1])
            all_emotes = self.get_all_emotes()
            if penultimate_normalized in emotion_labels and final_emote_normalized in all_emotes:
                logging.debug(
                    "[Emote] trailing_emotion_label_removed mode=label_plus_emote label=%s",
                    penultimate_normalized,
                )
                return " ".join(tokens[:-2] + [tokens[-1]]).strip()

        return message

    def _normalize_token(self, token):
        return token.strip(".,!?;:()[]{}\"'`*_~").strip()

    def get_all_emotes(self):
        pool = set()
        for values in self.global_emote_map.values():
            pool.update(values)
        for cmap in self.channel_emote_map.values():
            for values in cmap.values():
                pool.update(values)
        return pool

    def _get_known_emotion_labels(self):
        labels = set(self.global_emote_map.keys())
        for cmap in self.channel_emote_map.values():
            labels.update(cmap.keys())
        return labels

    def infer_emotion(self, text):
        t = (text or "").lower()
        score = defaultdict(int)

        # Mapeamento por CONTEXTO de emote (emoção + ação/situação de chat).
        rule_map = {
            "laugh": [r"\b(kkk+|haha+|ri\w+|piada|meme|zuera|engra[çc])\b"],
            "sad": [r"\b(triste|sad|pena|depress|que ruim|droga|luto|chor)\b"],
            "angry": [r"\b(raiva|[óo]dio|irrit|burro|rid[íi]culo|palha[çc]ada|tilt|nervos[oa])\b"],
            "hype": [r"\b(bora|vamo|boa+|insano|brabo|letsgo|hype|comemora)\b"],
            "cute": [r"\b(fof[oa]|lind[oa]|querid|meu bem|awn|nhom)\b"],
            "suspicion": [r"\b(sus|suspeit|estranho|investiga|desconfi)\b"],
            "scared": [r"\b(medo|assust|tenso|socorro|pavor|cagac[oã])\b"],
            "gambling": [r"\b(gamba|aposta|odd|cassino|slot|roleta|bet)\b"],
            "smart": [r"\b(teoria|evid[êe]ncia|l[óo]gica|an[áa]lise|estrat[ée]gia)\b"],
            "greeting": [r"\b(oi+|ol[áa]|salve|bom dia|boa tarde|boa noite|eae|hey)\b"],
            "farewell": [r"\b(fui|tchau|flw|até mais|vou nessa|partiu|indo nessa)\b"],
            "arrival": [r"\b(cheguei|acabei de chegar|to on|entrei|voltei)\b"],
            "attention": [r"\b(olha|aten[çc][aã]o|escuta|psiu|ei)\b"],
            "checking": [r"\b(modcheck|confere|checando|cad[eê]|onde t[aá])\b"],
            "waiting": [r"\b(espera|aguarda|esperando|j[áa] volto|fila)\b"],
            "running": [r"\b(corre|correndo|run|rush|vaza)\b"],
            "thinking": [r"\b(hmm|pensando|deixa eu ver|talvez|ser[aá])\b"],
            "sleep": [r"\b(sono|dormir|mimir|boa noite|cansad[oa])\b"],
            "music": [r"\b(m[úu]sica|som|playlist|dj|batida)\b"],
            "clap": [r"\b(aplaus|palmas|brabo|mandou bem)\b"],
            "fight": [r"\b(briga|x1|treta|porrada|duelo)\b"],
            "eating": [r"\b(comendo|comi|lanche|janta|almo[çc]o|fome)\b"],
            "shy": [r"\b(vergonha|t[ií]mid|sem gra[çc]a)\b"],
            "shock": [r"\b(chocado|nossa|caraca|mentira|n[aã]o creio)\b"],
            "relief": [r"\b(ufa|ainda bem|al[ií]vio|deu bom)\b"],
        }

        for emotion, patterns in rule_map.items():
            for pattern in patterns:
                if re.search(pattern, t):
                    score[emotion] += 2

        if "?" in t:
            score["attention"] += 1

        if not score:
            return "neutral", None

        ranked = sorted(score.items(), key=lambda item: item[1], reverse=True)
        primary = ranked[0][0]
        secondary = ranked[1][0] if len(ranked) > 1 and ranked[1][1] == ranked[0][1] else None
        return primary, secondary

    def _candidate_pool(self, channel, emotion, secondary_emotion=None):
        normalized_channel = (channel or "").lower()
        channel_map = self.channel_emote_map.get(normalized_channel, {})
        has_channel_config = normalized_channel in self.channel_emote_map
        candidates = []

        emotions = [emotion]
        if secondary_emotion and secondary_emotion not in (emotion, "neutral"):
            emotions.append(secondary_emotion)
        emotions.append("neutral")

        for key in emotions:
            channel_emotes = channel_map.get(key, [])
            global_emotes = self.global_emote_map.get(key, [])

            # Se o canal tiver emotes para a emoção, usa apenas os do canal.
            # Se o canal existir mas não tiver a emoção, cai no global para não ficar sem opção.
            if channel_emotes:
                candidates.extend(channel_emotes)
            elif has_channel_config:
                candidates.extend(global_emotes)
            else:
                candidates.extend(global_emotes)

        unique = []
        seen = set()
        for e in candidates:
            if e not in seen:
                seen.add(e)
                unique.append(e)

        return unique

    def _resolve_emotions(self, text, mood=None):
        """
        Resolve emoção exclusivamente pelo contexto textual da mensagem.
        O parâmetro `mood` é mantido apenas por compatibilidade de assinatura.
        """
        inferred_primary, inferred_secondary = self.infer_emotion(text)

        mood_map = {
            "happy": "cute",
            "angry": "angry",
            "curious": "attention",
            "chaotic": "hype",
            "tsundere": "mockery",
            "neutral": "neutral",
        }
        mood_emotion = mood_map.get((mood or "").lower())

        if inferred_primary == "neutral" and mood_emotion:
            logging.debug(
                "[Emote] emotion_resolve source=mood_fallback mood=%s inferred=%s resolved=%s",
                mood,
                inferred_primary,
                mood_emotion,
            )
            return mood_emotion, None

        if mood_emotion and mood_emotion not in {inferred_primary, "neutral"}:
            logging.debug(
                "[Emote] emotion_resolve source=text_plus_mood mood=%s inferred=%s secondary=%s",
                mood,
                inferred_primary,
                mood_emotion,
            )
            return inferred_primary, mood_emotion

        logging.debug(
            "[Emote] emotion_resolve source=text_only mood=%s inferred_primary=%s inferred_secondary=%s",
            mood,
            inferred_primary,
            inferred_secondary,
        )
        return inferred_primary, inferred_secondary

    def choose_emote(self, channel, text, mood=None, context_text=None):
        analysis_text = " ".join([p for p in [context_text, text] if p])
        emotion, secondary_emotion = self._resolve_emotions(analysis_text, mood=mood)
        logging.debug(
            "[Emote][Realtime] canal=%s emocao_escolhida=%s emocao_secundaria=%s mood=%s texto_analise=%s",
            channel,
            emotion,
            secondary_emotion,
            mood,
            (analysis_text or "")[:180],
        )
        candidates = self._candidate_pool(channel, emotion, secondary_emotion=secondary_emotion)

        channel_hist = self.channel_emote_history[channel.lower()]
        blocked = set(channel_hist) | set(self.global_emote_history)

        non_repeated = [e for e in candidates if e not in blocked]
        if not non_repeated:
            non_repeated = [e for e in candidates if not channel_hist or e != channel_hist[-1]]
        if not non_repeated:
            non_repeated = candidates[:]

        if not non_repeated:
            logging.debug("[Emote] Nenhum emote encontrado para canal=%s emotion=%s", channel, emotion)
            return ""

        chosen = random.choice(non_repeated)
        if chosen in blocked:
            alternatives = [e for e in candidates if e not in blocked and e != chosen]
            if alternatives:
                chosen = random.choice(alternatives)
            elif candidates:
                chosen = candidates[0]
            else:
                logging.debug("[Emote] Nenhuma alternativa de emote disponível para canal=%s", channel)
                return ""

        last_channel_emote = channel_hist[-1] if channel_hist else None
        last_global_emote = self.global_emote_history[-1] if self.global_emote_history else None

        self.global_emote_history.append(chosen)
        channel_hist.append(chosen)
        self.channel_emotion_history[channel.lower()].append(emotion)
        self.last_selected_emote_by_channel[channel.lower()] = chosen
        self.last_resolved_emotion_by_channel[channel.lower()] = {
            "primary": emotion,
            "secondary": secondary_emotion,
            "mood": mood,
        }

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
            "last_resolved_emotion": self.last_resolved_emotion_by_channel.get(normalized_channel),
            "last_channel_emote": channel_hist[-1] if channel_hist else None,
            "last_global_emote": self.global_emote_history[-1] if self.global_emote_history else None,
            "emotion_history": list(self.channel_emotion_history[normalized_channel]),
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
