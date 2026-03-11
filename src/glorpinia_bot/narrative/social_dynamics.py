import random
import re
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

    def __init__(self):
        self.message_count = 0
        self.users_seen = set()
        self.active_loop_for_message: Optional[MemoryLoop] = None

        self.memory_loops: List[MemoryLoop] = [
            MemoryLoop(
                topic="moon apostando cookies",
                users=["moongrade"],
                weight=0.8,
                last_used=0,
                type="running_joke",
            )
        ]

        self.drama_state: Dict[str, Optional[str]] = {
            "favorite_of_the_day": None,
            "enemy_of_the_day": None,
            "suspect": None,
            "rivalries": [],
        }

        self.bot_state = {"mood": "neutral", "duration": 0}

    def observe_message(self, author: str, content: str):
        self.message_count += 1
        self.users_seen.add(author.lower())

        if self.message_count % 20 == 0:
            for loop in self.memory_loops:
                loop.weight *= 0.97

        self._prune_loops()
        self._roll_memory_loop()
        self._roll_drama_events(author)
        self._update_mood(content)

    def get_injection_payload(self) -> Dict[str, object]:
        memory_loop = None
        if self.active_loop_for_message:
            loop = self.active_loop_for_message
            memory_loop = {"topic": loop.topic, "type": loop.type}
            loop.weight *= 0.9
            loop.last_used = self.message_count
            self._prune_loops()

        return {
            "mood": self.bot_state.get("mood", "neutral"),
            "drama_state": self.drama_state,
            "memory_loop": memory_loop,
        }

    def _roll_memory_loop(self):
        self.active_loop_for_message = None
        if not self.memory_loops:
            return

        if random.random() > self.LOOP_PROBABILITY:
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

    def _update_mood(self, content: str):
        text = content.lower()

        mood_event = None
        if any(token in text for token in ["glorpinia linda", "boa bot", "te amo", "braba"]):
            mood_event = ("happy", 6)
        elif any(token in text for token in ["burra", "lixo", "idiota", "bot ruim"]):
            mood_event = ("angry", 4)
        elif "?" in text and any(token in text for token in ["por que", "como", "explica", "teoria"]):
            mood_event = ("curious", 5)
        elif re.search(r"\bcaos|anarquia|glitch\b", text):
            mood_event = ("chaotic", 3)
        elif re.search(r"\btsundere\b", text):
            mood_event = ("tsundere", 4)

        if mood_event:
            self.bot_state["mood"] = mood_event[0]
            self.bot_state["duration"] = mood_event[1]
            return

        duration = self.bot_state.get("duration", 0)
        if duration > 0:
            self.bot_state["duration"] = duration - 1
        if self.bot_state.get("duration", 0) <= 0:
            self.bot_state["mood"] = "neutral"
            self.bot_state["duration"] = 0

    def add_memory_loop(self, topic: str, users: Optional[List[str]] = None, weight: float = 0.5, loop_type: str = "running_joke"):
        self.memory_loops.append(
            MemoryLoop(topic=topic, users=users or [], weight=weight, last_used=self.message_count, type=loop_type)
        )
        self.memory_loops = self.memory_loops[-self.MAX_LOOPS :]
        self._prune_loops()

    def _prune_loops(self):
        self.memory_loops = [loop for loop in self.memory_loops if loop.weight >= self.MIN_LOOP_WEIGHT]
        if len(self.memory_loops) > self.MAX_LOOPS:
            self.memory_loops = sorted(self.memory_loops, key=lambda l: l.weight, reverse=True)[: self.MAX_LOOPS]
