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
    examples: List[str] = field(default_factory=list)


@dataclass
class UserSocialProfile:
    positive_interactions: float = 0.0
    negative_interactions: float = 0.0
    teasing_style: str = "neutral"
    trusted_joke_level: float = 0.0
    last_emotion: str = "neutral"
    last_updated_message: int = 0

@dataclass
class ChannelSocialState:
    message_count: int = 0
    users_seen: set = field(default_factory=set)
    active_loop_for_message: Optional[MemoryLoop] = None
    memory_loops: List[MemoryLoop] = field(default_factory=list)
    user_profiles: Dict[str, UserSocialProfile] = field(default_factory=dict)
    drama_state: Dict[str, Optional[str]] = field(
        default_factory=lambda: {
            "favorite_of_the_day": None,
            "enemy_of_the_day": None,
            "suspect": None,
            "rivals": None,
        }
    )
    bot_state: Dict[str, object] = field(
        default_factory=lambda: {"mood": "neutral", "remaining_messages": 0, "cooldown_messages": 0}
    )
    drama_reset_at: datetime = field(default_factory=datetime.utcnow)


class SocialDynamicsEngine:
    LOOP_PROBABILITY = 0.04
    FAVORITE_PROBABILITY = 0.02
    ENEMY_PROBABILITY = 0.015
    SUSPECT_PROBABILITY = 0.01

    MAX_LOOPS = 8
    MIN_LOOP_WEIGHT = 0.2
    LOOP_TTL_MESSAGES = 600
    SOCIAL_PROFILE_TTL_MESSAGES = 1_200
    SOCIAL_PROFILE_DECAY_PER_MESSAGE = 0.997
    SOCIAL_PROFILE_MIN_SIGNAL = 0.08
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
        self._load_user_profiles(channel_key, state)
        self._prune_loops(state, channel=channel_key, save=False)
        self._prune_user_profiles(state, channel=channel_key, save=False)
        self.channel_states[channel_key] = state
        return state

    def observe_message(self, channel: str, author: str, content: str, bot_nick: Optional[str] = None, intent_analysis: Optional[Dict[str, object]] = None):
        state = self._get_channel_state(channel)
        self._maybe_reset_drama_for_interval(state, channel)

        state.message_count += 1
        logging.debug("[SocialDynamics] observe_message channel=%s count=%s author=%s content=%s", channel, state.message_count, author, content[:120])
        state.users_seen.add(author.lower())

        if state.message_count % 20 == 0:
            for loop in state.memory_loops:
                loop.weight *= 0.97

        self._update_user_profile(state, channel=channel, author=author, content=content, intent_analysis=intent_analysis)
        self._prune_loops(state, channel=channel)
        self._prune_user_profiles(state, channel=channel)
        self._roll_memory_loop(state)
        self._roll_drama_events(state, author)
        self._update_mood(state, author=author, content=content, bot_nick=bot_nick, intent_analysis=intent_analysis)

    def reset_drama_state(self, channel: str, reason: str = "manual"):
        state = self._get_channel_state(channel)
        state.drama_state = {
            "favorite_of_the_day": None,
            "enemy_of_the_day": None,
            "suspect": None,
            "rivals": None,
        }
        state.users_seen = set()
        state.bot_state = {"mood": "neutral", "remaining_messages": 0, "cooldown_messages": 0}
        state.drama_reset_at = datetime.utcnow()
        logging.info("[SocialDynamics] drama_state reset channel=%s reason=%s", channel, reason)

    def register_bot_message(self, channel: str):
        state = self._get_channel_state(channel)
        remaining = int(state.bot_state.get("remaining_messages", 0) or 0)
        cooldown = int(state.bot_state.get("cooldown_messages", 0) or 0)

        if remaining > 0:
            remaining -= 1
            state.bot_state["remaining_messages"] = remaining
            if remaining <= 0:
                state.bot_state["mood"] = "neutral"
                state.bot_state["remaining_messages"] = 0
                state.bot_state["cooldown_messages"] = 3
            logging.debug("[SocialDynamics] bot_message mood_progress state=%s", state.bot_state)
            return

        if cooldown > 0:
            state.bot_state["mood"] = "neutral"
            state.bot_state["cooldown_messages"] = cooldown - 1
            logging.debug("[SocialDynamics] bot_message cooldown_progress state=%s", state.bot_state)
            return

    def _maybe_reset_drama_for_interval(self, state: ChannelSocialState, channel: str):
        now = datetime.utcnow()
        if (now - state.drama_reset_at) >= self.DRAMA_RESET_INTERVAL:
            self.reset_drama_state(channel, reason="24h_interval")

    def get_injection_payload(self, channel: str, author: Optional[str] = None) -> Dict[str, object]:
        state = self._get_channel_state(channel)
        memory_loop = None
        if state.active_loop_for_message:
            loop = state.active_loop_for_message
            memory_loop = {"topic": loop.topic, "type": loop.type, "examples": loop.examples}
            loop.weight *= 0.9
            loop.last_used = state.message_count
            self._persist_loops(channel, state)
            self._prune_loops(state, channel=channel)

        payload = {
            "mood": state.bot_state.get("mood", "neutral"),
            "drama_state": state.drama_state,
            "memory_loop": memory_loop,
            "social_memory": self._build_social_memory_summary(state, author),
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

        self._refresh_rivals_from_drama_state(state)

    def set_drama_role_target(self, channel: str, role: str, user: str):
        state = self._get_channel_state(channel)
        normalized_user = (user or "").strip().lower()
        if not normalized_user:
            return

        valid_roles = {"favorite_of_the_day", "enemy_of_the_day", "suspect"}
        if role not in valid_roles:
            return

        state.drama_state[role] = normalized_user
        state.users_seen.add(normalized_user)
        self._refresh_rivals_from_drama_state(state)
        logging.info("[SocialDynamics] role_target_updated channel=%s role=%s user=%s", channel, role, normalized_user)

    def _refresh_rivals_from_drama_state(self, state: ChannelSocialState):
        enemy = (state.drama_state.get("enemy_of_the_day") or "").strip()
        favorite = (state.drama_state.get("favorite_of_the_day") or "").strip()
        if enemy and favorite and enemy != favorite:
            state.drama_state["rivals"] = f"{favorite} vs {enemy}"
            return
        state.drama_state["rivals"] = None

    def _update_mood(self, state: ChannelSocialState, author: str, content: str, bot_nick: Optional[str] = None, intent_analysis: Optional[Dict[str, object]] = None):
        text = (content or "").lower().strip()
        lowered_author = (author or "").lower()
        bot_aliases = {"glorpinia", "glorp", (bot_nick or "").lower().strip()}
        bot_aliases.discard("")

        remaining = int(state.bot_state.get("remaining_messages", 0) or 0)
        cooldown = int(state.bot_state.get("cooldown_messages", 0) or 0)
        if remaining > 0:
            return
        if cooldown > 0:
            state.bot_state["mood"] = "neutral"
            return

        mood_event = self._infer_contextual_mood_event(
            text=text,
            author=lowered_author,
            bot_aliases=bot_aliases,
            intent_analysis=intent_analysis,
        )

        if mood_event:
            duration = random.randint(1, 5)
            state.bot_state["mood"] = mood_event
            state.bot_state["remaining_messages"] = duration
            state.bot_state["cooldown_messages"] = 0
            logging.debug("[SocialDynamics] mood_updated mood=%s remaining_messages=%s", mood_event, duration)
            return

        state.bot_state["mood"] = "neutral"
        state.bot_state["remaining_messages"] = 0
        logging.debug("[SocialDynamics] mood_state=%s", state.bot_state)

    def _infer_contextual_mood_event(self, text: str, author: str, bot_aliases: set, intent_analysis: Optional[Dict[str, object]] = None):
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

        if intent_analysis:
            emotion = (intent_analysis.get("emotion") or "").strip().lower()
            confidence = float(intent_analysis.get("confidence") or 0.0)
            if confidence >= 0.55:
                if direct_to_bot and emotion == "anger":
                    return "angry"
                if direct_to_bot and emotion == "joy":
                    return "happy"
                if mentions_bot and emotion == "curiosity":
                    return "curious"
                if emotion == "chaos":
                    return "chaotic"
                if emotion == "tsundere":
                    return "tsundere"

        if direct_to_bot and any(token in text for token in rude_tokens):
            return "angry"

        if direct_to_bot and any(token in text for token in praise_tokens):
            return "happy"

        if mentions_bot and "?" in text and any(token in text for token in question_tokens):
            return "curious"

        if re.search(r"\b(caos|anarquia|glitch)\b", text):
            return "chaotic"

        if re.search(r"\btsundere\b", text):
            return "tsundere"

        return None

    def _normalize_author(self, author: Optional[str]) -> str:
        return re.sub(r"[^a-z0-9_]", "", str(author or "").strip().lower())

    def _update_user_profile(
        self,
        state: ChannelSocialState,
        channel: str,
        author: str,
        content: str,
        intent_analysis: Optional[Dict[str, object]] = None,
    ):
        user_key = self._normalize_author(author)
        if not user_key:
            return

        profile = state.user_profiles.get(user_key) or UserSocialProfile(last_updated_message=state.message_count)
        self._decay_user_profile(profile, state.message_count)

        analysis = intent_analysis or {}
        sentiment = (analysis.get("sentiment") or "neutral").strip().lower()
        emotion = (analysis.get("emotion") or "neutral").strip().lower()
        primary_intent = (analysis.get("primary_intent") or "chat").strip().lower()
        confidence = float(analysis.get("confidence") or 0.0)

        if sentiment == "positive" or primary_intent == "praise":
            profile.positive_interactions += max(0.45, confidence)
        elif sentiment == "negative" or primary_intent == "complaint":
            profile.negative_interactions += max(0.35, confidence)
        elif emotion in {"joy", "tsundere", "chaos"}:
            profile.positive_interactions += 0.15
        elif emotion in {"anger", "sadness"}:
            profile.negative_interactions += 0.15

        profile.last_emotion = self._safe_emotion_label(emotion)
        profile.teasing_style = self._infer_teasing_style(content=content, intent_analysis=analysis)
        profile.trusted_joke_level = self._calculate_trusted_joke_level(profile)
        profile.last_updated_message = state.message_count
        state.user_profiles[user_key] = profile
        self._persist_user_profiles(channel, state)
        logging.debug(
            "[SocialDynamics] user_profile_updated channel=%s user=%s positive=%.3f negative=%.3f style=%s trusted=%.3f emotion=%s",
            channel,
            user_key,
            profile.positive_interactions,
            profile.negative_interactions,
            profile.teasing_style,
            profile.trusted_joke_level,
            profile.last_emotion,
        )

    def _decay_user_profile(self, profile: UserSocialProfile, current_message_count: int):
        age = max(0, current_message_count - int(profile.last_updated_message or 0))
        if age <= 0:
            return
        decay = self.SOCIAL_PROFILE_DECAY_PER_MESSAGE ** age
        profile.positive_interactions *= decay
        profile.negative_interactions *= decay
        profile.trusted_joke_level *= decay

    def _infer_teasing_style(self, content: str, intent_analysis: Dict[str, object]) -> str:
        """Classify style from safe signals only; never persist literal message text."""
        text = (content or "").lower()
        sentiment = (intent_analysis.get("sentiment") or "neutral").strip().lower()
        emotion = (intent_analysis.get("emotion") or "neutral").strip().lower()
        primary_intent = (intent_analysis.get("primary_intent") or "chat").strip().lower()

        has_laughter = bool(re.search(r"\b(k{2,}|kkk+|rsrs+|haha+)\b", text))
        has_teasing_marker = any(
            marker in text
            for marker in ["zoeira", "zoando", "brincadeira", "ironia", "sarcasmo", "provoca", "provocar"]
        )
        if has_teasing_marker or (has_laughter and (sentiment == "negative" or emotion in {"anger", "tsundere"})):
            return "provocative"
        if sentiment == "positive" or primary_intent == "praise":
            return "supportive"
        if emotion in {"curiosity", "chaos", "tsundere"}:
            return emotion
        return "neutral"

    def _calculate_trusted_joke_level(self, profile: UserSocialProfile) -> float:
        positive = max(0.0, float(profile.positive_interactions or 0.0))
        negative = max(0.0, float(profile.negative_interactions or 0.0))
        teasing_bonus = 0.25 if profile.teasing_style in {"provocative", "tsundere", "chaos"} else 0.0
        trust = (positive + teasing_bonus) / (positive + negative + 1.0)
        return max(0.0, min(1.0, trust))

    def _decayed_profile_values(self, profile: UserSocialProfile, current_message_count: int):
        age = max(0, current_message_count - int(profile.last_updated_message or 0))
        decay = self.SOCIAL_PROFILE_DECAY_PER_MESSAGE ** age
        return (
            max(0.0, float(profile.positive_interactions or 0.0) * decay),
            max(0.0, float(profile.negative_interactions or 0.0) * decay),
            max(0.0, float(profile.trusted_joke_level or 0.0) * decay),
        )

    def _safe_emotion_label(self, emotion: str) -> str:
        allowed = {"neutral", "joy", "anger", "sadness", "curiosity", "chaos", "tsundere"}
        normalized = (emotion or "neutral").strip().lower()
        return normalized if normalized in allowed else "neutral"

    def _build_social_memory_summary(self, state: ChannelSocialState, author: Optional[str]) -> Optional[str]:
        user_key = self._normalize_author(author)
        if not user_key:
            return None
        profile = state.user_profiles.get(user_key)
        if not profile:
            return None

        age = state.message_count - profile.last_updated_message
        if age > self.SOCIAL_PROFILE_TTL_MESSAGES:
            return None
        positive, negative, trusted = self._decayed_profile_values(profile, state.message_count)
        if max(positive, negative, trusted) < self.SOCIAL_PROFILE_MIN_SIGNAL:
            return None

        style_fragments = {
            "provocative": "costuma brincar de forma provocativa",
            "supportive": "costuma interagir de forma positiva",
            "curiosity": "costuma puxar perguntas e teorias",
            "chaos": "costuma entrar na energia caótica do chat",
            "tsundere": "costuma brincar em tom tsundere",
            "neutral": "tem histórico social neutro",
        }
        tone = "responder de forma neutra."
        if trusted >= 0.55 and negative <= positive + 0.5:
            tone = "responder com ironia leve."
        elif negative > positive + 1.0:
            tone = "evitar escalar conflito; responder com limites e humor seco."
        elif positive > negative + 0.7:
            tone = "manter tom cúmplice e amigável."

        style = style_fragments.get(profile.teasing_style, style_fragments["neutral"])
        return f"@{user_key} {style}, {tone} Última emoção percebida: {profile.last_emotion}."

    def add_memory_loop(self, channel: str, topic: str, users: Optional[List[str]] = None, weight: float = 0.5, loop_type: str = "running_joke", examples: Optional[List[str]] = None):
        state = self._get_channel_state(channel)
        normalized_topic = (topic or "").strip()
        if not normalized_topic:
            return

        clean_examples = []
        for example in examples or []:
            clean_example = str(example).strip()
            if clean_example and clean_example not in clean_examples:
                clean_examples.append(clean_example[:160])

        for loop in state.memory_loops:
            if loop.topic.lower() == normalized_topic.lower():
                merged_users = sorted(set(loop.users + (users or [])))
                loop.users = merged_users
                loop.weight = max(loop.weight, weight)
                loop.last_used = state.message_count
                merged_examples = list(loop.examples)
                for example in clean_examples:
                    if example not in merged_examples:
                        merged_examples.append(example)
                loop.examples = merged_examples[-5:]
                logging.debug(
                    "[SocialDynamics] memory_loop refreshed topic=%s users=%s weight=%.3f examples=%s",
                    loop.topic,
                    loop.users,
                    loop.weight,
                    loop.examples,
                )
                self._persist_loops(channel, state)
                self._prune_loops(state, channel=channel)
                return

        state.memory_loops.append(
            MemoryLoop(topic=normalized_topic, users=users or [], weight=weight, last_used=state.message_count, type=loop_type, examples=clean_examples[-5:])
        )
        logging.debug(
            "[SocialDynamics] memory_loop created topic=%s users=%s weight=%.3f type=%s examples=%s",
            normalized_topic,
            users or [],
            weight,
            loop_type,
            clean_examples[-5:],
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
                "examples": state.active_loop_for_message.examples,
            }

        return {
            "message_count": state.message_count,
            "users_seen": sorted(state.users_seen),
            "mood": state.bot_state.get("mood", "neutral"),
            "mood_duration": state.bot_state.get("remaining_messages", 0),
            "mood_cooldown": state.bot_state.get("cooldown_messages", 0),
            "drama_state": dict(state.drama_state),
            "active_memory_loop": active_loop,
            "user_profiles": {
                user: {
                    "positive_interactions": round(profile.positive_interactions, 3),
                    "negative_interactions": round(profile.negative_interactions, 3),
                    "teasing_style": profile.teasing_style,
                    "trusted_joke_level": round(profile.trusted_joke_level, 3),
                    "last_emotion": profile.last_emotion,
                    "age_messages": max(0, state.message_count - profile.last_updated_message),
                }
                for user, profile in sorted(state.user_profiles.items())
            },
            "memory_loops": [
                {
                    "topic": loop.topic,
                    "users": loop.users,
                    "weight": round(loop.weight, 3),
                    "last_used": loop.last_used,
                    "type": loop.type,
                    "examples": loop.examples,
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

    def _profile_storage_path_for_channel(self, channel: str) -> Path:
        channel_key = self._normalize_channel(channel)
        stem = self.storage_path.stem
        suffix = self.storage_path.suffix or ".json"
        return self.storage_path.with_name(f"{stem}_social_profiles_{channel_key}{suffix}")

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
                        examples=[str(example)[:160] for example in item.get("examples", []) if example],
                    )
                )
            if loaded_loops:
                state.memory_loops = loaded_loops[-self.MAX_LOOPS :]
            logging.debug("[SocialDynamics] memory_loops loaded path=%s count=%s", channel_path, len(state.memory_loops))
        except Exception as exc:
            logging.error("[SocialDynamics] failed loading memory loops path=%s error=%s", channel_path, exc)

    def _load_user_profiles(self, channel: str, state: ChannelSocialState):
        channel_path = self._profile_storage_path_for_channel(channel)
        if not channel_path.exists():
            return
        try:
            raw = json.loads(channel_path.read_text(encoding="utf-8"))
            loaded_profiles = {}
            for user, item in raw.items():
                user_key = self._normalize_author(user)
                if not user_key or not isinstance(item, dict):
                    continue
                loaded_profiles[user_key] = UserSocialProfile(
                    positive_interactions=float(item.get("positive_interactions", 0.0)),
                    negative_interactions=float(item.get("negative_interactions", 0.0)),
                    teasing_style=(item.get("teasing_style") or "neutral"),
                    trusted_joke_level=float(item.get("trusted_joke_level", 0.0)),
                    last_emotion=self._safe_emotion_label(item.get("last_emotion") or "neutral"),
                    last_updated_message=int(item.get("last_updated_message", 0)),
                )
            state.user_profiles = loaded_profiles
            logging.debug("[SocialDynamics] user_profiles loaded path=%s count=%s", channel_path, len(state.user_profiles))
        except Exception as exc:
            logging.error("[SocialDynamics] failed loading user profiles path=%s error=%s", channel_path, exc)

    def _persist_user_profiles(self, channel: str, state: ChannelSocialState):
        serialized = {
            user: {
                "positive_interactions": round(profile.positive_interactions, 4),
                "negative_interactions": round(profile.negative_interactions, 4),
                "teasing_style": profile.teasing_style,
                "trusted_joke_level": round(profile.trusted_joke_level, 4),
                "last_emotion": profile.last_emotion,
                "last_updated_message": profile.last_updated_message,
            }
            for user, profile in sorted(state.user_profiles.items())
        }
        try:
            channel_path = self._profile_storage_path_for_channel(channel)
            channel_path.parent.mkdir(parents=True, exist_ok=True)
            channel_path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logging.error("[SocialDynamics] failed persisting user profiles channel=%s error=%s", channel, exc)

    def _prune_user_profiles(self, state: ChannelSocialState, channel: str, save: bool = True):
        before = len(state.user_profiles)
        retained_profiles = {}
        for user, profile in state.user_profiles.items():
            age = state.message_count - profile.last_updated_message
            strongest_signal = max(self._decayed_profile_values(profile, state.message_count))
            if age > self.SOCIAL_PROFILE_TTL_MESSAGES or strongest_signal < self.SOCIAL_PROFILE_MIN_SIGNAL:
                logging.debug(
                    "[SocialDynamics] user_profile expired user=%s age=%s signal=%.3f",
                    user,
                    age,
                    strongest_signal,
                )
                continue
            retained_profiles[user] = profile
        state.user_profiles = retained_profiles
        if save and len(state.user_profiles) != before:
            self._persist_user_profiles(channel, state)

    def _persist_loops(self, channel: str, state: ChannelSocialState):
        serialized = [
            {
                "topic": loop.topic,
                "users": loop.users,
                "weight": loop.weight,
                "last_used": loop.last_used,
                "type": loop.type,
                "examples": loop.examples,
            }
            for loop in state.memory_loops
        ]
        try:
            channel_path = self._storage_path_for_channel(channel)
            channel_path.parent.mkdir(parents=True, exist_ok=True)
            channel_path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logging.error("[SocialDynamics] failed persisting memory loops channel=%s error=%s", channel, exc)
