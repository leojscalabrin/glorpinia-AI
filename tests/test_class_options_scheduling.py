import json
import os
import tempfile
import threading
import unittest
from collections import deque
from types import SimpleNamespace
from unittest import mock

from glorpinia_bot.main import TwitchIRC
from glorpinia_bot.user_rpg import UserRPGManager

GOOD = json.dumps({"options": [
    {"name": "Speedrunner Lunar", "description": "Corta caminho entre fendas do espaço-tempo."},
    {"name": "Gato de Neon", "description": "Ronrona e reescreve a sorte do grupo."},
    {"name": "Sentinela do Café", "description": "Mantém a guilda acordada nas madrugadas."},
]})


class FakeGemini:
    def __init__(self, response):
        self.response, self.calls = response, []

    def request_pure_analysis(self, prompt, generation_config=None):
        self.calls.append((prompt, generation_config))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ClassOptionsSchedulingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bot = TwitchIRC.__new__(TwitchIRC)
        bot.user_rpg = UserRPGManager(path=os.path.join(tmp.name, "rpg.json"))
        bot.class_ai_enabled = True
        bot.class_gen_retry_sec = 600
        bot._class_gen_lock = threading.Lock()
        bot._class_gen_inflight = set()
        bot._class_gen_last_attempt = {}
        bot.user_tags = SimpleNamespace(get_tags=lambda n: ["gamer noturno"])
        bot.cookie_system = SimpleNamespace(get_cookies=lambda n: 7)
        bot.memory_mgr = SimpleNamespace(get_user_memory_samples=lambda c, n, limit: ["gosta de speedrun"])
        bot.social_dynamics = SimpleNamespace(get_user_social_summary=lambda c, n: "@ana costuma interagir de forma positiva.")
        bot.recent_messages = {"canal": deque([
            {"author": "ana", "content": "bom dia chat"},
            {"author": "outro", "content": "mensagem de terceiros"},
        ])}
        bot.gemini_client = FakeGemini(GOOD)
        self.bot = bot

    def _set_level(self, nick, level, channel="canal"):
        rpg = self.bot.user_rpg
        current = (rpg.get_profile(nick) or {}).get("xp", 0)
        rpg.add_xp(nick, sum(rpg.xp_to_next(l) for l in range(1, level)) - current, channel)

    def test_worker_stores_ai_options_using_all_context(self):
        self._set_level("ana", 8)
        self.bot._class_gen_inflight.add("ana")
        self.bot._class_options_worker("ana", "canal")

        profile = self.bot.user_rpg.get_profile("ana")
        self.assertEqual(profile["class_options_source"], "ai")
        self.assertEqual(profile["class_options"][0]["name"], "Speedrunner Lunar")
        self.assertNotIn("ana", self.bot._class_gen_inflight)

        prompt, config = self.bot.gemini_client.calls[0]
        for expected in ("gamer noturno", "gosta de speedrun", "bom dia chat", "costuma interagir de forma positiva", "Cookies atuais: 7"):
            self.assertIn(expected, prompt)
        self.assertNotIn("mensagem de terceiros", prompt)
        self.assertEqual(config["temperature"], 0.9)

    def test_invalid_ai_answer_before_level_10_leaves_options_empty(self):
        self.bot.gemini_client = FakeGemini("MrDestructoid **GL-0RP5:** Falha crítica.")
        self._set_level("ana", 8)
        self.bot._class_options_worker("ana", "canal")
        self.assertFalse(self.bot.user_rpg.get_profile("ana").get("class_options"))

    def test_ai_failure_at_level_10_falls_back_to_pool(self):
        self.bot.gemini_client = FakeGemini(RuntimeError("boom"))
        self._set_level("ana", 10)
        self.bot._class_options_worker("ana", "canal")
        profile = self.bot.user_rpg.get_profile("ana")
        self.assertEqual(len(profile["class_options"]), 3)
        self.assertEqual(profile["class_options_source"], "pool")

    def test_worker_never_overwrites_existing_options_or_class(self):
        self._set_level("ana", 9)
        existing = [{"name": f"C{i}", "description": f"Descrição {i}."} for i in range(3)]
        self.bot.user_rpg.set_class_options("ana", existing)
        self.bot._class_options_worker("ana", "canal")
        self.assertEqual(self.bot.gemini_client.calls, [])
        self.assertEqual(self.bot.user_rpg.get_profile("ana")["class_options"], existing)

    def test_schedule_deduplicates_and_respects_retry_window(self):
        self._set_level("ana", 8)
        with mock.patch("glorpinia_bot.main.threading.Thread") as thread:
            self.assertTrue(self.bot.schedule_class_options("ana", "canal"))
            self.assertFalse(self.bot.schedule_class_options("ana", "canal"))  # em andamento
            self.bot._class_gen_inflight.clear()
            self.assertFalse(self.bot.schedule_class_options("ana", "canal"))  # dentro do intervalo
            self.assertEqual(thread.call_count, 1)

    def test_schedule_ignores_retry_window_once_level_10_is_reached(self):
        self._set_level("ana", 10)
        self.bot._class_gen_last_attempt["ana"] = __import__("time").time()
        with mock.patch("glorpinia_bot.main.threading.Thread") as thread:
            self.assertTrue(self.bot.schedule_class_options("ana", "canal"))
            self.assertEqual(thread.call_count, 1)

    def test_ai_disabled_uses_pool_directly(self):
        self.bot.class_ai_enabled = False
        self._set_level("ana", 10)
        with mock.patch("glorpinia_bot.main.threading.Thread") as thread:
            self.assertFalse(self.bot.schedule_class_options("ana", "canal"))
            thread.assert_not_called()
        self.assertEqual(self.bot.user_rpg.get_profile("ana")["class_options_source"], "pool")

    def test_xp_hook_triggers_generation_when_reaching_prep_level(self):
        self.bot.user_rpg.class_options_hook = self.bot.schedule_class_options
        with mock.patch("glorpinia_bot.main.threading.Thread") as thread:
            self._set_level("ana", self.bot.user_rpg.CLASS_PREP_LEVEL - 1)
            thread.assert_not_called()
            self._set_level("ana", self.bot.user_rpg.CLASS_PREP_LEVEL)
            self.assertEqual(thread.call_count, 1)


if __name__ == "__main__":
    unittest.main()
