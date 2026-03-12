import random
import re
import logging
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class MemoryLoop:
    topic: str
    users: List[str] = field(default_factory=list)
    weight: float = 0.5
    last_used: int = 0
    type: str = "running_joke"


class SocialDynamicsEngine:
    LOOP_PROBABILITY = 0.04
    FAVORITE_PROBABILITY = 0.02
    ENEMY_PROBABILITY = 0.015
    SUSPECT_PROBABILITY = 0.01

    MAX_LOOPS = 8
    MIN_LOOP_WEIGHT = 0.2
    LOOP_TTL_MESSAGES = 600
    DEFAULT_STORAGE_PATH = Path("glorpinia_memory_loops.json")

    def __init__(self, storage_path: Optional[Path] = None):
        self.message_count = 0
        self.users_seen = set()
        self.active_loop_for_message: Optional[MemoryLoop] = None
        self.storage_path = Path(storage_path) if storage_path else self.DEFAULT_STORAGE_PATH

        self.memory_loops: List[MemoryLoop] = [
            MemoryLoop(
                topic="moon apostando cookies",
                users=["moongrade"],
                weight=0.8,
                last_used=self.message_count,
                type="running_joke",
            )
        ]
        self._load_memory_loops()
        self._prune_loops(save=False)

        self.drama_state: Dict[str, Optional[str]] = {
            "favorite_of_the_day": None,
            "enemy_of_the_day": None,
            "suspect": None,
            "rivalries": [],
        }

        self.bot_state = {"mood": "neutral", "duration": 0}

    def observe_message(self, author: str, content: str, bot_nick: Optional[str] = None):
        self.message_count += 1
        logging.debug("[SocialDynamics] observe_message count=%s author=%s content=%s", self.message_count, author, content[:120])
        self.users_seen.add(author.lower())

        if self.message_count % 20 == 0:
            for loop in self.memory_loops:
                loop.weight *= 0.97

        self._prune_loops()
        self._roll_memory_loop()
        self._roll_drama_events(author)
        self._update_mood(author=author, content=content, bot_nick=bot_nick)

    def get_injection_payload(self) -> Dict[str, object]:
        memory_loop = None
        if self.active_loop_for_message:
            loop = self.active_loop_for_message
            memory_loop = {"topic": loop.topic, "type": loop.type}
            loop.weight *= 0.9
            loop.last_used = self.message_count
            self._persist_loops()
            self._prune_loops()

        payload = {
            "mood": self.bot_state.get("mood", "neutral"),
            "drama_state": self.drama_state,
            "memory_loop": memory_loop,
        }
        logging.debug("[SocialDynamics] injection_payload=%s", payload)
        return payload

    def _roll_memory_loop(self):
        self.active_loop_for_message = None
        if not self.memory_loops:
            return

        roll = random.random()
        if roll > self.LOOP_PROBABILITY:
            logging.debug("[SocialDynamics] memory_loop roll=%.4f > %.4f (skip)", roll, self.LOOP_PROBABILITY)
            return

        total_weight = sum(max(0.0, loop.weight) for loop in self.memory_loops)
        if total_weight <= 0:
            return

        pick = random.uniform(0, total_weight)
        running = 0.0
        for loop in self.memory_loops:
            running += max(0.0, loop.weight)
            if pick <= running:
                self.active_loop_for_message = loop
                logging.debug(
                    "[SocialDynamics] memory_loop selected topic=%s weight=%.3f last_used=%s",
                    loop.topic,
                    loop.weight,
                    loop.last_used,
                )
                return

    def _roll_drama_events(self, author: str):
        candidates = list(self.users_seen)
        if not candidates:
            return

        if random.random() < self.FAVORITE_PROBABILITY:
            self.drama_state["favorite_of_the_day"] = random.choice(candidates)

        if random.random() < self.ENEMY_PROBABILITY:
            self.drama_state["enemy_of_the_day"] = random.choice(candidates)

        if random.random() < self.SUSPECT_PROBABILITY:
            self.drama_state["suspect"] = random.choice(candidates)

        enemy = self.drama_state.get("enemy_of_the_day")
        favorite = self.drama_state.get("favorite_of_the_day")
        if enemy and favorite and enemy != favorite:
            rivalry = f"{favorite} vs {enemy}"
            if rivalry not in self.drama_state["rivalries"]:
                self.drama_state["rivalries"].append(rivalry)
                self.drama_state["rivalries"] = self.drama_state["rivalries"][-5:]

    def _update_mood(self, author: str, content: str, bot_nick: Optional[str] = None):
        text = (content or "").lower().strip()
        lowered_author = (author or "").lower()
        bot_aliases = {"glorpinia", "glorp", (bot_nick or "").lower().strip()}
        bot_aliases.discard("")

        mood_event = self._infer_contextual_mood_event(text=text, author=lowered_author, bot_aliases=bot_aliases)

        if mood_event:
            self.bot_state["mood"] = mood_event[0]
            self.bot_state["duration"] = mood_event[1]
            logging.debug("[SocialDynamics] mood_updated mood=%s duration=%s", mood_event[0], mood_event[1])
            return

        duration = self.bot_state.get("duration", 0)
        if duration > 0:
            self.bot_state["duration"] = duration - 1
        if self.bot_state.get("duration", 0) <= 0:
            self.bot_state["mood"] = "neutral"
            self.bot_state["duration"] = 0
        logging.debug("[SocialDynamics] mood_state=%s", self.bot_state)

    def _infer_contextual_mood_event(self, text: str, author: str, bot_aliases: set):
        if not text:
            return None

        rude_tokens = {
            "burra", "burro", "idiota", "lixo", "inutil", "otaria", "otário", "ridicula", "ridículo", "bot ruim", "calada", "cala boca"
        }
        praise_tokens = {
            "boa", "mandou bem", "linda", "fofa", "genia", "gênia", "braba", "te amo", "arrasou"
        }
        question_tokens = {"por que", "porque", "como", "explica", "teoria", "qual", "quando"}

        mentions_bot = any(alias and (f"@{alias}" in text or alias in text) for alias in bot_aliases)
        second_person = any(token in text for token in ["vc", "você", "tu", "teu", "tua", "sua", "seu", "te "])
        direct_to_bot = mentions_bot or second_person

        if direct_to_bot and any(token in text for token in rude_tokens):
            return ("angry", 5)

        if direct_to_bot and any(token in text for token in praise_tokens):
            return ("happy", 6)

        if mentions_bot and "?" in text and any(token in text for token in question_tokens):
            return ("curious", 5)

        if re.search(r"\b(caos|anarquia|glitch)\b", text):
            return ("chaotic", 3)

        if re.search(r"\btsundere\b", text):
            return ("tsundere", 4)

        return None

    def add_memory_loop(self, topic: str, users: Optional[List[str]] = None, weight: float = 0.5, loop_type: str = "running_joke"):
        normalized_topic = (topic or "").strip()
        if not normalized_topic:
            return

        for loop in self.memory_loops:
            if loop.topic.lower() == normalized_topic.lower():
                merged_users = sorted(set(loop.users + (users or [])))
                loop.users = merged_users
                loop.weight = max(loop.weight, weight)
                loop.last_used = self.message_count
                logging.debug(
                    "[SocialDynamics] memory_loop refreshed topic=%s users=%s weight=%.3f",
                    loop.topic,
                    loop.users,
                    loop.weight,
                )
                self._persist_loops()
                self._prune_loops()
                return

        self.memory_loops.append(
            MemoryLoop(topic=normalized_topic, users=users or [], weight=weight, last_used=self.message_count, type=loop_type)
        )
        logging.debug(
            "[SocialDynamics] memory_loop created topic=%s users=%s weight=%.3f type=%s",
            normalized_topic,
            users or [],
            weight,
            loop_type,
        )
        self._persist_loops()
        self.memory_loops = self.memory_loops[-self.MAX_LOOPS :]
        self._prune_loops()

    def get_debug_snapshot(self) -> Dict[str, object]:
        active_loop = None
        if self.active_loop_for_message:
            active_loop = {
                "topic": self.active_loop_for_message.topic,
                "type": self.active_loop_for_message.type,
                "weight": round(self.active_loop_for_message.weight, 3),
            }

        return {
            "message_count": self.message_count,
            "users_seen": sorted(self.users_seen),
            "mood": self.bot_state.get("mood", "neutral"),
            "mood_duration": self.bot_state.get("duration", 0),
            "drama_state": dict(self.drama_state),
            "active_memory_loop": active_loop,
            "memory_loops": [
                {
                    "topic": loop.topic,
                    "users": loop.users,
                    "weight": round(loop.weight, 3),
                    "last_used": loop.last_used,
                    "type": loop.type,
                }
                for loop in self.memory_loops
            ],
            "random_roll_parameters": {
                "favorite_probability": self.FAVORITE_PROBABILITY,
                "enemy_probability": self.ENEMY_PROBABILITY,
                "suspect_probability": self.SUSPECT_PROBABILITY,
                "memory_loop_probability": self.LOOP_PROBABILITY,
            },
        }

    def _prune_loops(self, save: bool = True):
        before = len(self.memory_loops)
        retained_loops: List[MemoryLoop] = []
        for loop in self.memory_loops:
            is_stale = self.message_count - loop.last_used > self.LOOP_TTL_MESSAGES
            has_min_weight = loop.weight >= self.MIN_LOOP_WEIGHT
            if is_stale:
                logging.debug(
                    "[SocialDynamics] memory_loop expired topic=%s reason=ttl age=%s ttl=%s",
                    loop.topic,
                    self.message_count - loop.last_used,
                    self.LOOP_TTL_MESSAGES,
                )
                continue
            if not has_min_weight:
                logging.debug(
                    "[SocialDynamics] memory_loop expired topic=%s reason=weight weight=%.3f min=%.3f",
                    loop.topic,
                    loop.weight,
                    self.MIN_LOOP_WEIGHT,
                )
                continue
            retained_loops.append(loop)

        self.memory_loops = retained_loops
        if len(self.memory_loops) > self.MAX_LOOPS:
            self.memory_loops = sorted(self.memory_loops, key=lambda l: l.weight, reverse=True)[: self.MAX_LOOPS]

        changed = len(self.memory_loops) != before
        if changed and save:
            self._persist_loops()

    def _load_memory_loops(self):
        if not self.storage_path.exists():
            self._persist_loops()
            return
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            loaded_loops = []
            for item in raw:
                topic = (item.get("topic") or "").strip()
                if not topic:
                    continue
                loaded_loops.append(
                    MemoryLoop(
                        topic=topic,
                        users=[str(user).lower() for user in item.get("users", []) if user],
                        weight=float(item.get("weight", 0.5)),
                        last_used=int(item.get("last_used", 0)),
                        type=item.get("type", "running_joke"),
                    )
                )
            if loaded_loops:
                self.memory_loops = loaded_loops[-self.MAX_LOOPS :]
            logging.debug("[SocialDynamics] memory_loops loaded path=%s count=%s", self.storage_path, len(self.memory_loops))
        except Exception as exc:
            logging.error("[SocialDynamics] failed loading memory loops path=%s error=%s", self.storage_path, exc)

    def _persist_loops(self):
        serialized = [
            {
                "topic": loop.topic,
                "users": loop.users,
                "weight": loop.weight,
                "last_used": loop.last_used,
                "type": loop.type,
            }
            for loop in self.memory_loops
        ]
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logging.error("[SocialDynamics] failed persisting memory loops path=%s error=%s", self.storage_path, exc)
