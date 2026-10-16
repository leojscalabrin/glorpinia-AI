import json
import os
import tempfile
import threading
import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest import mock

from glorpinia_bot.main import TwitchIRC
from glorpinia_bot.user_rpg import UserRPGManager

BASE = [{"name": f"Classe {i}", "description": f"Descrição da classe {i}."} for i in range(1, 4)]
GOOD_EVO = json.dumps({"options": [
    {"name": "Monge do Lag Eterno", "description": "Faz o tempo esperar por ele em cada duelo."},
    {"name": "Cavaleiro do Ping", "description": "Atravessa o atraso como quem corta o vento."},
    {"name": "Sábio do Buffer", "description": "Guarda o futuro em cache e o libera na hora certa."},
]})


class FakeGemini:
    def __init__(self, response=GOOD_EVO):
        self.response, self.calls, self.lore_prompts = response, [], []

    def request_pure_analysis(self, prompt, generation_config=None):
        self.calls.append((prompt, generation_config))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def get_response(self, prompt, channel, author, memory_mgr, live_context=None):
        self.lore_prompts.append(prompt)
        return "@x, Uma nova fase da história começa."


class EvolutionBotTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bot = TwitchIRC.__new__(TwitchIRC)
        bot.user_rpg = UserRPGManager(path=os.path.join(tmp.name, "rpg.json"))
        bot.user_rpg.class_options_hook = lambda nick, ch: None
        bot.class_ai_enabled = True
        bot.class_gen_retry_sec = 600
        bot._class_gen_lock = threading.Lock()
        bot._class_gen_inflight = set()
        bot._class_gen_last_attempt = {}
        bot.user_tags = SimpleNamespace(get_tags=lambda n: ["gamer noturno"])
        bot.cookie_system = SimpleNamespace(get_cookies=lambda n: 7)
        bot.memory_mgr = SimpleNamespace(get_user_memory_samples=lambda c, n, limit: ["gosta de speedrun"])
        bot.social_dynamics = SimpleNamespace(get_user_social_summary=lambda c, n: "@ana positiva.")
        bot.recent_messages = {"canal": deque([{"author": "ana", "content": "bom dia chat"}])}
        bot.auth = SimpleNamespace(bot_nick="glorpinia")
        bot.get_live_context = lambda ch: None
        bot.gemini_client = FakeGemini()
        bot.sent = []
        bot.send_message = lambda ch, msg: bot.sent.append(msg)
        bot.bot_privileged_channels = {"canal": True}
        bot.levelup_notice_delay_sec = 0
        self.bot = bot
        self.rpg = bot.user_rpg

    def _level(self, nick, level, channel="canal"):
        cur = (self.rpg.get_profile(nick) or {}).get("xp", 0)
        self.rpg.add_xp(nick, sum(self.rpg.xp_to_next(l) for l in range(1, level)) - cur, channel)

    def _with_class(self, nick="ana", level=10):
        self._level(nick, 10)
        self.rpg.set_class_options(nick, BASE)
        self.rpg.choose_class(nick, "1")
        self.rpg.set_lore(nick, "Lore do começo.")
        if level > 10:
            self._level(nick, level)

    # ---- worker ----
    def test_worker_generates_evolution_options_from_class_lore_and_context(self):
        self._with_class(level=38)
        self.bot._class_gen_inflight.add("ana")
        self.bot._class_options_worker("ana", "canal")

        p = self.rpg.get_profile("ana")
        self.assertEqual(p["evolution_options_source"], "ai")
        self.assertEqual(p["evolution_options"][0]["name"], "Monge do Lag Eterno")
        self.assertFalse(p.get("class_options"))
        prompt, config = self.bot.gemini_client.calls[0]
        for expected in ("Classe 1", "Lore do começo.", "gamer noturno", "gosta de speedrun", "bom dia chat", "PRIMEIRA evolução"):
            self.assertIn(expected, prompt)
        self.assertEqual(config["temperature"], 0.9)
        self.assertNotIn("ana", self.bot._class_gen_inflight)

    def test_worker_rejects_ai_options_that_repeat_the_current_class(self):
        self._with_class(level=38)
        repeated = json.dumps({"options": [
            {"name": "Classe 1", "description": "Igual à classe atual, deve cair fora."},
            {"name": "Monge Zen", "description": "Atraso vira meditação profunda."},
            {"name": "Monge Glitch", "description": "Falhas viram golpes inesperados."},
        ]})
        self.bot.gemini_client = FakeGemini(repeated)
        self.bot._class_options_worker("ana", "canal")
        self.assertFalse(self.rpg.get_profile("ana").get("evolution_options"))  # 38: sem reserva ainda

    def test_ai_failure_before_unlock_leaves_empty_and_at_unlock_uses_fallback(self):
        self.bot.gemini_client = FakeGemini(RuntimeError("boom"))
        self._with_class(level=38)
        self.bot._class_options_worker("ana", "canal")
        self.assertFalse(self.rpg.get_profile("ana").get("evolution_options"))
        self._level("ana", 40)
        self.bot._class_options_worker("ana", "canal")
        p = self.rpg.get_profile("ana")
        self.assertEqual(p["evolution_options_source"], "fallback")
        self.assertEqual(len(p["evolution_options"]), 3)

    def test_worker_second_stage_uses_latest_evolution_and_full_path(self):
        self._with_class(level=70)
        self.rpg.set_evolution_options("ana", [{"name": f"Evo{i}", "description": f"Evolução {i} da classe."} for i in range(1, 4)])
        self.rpg.choose_class("ana", "1")
        self.rpg.set_lore("ana", "Segunda fase.")
        self.bot._class_options_worker("ana", "canal")
        prompt = self.bot.gemini_client.calls[0][0]
        self.assertIn("SEGUNDA evolução", prompt)
        self.assertIn("Classe atual: Evo1", prompt)
        self.assertIn("Classe 1 → Evo1", prompt)
        self.assertIn("Segunda fase.", prompt)
        self.assertEqual(self.rpg.get_profile("ana")["evolution_options_stage"], 2)

    def test_schedule_spawns_for_evolution_and_bypasses_retry_when_unlocked(self):
        self._with_class(level=40)
        self.bot._class_gen_last_attempt["ana"] = time.time()
        with mock.patch("glorpinia_bot.main.threading.Thread") as thread:
            self.assertTrue(self.bot.schedule_class_options("ana", "canal"))
            self.assertEqual(thread.call_count, 1)

    def test_schedule_does_nothing_when_nothing_is_pending(self):
        self._with_class(level=20)
        with mock.patch("glorpinia_bot.main.threading.Thread") as thread:
            self.assertFalse(self.bot.schedule_class_options("ana", "canal"))
            thread.assert_not_called()

    def test_ai_disabled_uses_evolution_fallback_directly(self):
        self.bot.class_ai_enabled = False
        self._with_class(level=40)
        self.bot.schedule_class_options("ana", "canal")
        self.assertEqual(self.rpg.get_profile("ana")["evolution_options_source"], "fallback")

    # ---- aviso de level up ----
    def test_level_up_notice_hints_class_at_10_and_evolution_at_40_and_70_only(self):
        self._level("ana", 10)
        self.bot.send_level_up_notice("canal", "ana", 10)
        self.assertIn("escolher sua classe", self.bot.sent[-1])

        self._with_class("bia", level=40)
        self.bot.send_level_up_notice("canal", "bia", 40)
        self.assertIn("escolher sua evolução", self.bot.sent[-1])
        self.bot.send_level_up_notice("canal", "bia", 41)
        self.assertNotIn("*class", self.bot.sent[-1])

        self.rpg.set_evolution_options("bia", BASE)
        self.rpg.choose_class("bia", "1")
        self._level("bia", 70)
        self.bot.send_level_up_notice("canal", "bia", 70)
        self.assertIn("escolher sua evolução", self.bot.sent[-1])

    # ---- lore ----
    def test_evolution_lore_continues_previous_lore_and_is_saved(self):
        self._with_class(level=40)
        self.rpg.set_evolution_options("ana", BASE)
        ok, reason, profile = self.rpg.choose_class("ana", "2")
        self.assertEqual(reason, "evolved")
        self.bot._generate_rpg_lore("ana", "canal", profile, evolution=True)

        prompt = self.bot.gemini_client.lore_prompts[0]
        for expected in ("PRÓXIMA FASE", "Classe anterior: Classe 1", "Nova classe: Classe 2", "Lore anterior: Lore do começo.", "gamer noturno"):
            self.assertIn(expected, prompt)
        p = self.rpg.get_profile("ana")
        self.assertEqual(p["lore"], "Uma nova fase da história começa.")  # prefixo "@x," removido
        self.assertEqual(p["lore_history"][0]["lore"], "Lore do começo.")

    def test_base_class_lore_prompt_is_unchanged(self):
        self._level("ana", 10)
        self.rpg.set_class_options("ana", BASE)
        _, _, profile = self.rpg.choose_class("ana", "1")
        self.bot._generate_rpg_lore("ana", "canal", profile, evolution=False)
        prompt = self.bot.gemini_client.lore_prompts[0]
        self.assertIn("Escreva uma lore curta (2-3 frases)", prompt)
        self.assertIn("Classe: Classe 1 — Descrição da classe 1.", prompt)
        self.assertNotIn("PRÓXIMA FASE", prompt)


if __name__ == "__main__":
    unittest.main()
