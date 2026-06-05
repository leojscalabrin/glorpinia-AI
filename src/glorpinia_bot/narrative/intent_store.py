import json
import logging
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional


class LearnedIntentStore:
    """SQLite-backed store for learned intent proposals.

    Learned intents are created as proposals first. They only become active when
    an admin approves them or when repeated similar messages raise confidence
    above a high threshold and no blocked words are present.
    """

    ACTIVE_THRESHOLD = 0.85
    INITIAL_CONFIDENCE = 0.38
    MAX_EXAMPLES = 5
    DECAY_AFTER_DAYS = 30
    DECAY_FACTOR = 0.92

    BLOCKED_WORDS = {
        "senha", "password", "token", "oauth", "secret", "segredo", "api_key",
        "apikey", "cpf", "cnpj", "cartao", "cartão", "creditcard", "endereco",
        "endereço", "telefone", "email", "e-mail", "pix", "banco", "conta",
        "admin", "mod", "moderador", "ban", "banir", "timeout", "delete",
        "deletar", "shutdown", "desligar", "shell", "exec", "eval",
    }

    STOPWORDS = {
        "a", "o", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", "e",
        "é", "eh", "que", "pra", "para", "com", "sem", "por", "no", "na", "nos",
        "nas", "me", "te", "se", "eu", "tu", "vc", "você", "voce", "ele", "ela",
        "isso", "esse", "essa", "meu", "minha", "seu", "sua", "glorpinia", "glorp",
        "kkk", "kkkk", "haha", "rs", "sim", "não", "nao", "tipo", "mano",
    }

    def __init__(self, db_path: str = "glorpinia_memory.db", active_threshold: float = ACTIVE_THRESHOLD):
        self.db_path = db_path
        self.active_threshold = active_threshold
        self._initialize_db()

    def _initialize_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS learned_intents (
                intent_name TEXT NOT NULL,
                keywords TEXT,
                examples TEXT,
                emotion_hint TEXT,
                confidence REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'proposed',
                channel TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT,
                PRIMARY KEY (channel, intent_name)
            )
            """
        )
        conn.commit()
        conn.close()

    def propose_from_interaction(self, channel: str, content: str, intent_analysis: Optional[Dict] = None):
        text = (content or "").strip()
        if not text or text.startswith(("*", "!")) or len(text) < 8:
            return None

        normalized = self._normalize_text(text)
        if self._contains_blocked_words(normalized):
            logging.debug("[IntentStore] proposta ignorada por palavra bloqueada channel=%s", channel)
            return None

        keywords = self._candidate_keywords(normalized, intent_analysis)
        if len(keywords) < 2:
            return None

        channel = self._normalize_channel(channel)
        intent_name = self._intent_name(keywords)
        emotion_hint = (intent_analysis or {}).get("emotion") or "neutral"
        now = self._now()

        similar = self._find_similar(channel, keywords)
        if similar:
            intent_name = similar["intent_name"]
            merged_keywords = self._dedupe(similar["keywords"] + keywords)[:12]
            examples = self._dedupe(similar["examples"] + [text])[-self.MAX_EXAMPLES :]
            overlap = self._keyword_overlap_ratio(similar["keywords"], keywords)
            new_confidence = min(0.95, similar["confidence"] + 0.08 + (0.07 * overlap))
            status = self._next_status(similar["status"], intent_name, merged_keywords, examples, new_confidence)
            self._upsert_intent(
                channel=channel,
                intent_name=intent_name,
                keywords=merged_keywords,
                examples=examples,
                emotion_hint=emotion_hint or similar["emotion_hint"],
                confidence=new_confidence,
                status=status,
                created_at=similar["created_at"],
                updated_at=now,
            )
            return {"intent_name": intent_name, "status": status, "confidence": round(new_confidence, 3)}

        confidence = min(0.5, max(self.INITIAL_CONFIDENCE, (intent_analysis or {}).get("confidence", 0.0) * 0.55))
        self._upsert_intent(
            channel=channel,
            intent_name=intent_name,
            keywords=keywords,
            examples=[text],
            emotion_hint=emotion_hint,
            confidence=confidence,
            status="proposed",
            created_at=now,
            updated_at=now,
        )
        return {"intent_name": intent_name, "status": "proposed", "confidence": round(confidence, 3)}

    def list_intents(self, channel: str, status: Optional[str] = None, limit: int = 8) -> List[Dict]:
        channel = self._normalize_channel(channel)
        status_aliases = {"pending": "proposed", "approved": "active"}
        status = status_aliases.get(status, status)
        params = [channel]
        where = "WHERE channel=?"
        if status in {"proposed", "active", "rejected"}:
            where += " AND status=?"
            params.append(status)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            f"""
            SELECT intent_name, keywords, examples, emotion_hint, confidence, status, channel, created_at, updated_at
            FROM learned_intents
            {where}
            ORDER BY status='proposed' DESC, confidence DESC, updated_at DESC
            LIMIT ?
            """,
            params + [limit],
        )
        rows = [self._row_to_dict(row) for row in c.fetchall()]
        conn.close()
        return rows

    def approve_intent(self, channel: str, intent_name: str) -> bool:
        return self._set_status(channel, intent_name, "active")

    def reject_intent(self, channel: str, intent_name: str) -> bool:
        return self._set_status(channel, intent_name, "rejected")

    def clear_intents(self, channel: str) -> int:
        channel = self._normalize_channel(channel)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "DELETE FROM learned_intents WHERE channel=?",
            (channel,),
        )
        changed = c.rowcount
        conn.commit()
        conn.close()
        return changed

    def match_active_intents(self, channel: str, normalized_text: str, tokens: Optional[Iterable[str]] = None) -> List[Dict]:
        channel = self._normalize_channel(channel)
        token_set = set(tokens or self._tokens(normalized_text))
        if not token_set:
            return []

        rows = self.list_intents(channel, status="active", limit=25)
        matches = []
        for row in rows:
            keywords = set(row["keywords"])
            if not keywords:
                continue
            overlap = len(keywords & token_set)
            phrase_hit = any(" " in kw and kw in normalized_text for kw in keywords)
            if overlap >= 2 or phrase_hit:
                score = min(1.0, row["confidence"] + (0.04 * overlap))
                matches.append({**row, "match_score": round(score, 3)})
                self._touch_intent(channel, row["intent_name"])

        matches.sort(key=lambda row: row["match_score"], reverse=True)
        return matches[:3]

    def apply_confidence_decay(self, channel: Optional[str] = None) -> int:
        cutoff = datetime.utcnow() - timedelta(days=self.DECAY_AFTER_DAYS)
        params = []
        where = "WHERE status IN ('proposed', 'active') AND updated_at < ?"
        params.append(cutoff.isoformat())
        if channel:
            where += " AND channel=?"
            params.append(self._normalize_channel(channel))

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            f"""
            UPDATE learned_intents
            SET confidence = MAX(0, confidence * ?),
                status = CASE WHEN status='active' AND confidence * ? < ? THEN 'proposed' ELSE status END,
                updated_at = ?
            {where}
            """,
            [self.DECAY_FACTOR, self.DECAY_FACTOR, self.active_threshold, self._now()] + params,
        )
        changed = c.rowcount
        conn.commit()
        conn.close()
        return changed

    def _next_status(self, current_status, intent_name, keywords, examples, confidence):
        if current_status in {"active", "rejected"}:
            return current_status
        if confidence >= self.active_threshold and not self._contains_blocked_words(" ".join([intent_name] + keywords + examples)):
            return "active"
        return "proposed"

    def _upsert_intent(self, channel, intent_name, keywords, examples, emotion_hint, confidence, status, created_at, updated_at):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """
            INSERT OR REPLACE INTO learned_intents (
                intent_name, keywords, examples, emotion_hint, confidence, status, channel, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent_name,
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(examples, ensure_ascii=False),
                emotion_hint,
                float(confidence),
                status,
                channel,
                created_at,
                updated_at,
            ),
        )
        conn.commit()
        conn.close()

    def _set_status(self, channel, intent_name, status):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """
            UPDATE learned_intents
            SET status=?, updated_at=?
            WHERE channel=? AND intent_name=?
            """,
            (status, self._now(), self._normalize_channel(channel), intent_name),
        )
        changed = c.rowcount > 0
        conn.commit()
        conn.close()
        return changed

    def _touch_intent(self, channel, intent_name):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            "UPDATE learned_intents SET updated_at=? WHERE channel=? AND intent_name=?",
            (self._now(), channel, intent_name),
        )
        conn.commit()
        conn.close()

    def _find_similar(self, channel, keywords):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """
            SELECT intent_name, keywords, examples, emotion_hint, confidence, status, channel, created_at, updated_at
            FROM learned_intents
            WHERE channel=? AND status != 'rejected'
            ORDER BY updated_at DESC
            """,
            (channel,),
        )
        rows = [self._row_to_dict(row) for row in c.fetchall()]
        conn.close()

        for row in rows:
            if self._keyword_overlap_ratio(row["keywords"], keywords) >= 0.45:
                return row
        return None

    def _row_to_dict(self, row):
        return {
            "intent_name": row["intent_name"],
            "keywords": self._loads_json_list(row["keywords"]),
            "examples": self._loads_json_list(row["examples"]),
            "emotion_hint": row["emotion_hint"],
            "confidence": float(row["confidence"] or 0),
            "status": row["status"],
            "channel": row["channel"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _candidate_keywords(self, normalized, intent_analysis):
        analysis_keywords = (intent_analysis or {}).get("keywords") or []
        tokens = self._tokens(normalized)
        keywords = [kw for kw in analysis_keywords if self._valid_keyword(kw)]
        keywords.extend([token for token in tokens if self._valid_keyword(token)])
        return self._dedupe(keywords)[:10]

    def _valid_keyword(self, word):
        clean = self._normalize_text(word)
        return len(clean) >= 4 and clean not in self.STOPWORDS and clean not in self.BLOCKED_WORDS

    def _intent_name(self, keywords):
        slug = "_".join(re.sub(r"[^a-z0-9]+", "", self._strip_accents(kw)) for kw in keywords[:3])
        slug = re.sub(r"_+", "_", slug).strip("_")[:48] or "generic"
        return f"learned_{slug}"

    def _keyword_overlap_ratio(self, existing, candidate):
        left = set(existing)
        right = set(candidate)
        if not left or not right:
            return 0.0
        return len(left & right) / max(1, min(len(left), len(right)))

    def _contains_blocked_words(self, text):
        normalized = self._normalize_text(text)
        tokens = set(self._tokens(normalized))
        return bool(tokens & self.BLOCKED_WORDS)

    def _tokens(self, normalized):
        return re.findall(r"[\wÀ-ÿ]+", normalized, flags=re.UNICODE)

    def _normalize_text(self, text):
        normalized = (text or "").lower().replace("’", "'")
        normalized = unicodedata.normalize("NFC", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _strip_accents(self, text):
        return "".join(
            char for char in unicodedata.normalize("NFKD", text or "")
            if not unicodedata.combining(char)
        )

    def _normalize_channel(self, channel):
        return str(channel or "").strip().lower().replace("#", "")

    def _loads_json_list(self, value):
        try:
            loaded = json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        return loaded if isinstance(loaded, list) else []

    def _dedupe(self, values):
        seen = set()
        deduped = []
        for value in values:
            clean = self._normalize_text(value)
            if not clean or clean in seen:
                continue
            seen.add(clean)
            deduped.append(clean)
        return deduped

    def _now(self):
        return datetime.utcnow().isoformat()
