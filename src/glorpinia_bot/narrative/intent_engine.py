import re
import unicodedata
from typing import Dict, List


class IntentEngine:
    """Heuristic intent analyzer for Twitch chat messages.

    The engine is intentionally local/deterministic so it can run on every
    message before any LLM call.  It favors small, explainable signals that are
    useful for routing: emotional tone, web-search need, and cookie/economy
    relevance.
    """

    ECONOMIC_INTENT_KEYWORDS: Dict[str, set] = {
        "bet": {
            "aposta", "apostar", "apostei", "apostou", "odd", "odds", "all in", "all-in", "double", "dobrar",
            "slots", "slot", "roleta", "jackpot", "gamble", "gambiar", "arriscar", "bet",
        },
        "debt": {
            "dívida", "divida", "devendo", "devo", "devedor", "devedora", "calote", "pagar", "pagamento",
            "quitar", "cobrar", "cobrança", "cobranca", "multa", "juros", "saldo", "negativo", "falido",
            "debt", "owe", "owing",
        },
        "reward_punishment": {
            "recompensa", "premio", "prêmio", "bonus", "bônus", "punicao", "punição", "penalidade", "castigo",
            "mimo", "taxa", "multar", "prender", "liberar", "cookie", "cookies",
        },
        "explicit_commands": {
            "dar cookie", "dá cookie", "da cookie", "tirar cookie", "remove cookie", "transferir cookie",
            "!cookie", "!cookies", "!pay", "!give", "!bet", "!slots", "!slot", "!apostar",
            "*cookie", "*cookies", "*pay", "*give", "*bet", "*slots", "*slot", "*apostar",
        },
    }

    RUDE_TOKENS = {
        "burra", "burro", "idiota", "lixo", "inutil", "inútil", "otaria", "otário", "ridicula", "ridículo",
        "bot ruim", "calada", "cala boca", "odeio", "horrivel", "horrível",
    }
    PRAISE_TOKENS = {
        "boa", "mandou bem", "linda", "fofa", "genia", "gênia", "braba", "te amo", "arrasou", "perfeita",
        "obrigado", "obrigada", "valeu",
    }
    SAD_TOKENS = {"triste", "sad", "chateado", "chateada", "deprimido", "deprimida", "cry", "chorando"}
    ANGER_TOKENS = {"raiva", "puto", "puta", "irritado", "irritada", "ódio", "odio", "tiltado", "tiltada"}
    CHAOS_TOKENS = {"caos", "anarquia", "glitch", "bugou", "buguei"}
    QUESTION_TOKENS = {"por que", "porque", "como", "explica", "teoria", "qual", "quando", "onde", "quem"}
    SEARCH_TOKENS = {
        "notícia", "noticia", "hoje", "agora", "atual", "último", "ultimo", "recente", "preço", "preco",
        "cotação", "cotacao", "placar", "resultado", "data", "lançamento", "lancamento", "versão", "versao",
        "define", "definição", "definicao", "o que é", "o que e", "quem é", "quem e",
    }
    STOPWORDS = {
        "a", "o", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", "e", "é", "eh", "que", "pra",
        "para", "com", "sem", "por", "no", "na", "nos", "nas", "me", "te", "se", "eu", "tu", "vc", "você",
        "voce", "ele", "ela", "isso", "esse", "essa", "meu", "minha", "seu", "sua", "glorpinia", "glorp",
    }

    def analyze_message(self, channel, author, content, recent_history=None):
        text = (content or "").strip()
        normalized = self._normalize_text(text)
        tokens = self._tokens(normalized)
        entities = self._extract_entities(text, normalized)
        keyword_hits = self._extract_keywords(normalized, tokens)
        secondary_intents: List[str] = []

        economy_relevance, economy_categories = self._economy_relevance(normalized)
        if economy_relevance >= 0.35:
            secondary_intents.append("economy")

        emotion, emotion_score = self._emotion(normalized)
        sentiment = self._sentiment(normalized, emotion, emotion_score)
        should_search_web = self._should_search_web(normalized)

        primary_intent = self._primary_intent(
            normalized=normalized,
            entities=entities,
            economy_relevance=economy_relevance,
            should_search_web=should_search_web,
        )
        if primary_intent != "question" and self._is_question(normalized):
            secondary_intents.append("question")
        if should_search_web and primary_intent != "information_request":
            secondary_intents.append("information_request")
        if entities["mentions"]:
            secondary_intents.append("mention")
        if entities["commands"] and primary_intent != "command":
            secondary_intents.append("command")

        confidence = self._confidence(
            normalized=normalized,
            primary_intent=primary_intent,
            emotion_score=emotion_score,
            economy_relevance=economy_relevance,
            should_search_web=should_search_web,
        )

        return {
            "primary_intent": primary_intent,
            "secondary_intents": self._dedupe(secondary_intents),
            "emotion": emotion,
            "sentiment": sentiment,
            "entities": {
                **entities,
                "channel": self._normalize_channel(channel),
                "author": (author or "").strip(),
                "economy_categories": economy_categories,
            },
            "keywords": keyword_hits,
            "confidence": confidence,
            "should_search_web": should_search_web,
            "economy_relevance": economy_relevance,
        }

    def has_economic_intent(self, text: str) -> bool:
        analysis = self.analyze_message(channel=None, author=None, content=text)
        return analysis["economy_relevance"] >= 0.35

    def _primary_intent(self, normalized, entities, economy_relevance, should_search_web):
        if not normalized:
            return "empty"
        if entities["commands"]:
            return "command"
        if economy_relevance >= 0.65:
            return "economy_action"
        if should_search_web:
            return "information_request"
        if self._is_question(normalized):
            return "question"
        if any(token in normalized for token in self.PRAISE_TOKENS):
            return "praise"
        if any(token in normalized for token in self.RUDE_TOKENS):
            return "complaint"
        return "chat"

    def _emotion(self, normalized):
        if not normalized:
            return "neutral", 0.0
        if any(token in normalized for token in self.RUDE_TOKENS | self.ANGER_TOKENS):
            return "anger", 0.85
        if any(token in normalized for token in self.PRAISE_TOKENS):
            return "joy", 0.8
        if any(token in normalized for token in self.SAD_TOKENS):
            return "sadness", 0.7
        if any(token in normalized for token in self.CHAOS_TOKENS):
            return "chaos", 0.65
        if "tsundere" in normalized:
            return "tsundere", 0.65
        if self._is_question(normalized):
            return "curiosity", 0.55
        return "neutral", 0.35

    def _sentiment(self, normalized, emotion, emotion_score):
        if emotion in {"anger", "sadness"} and emotion_score >= 0.6:
            return "negative"
        if emotion == "joy" and emotion_score >= 0.6:
            return "positive"
        if re.search(r"\b(n[aã]o gostei|ruim|horr[ií]vel|péssim|pessim)\b", normalized):
            return "negative"
        if re.search(r"\b(bom|boa|ótim|otim|excelente|perfeito|perfeita)\b", normalized):
            return "positive"
        return "neutral"

    def _should_search_web(self, normalized):
        if not normalized:
            return False
        if any(token in normalized for token in self.SEARCH_TOKENS):
            return self._is_question(normalized) or "?" in normalized
        if re.search(r"\b(quem|quando|onde|qual|quanto|como)\b", normalized) and re.search(r"\b(202[0-9]|hoje|agora|atual)\b", normalized):
            return True
        return False

    def _economy_relevance(self, normalized):
        categories = []
        score = 0.0
        for category, keywords in self.ECONOMIC_INTENT_KEYWORDS.items():
            if any(keyword in normalized for keyword in keywords):
                categories.append(category)
                score += 0.32 if category != "explicit_commands" else 0.5
        if re.search(r"\b\d+\s*(cookie|cookies|🍪)\b", normalized):
            score += 0.25
        return min(score, 1.0), categories

    def _extract_entities(self, text, normalized):
        mentions = [m.lower() for m in re.findall(r"@([A-Za-z0-9_]{2,25})", text or "")]
        commands = re.findall(r"(?:^|\s)([!*][A-Za-z0-9_]+)", text or "")
        urls = re.findall(r"https?://\S+", text or "")
        numbers = re.findall(r"\b\d+(?:[\.,]\d+)?\b", normalized)
        return {
            "mentions": self._dedupe(mentions),
            "commands": self._dedupe(commands),
            "urls": urls,
            "numbers": numbers,
        }

    def _extract_keywords(self, normalized, tokens):
        keywords = [token for token in tokens if len(token) >= 4 and token not in self.STOPWORDS]
        phrase_hits = []
        for phrase_set in [self.RUDE_TOKENS, self.PRAISE_TOKENS, self.CHAOS_TOKENS, self.SEARCH_TOKENS]:
            phrase_hits.extend([phrase for phrase in phrase_set if " " in phrase and phrase in normalized])
        for keywords_by_category in self.ECONOMIC_INTENT_KEYWORDS.values():
            phrase_hits.extend([kw for kw in keywords_by_category if kw in normalized])
        return self._dedupe(phrase_hits + keywords)[:12]

    def _confidence(self, normalized, primary_intent, emotion_score, economy_relevance, should_search_web):
        if not normalized:
            return 0.0
        score = 0.45
        if primary_intent not in {"chat", "empty"}:
            score += 0.18
        if emotion_score >= 0.6:
            score += 0.12
        if economy_relevance >= 0.35:
            score += 0.15
        if should_search_web:
            score += 0.1
        return min(round(score, 2), 0.95)

    def _is_question(self, normalized):
        return "?" in normalized or any(token in normalized for token in self.QUESTION_TOKENS)

    def _tokens(self, normalized):
        return re.findall(r"[\wÀ-ÿ]+", normalized, flags=re.UNICODE)

    def _normalize_text(self, text):
        normalized = (text or "").lower().replace("’", "'")
        normalized = unicodedata.normalize("NFC", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _normalize_channel(self, channel):
        return (str(channel or "").strip().lower().replace("#", ""))

    def _dedupe(self, values):
        seen = set()
        deduped = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped
