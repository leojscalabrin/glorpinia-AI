import random
import re
import logging
import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional


@dataclass
class MemoryLoop:
    topic: str
    users: List[str] = field(default_factory=list)
    weight: float = 0.5
    last_used: int = 0
    type: str = "running_joke"


@dataclass
class ChannelSocialState:
    message_count: int = 0
    users_seen: set = field(default_factory=set)
    active_loop_for_message: Optional[MemoryLoop] = None
    memory_loops: List[MemoryLoop] = field(default_factory=list)
    drama_state: Dict[str, Optional[str]] = field(
        default_factory=lambda: {
            "favorite_of_the_day": None,
            "enemy_of_the_day": None,
            "suspect": None,
            "rivalries": [],
        }
    )
    bot_state: Dict[str, object] = field(default_factory=lambda: {"mood": "neutral", "duration": 0})
    drama_reset_at: datetime = field(default_factory=datetime.utcnow)


class SocialDynamicsEngine:
    LOOP_PROBABILITY = 0.04
    FAVORITE_PROBABILITY = 0.02
    ENEMY_PROBABILITY = 0.015
    SUSPECT_PROBABILITY = 0.01

    MAX_LOOPS = 8
    MIN_LOOP_WEIGHT = 0.2
    LOOP_TTL_MESSAGES = 600
    DRAMA_RESET_INTERVAL = timedelta(hours=24)
    DEFAULT_STORAGE_PATH = Path("glorpinia_memory_loops.json")

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = Path(storage_path) if storage_path else self.DEFAULT_STORAGE_PATH
        self.channel_states: Dict[str, ChannelSocialState] = {}

    def _normalize_channel(self, channel: Optional[str]) -> str:
        if not channel:
            return "global"
        return str(channel).strip().lower().replace("#", "") or "global"

    def _default_memory_loops(self) -> List[MemoryLoop]:
        return [
            MemoryLoop(
                topic="moon apostando cookies",
                users=["moongrade"],
                weight=0.8,
                last_used=0,
                type="running_joke",
            )
        ]

    def _get_channel_state(self, channel: Optional[str]) -> ChannelSocialState:
        channel_key = self._normalize_channel(channel)
        if channel_key in self.channel_states:
            return self.channel_states[channel_key]

        state = ChannelSocialState(memory_loops=self._default_memory_loops())
        self._load_memory_loops(channel_key, state)
        self._prune_loops(state, channel=channel_key, save=False)
        self.channel_states[channel_key] = state
        return state

    def observe_message(self, channel: str, author: str, content: str, bot_nick: Optional[str] = None):
        state = self._get_channel_state(channel)
        self._maybe_reset_drama_for_interval(state, channel)

        state.message_count += 1
        logging.debug("[SocialDynamics] observe_message channel=%s count=%s author=%s content=%s", channel, state.message_count, author, content[:120])
        state.users_seen.add(author.lower())

        if state.message_count % 20 == 0:
            for loop in state.memory_loops:
                loop.weight *= 0.97

        self._prune_loops(state, channel=channel)
        self._roll_memory_loop(state)
        self._roll_drama_events(state, author)
        self._update_mood(state, author=author, content=content, bot_nick=bot_nick)

    def reset_drama_state(self, channel: str, reason: str = "manual"):
        state = self._get_channel_state(channel)
        state.drama_state = {
            "favorite_of_the_day": None,
            "enemy_of_the_day": None,
            "suspect": None,
            "rivalries": [],
        }
        state.users_seen = set()
        state.bot_state = {"mood": "neutral", "duration": 0}
        state.drama_reset_at = datetime.utcnow()
        logging.info("[SocialDynamics] drama_state reset channel=%s reason=%s", channel, reason)

    def _maybe_reset_drama_for_interval(self, state: ChannelSocialState, channel: str):
        now = datetime.utcnow()
        if (now - state.drama_reset_at) >= self.DRAMA_RESET_INTERVAL:
            self.reset_drama_state(channel, reason="24h_interval")

    def get_injection_payload(self, channel: str) -> Dict[str, object]:
        state = self._get_channel_state(channel)
        memory_loop = None
        if state.active_loop_for_message:
            loop = state.active_loop_for_message
            memory_loop = {"topic": loop.topic, "type": loop.type}
            loop.weight *= 0.9
            loop.last_used = state.message_count
            self._persist_loops(channel, state)
            self._prune_loops(state, channel=channel)

        payload = {
            "mood": state.bot_state.get("mood", "neutral"),
            "drama_state": state.drama_state,
            "memory_loop": memory_loop,
        }
        logging.debug("[SocialDynamics] injection_payload channel=%s payload=%s", channel, payload)
        return payload

    def _roll_memory_loop(self, state: ChannelSocialState):
        state.active_loop_for_message = None
        if not state.memory_loops:
            return

        roll = random.random()
        if roll > self.LOOP_PROBABILITY:
            logging.debug("[SocialDynamics] memory_loop roll=%.4f > %.4f (skip)", roll, self.LOOP_PROBABILITY)
            return

        total_weight = sum(max(0.0, loop.weight) for loop in state.memory_loops)
        if total_weight <= 0:
            return

        pick = random.uniform(0, total_weight)
        running = 0.0
        for loop in state.memory_loops:
            running += max(0.0, loop.weight)
            if pick <= running:
                state.active_loop_for_message = loop
                logging.debug(
                    "[SocialDynamics] memory_loop selected topic=%s weight=%.3f last_used=%s",
                    loop.topic,
                    loop.weight,
                    loop.last_used,
                )
                return

    def _roll_drama_events(self, state: ChannelSocialState, author: str):
        candidates = list(state.users_seen)
        if not candidates:
            return

        if random.random() < self.FAVORITE_PROBABILITY:
            state.drama_state["favorite_of_the_day"] = random.choice(candidates)

        if random.random() < self.ENEMY_PROBABILITY:
            state.drama_state["enemy_of_the_day"] = random.choice(candidates)

        if random.random() < self.SUSPECT_PROBABILITY:
            state.drama_state["suspect"] = random.choice(candidates)

        enemy = state.drama_state.get("enemy_of_the_day")
        favorite = state.drama_state.get("favorite_of_the_day")
        if enemy and favorite and enemy != favorite:
            rivalry = f"{favorite} vs {enemy}"
            if rivalry not in state.drama_state["rivalries"]:
                state.drama_state["rivalries"].append(rivalry)
                state.drama_state["rivalries"] = state.drama_state["rivalries"][-5:]

    def _update_mood(self, state: ChannelSocialState, author: str, content: str, bot_nick: Optional[str] = None):
        text = (content or "").lower().strip()
        lowered_author = (author or "").lower()
        bot_aliases = {"glorpinia", "glorp", (bot_nick or "").lower().strip()}
        bot_aliases.discard("")

        mood_event = self._infer_contextual_mood_event(text=text, author=lowered_author, bot_aliases=bot_aliases)

        if mood_event:
            state.bot_state["mood"] = mood_event[0]
            state.bot_state["duration"] = mood_event[1]
            logging.debug("[SocialDynamics] mood_updated mood=%s duration=%s", mood_event[0], mood_event[1])
            return

        duration = state.bot_state.get("duration", 0)
        if duration > 0:
            state.bot_state["duration"] = duration - 1
        if state.bot_state.get("duration", 0) <= 0:
            state.bot_state["mood"] = "neutral"
            state.bot_state["duration"] = 0
        logging.debug("[SocialDynamics] mood_state=%s", state.bot_state)

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

    def add_memory_loop(self, channel: str, topic: str, users: Optional[List[str]] = None, weight: float = 0.5, loop_type: str = "running_joke"):
        state = self._get_channel_state(channel)
        normalized_topic = (topic or "").strip()
        if not normalized_topic:
            return

        for loop in state.memory_loops:
            if loop.topic.lower() == normalized_topic.lower():
                merged_users = sorted(set(loop.users + (users or [])))
                loop.users = merged_users
                loop.weight = max(loop.weight, weight)
                loop.last_used = state.message_count
                logging.debug(
                    "[SocialDynamics] memory_loop refreshed topic=%s users=%s weight=%.3f",
                    loop.topic,
                    loop.users,
                    loop.weight,
                )
                self._persist_loops(channel, state)
                self._prune_loops(state, channel=channel)
                return

        state.memory_loops.append(
            MemoryLoop(topic=normalized_topic, users=users or [], weight=weight, last_used=state.message_count, type=loop_type)
        )
        logging.debug(
            "[SocialDynamics] memory_loop created topic=%s users=%s weight=%.3f type=%s",
            normalized_topic,
            users or [],
            weight,
            loop_type,
        )
        self._persist_loops(channel, state)
        state.memory_loops = state.memory_loops[-self.MAX_LOOPS :]
        self._prune_loops(state, channel=channel)

    def get_debug_snapshot(self, channel: str) -> Dict[str, object]:
        state = self._get_channel_state(channel)
        active_loop = None
        if state.active_loop_for_message:
            active_loop = {
                "topic": state.active_loop_for_message.topic,
                "type": state.active_loop_for_message.type,
                "weight": round(state.active_loop_for_message.weight, 3),
            }

        return {
            "message_count": state.message_count,
            "users_seen": sorted(state.users_seen),
            "mood": state.bot_state.get("mood", "neutral"),
            "mood_duration": state.bot_state.get("duration", 0),
            "drama_state": dict(state.drama_state),
            "active_memory_loop": active_loop,
            "memory_loops": [
                {
                    "topic": loop.topic,
                    "users": loop.users,
                    "weight": round(loop.weight, 3),
                    "last_used": loop.last_used,
                    "type": loop.type,
                }
                for loop in state.memory_loops
            ],
            "random_roll_parameters": {
                "favorite_probability": self.FAVORITE_PROBABILITY,
                "enemy_probability": self.ENEMY_PROBABILITY,
                "suspect_probability": self.SUSPECT_PROBABILITY,
                "memory_loop_probability": self.LOOP_PROBABILITY,
            },
        }

    def _prune_loops(self, state: ChannelSocialState, channel: str, save: bool = True):
        before = len(state.memory_loops)
        retained_loops: List[MemoryLoop] = []
        for loop in state.memory_loops:
            is_stale = state.message_count - loop.last_used > self.LOOP_TTL_MESSAGES
            has_min_weight = loop.weight >= self.MIN_LOOP_WEIGHT
            if is_stale:
                logging.debug(
                    "[SocialDynamics] memory_loop expired topic=%s reason=ttl age=%s ttl=%s",
                    loop.topic,
                    state.message_count - loop.last_used,
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

        state.memory_loops = retained_loops
        if len(state.memory_loops) > self.MAX_LOOPS:
            state.memory_loops = sorted(state.memory_loops, key=lambda l: l.weight, reverse=True)[: self.MAX_LOOPS]

        changed = len(state.memory_loops) != before
        if changed and save:
            self._persist_loops(channel, state)

    def _storage_path_for_channel(self, channel: str) -> Path:
        channel_key = self._normalize_channel(channel)
        stem = self.storage_path.stem
        suffix = self.storage_path.suffix or ".json"
        return self.storage_path.with_name(f"{stem}_{channel_key}{suffix}")

    def _load_memory_loops(self, channel: str, state: ChannelSocialState):
        channel_path = self._storage_path_for_channel(channel)
        if not channel_path.exists():
            self._persist_loops(channel, state)
            return
        try:
            raw = json.loads(channel_path.read_text(encoding="utf-8"))
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
                state.memory_loops = loaded_loops[-self.MAX_LOOPS :]
            logging.debug("[SocialDynamics] memory_loops loaded path=%s count=%s", channel_path, len(state.memory_loops))
        except Exception as exc:
            logging.error("[SocialDynamics] failed loading memory loops path=%s error=%s", channel_path, exc)

    def _persist_loops(self, channel: str, state: ChannelSocialState):
        serialized = [
            {
                "topic": loop.topic,
                "users": loop.users,
                "weight": loop.weight,
                "last_used": loop.last_used,
                "type": loop.type,
            }
            for loop in state.memory_loops
        ]
        try:
            channel_path = self._storage_path_for_channel(channel)
            channel_path.parent.mkdir(parents=True, exist_ok=True)
            channel_path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logging.error("[SocialDynamics] failed persisting memory loops channel=%s error=%s", channel, exc)
