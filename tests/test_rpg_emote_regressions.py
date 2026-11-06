import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from glorpinia_bot.user_rpg import UserRPGManager
from glorpinia_bot.features.seventv_emote import (
    SevenTVEmote,
    SevenTVRateLimitError,
)
from glorpinia_bot.features.fortune_cookie import FortuneCookie


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class RPGRegressionTests(unittest.TestCase):
    def test_saved_level_is_reconciled_from_total_xp_on_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "user_rpg.json")
            with open(path, "w", encoding="utf-8") as profile_file:
                json.dump({"viewer": {"xp": 500, "level": 1}}, profile_file)

            manager = UserRPGManager(path=path)
            profile = manager.get_profile("viewer")

            self.assertEqual(profile["xp"], 500)
            self.assertEqual(profile["level"], 10)

            first_message = manager.record_message("viewer", "channel")
            self.assertFalse(first_message["leveled"])
            self.assertEqual(first_message["old_level"], 10)
            self.assertEqual(first_message["level"], 10)
            self.assertEqual(manager.get_profile("viewer")["xp"], 501)

            # Reinicializações seguintes não devem continuar alterando o perfil.
            second_manager = UserRPGManager(path=path)
            self.assertEqual(second_manager.get_profile("viewer")["level"], 10)

    def test_provisional_and_definitive_class_options_are_stored_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = UserRPGManager(path=os.path.join(directory, "rpg.json"))
            manager.ensure_profile("viewer")
            manager.add_xp("viewer", 315)  # nível 8: já pode preparar a classe definitiva.

            provisional = [
                {"name": "Explorador", "description": "Explora caminhos."},
                {"name": "Guardião", "description": "Protege aliados."},
                {"name": "Artífice", "description": "Cria soluções."},
            ]
            definitive = [
                {"name": "Cronista do Vazio", "description": "Registra anomalias."},
                {"name": "Mestre das Relíquias", "description": "Domina artefatos."},
                {"name": "Oráculo de Neon", "description": "Lê sinais do chat."},
            ]

            self.assertTrue(manager.needs_class_options("viewer", "definitive", minimum_level=8))
            self.assertTrue(manager.set_class_options("viewer", provisional, "provisional"))
            self.assertTrue(manager.set_class_options("viewer", definitive, "definitive"))
            self.assertFalse(manager.needs_class_options("viewer", "definitive", minimum_level=8))
            self.assertEqual(manager.get_class_options("viewer", "provisional"), provisional)
            self.assertEqual(manager.get_class_options("viewer", "definitive"), definitive)

            manager.add_xp("viewer", 185)  # nível 10: opções antecipadas permanecem disponíveis.
            success, reason, profile = manager.choose_class("viewer", 1)
            self.assertTrue(success)
            self.assertEqual(reason, "chosen")
            self.assertEqual(profile["class_name"], "Cronista do Vazio")

    def test_legacy_definitive_options_are_migrated_without_losing_them(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "user_rpg.json")
            legacy_options = [
                {"name": "A", "description": "a"},
                {"name": "B", "description": "b"},
                {"name": "C", "description": "c"},
            ]
            with open(path, "w", encoding="utf-8") as profile_file:
                json.dump({
                    "viewer": {
                        "xp": 500,
                        "level": 10,
                        "class_options": legacy_options,
                        "class_options_stage": "definitive",
                    }
                }, profile_file)

            manager = UserRPGManager(path=path)
            self.assertEqual(manager.get_class_options("viewer", "definitive"), legacy_options)
            self.assertEqual(manager.get_class_options("viewer", "provisional"), [])

    def test_lore_storage_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = UserRPGManager(path=os.path.join(directory, "rpg.json"))
            manager.ensure_profile("viewer")
            manager.add_xp("viewer", 500)
            manager.set_class_options(
                "viewer",
                [
                    {"name": "A", "description": "a"},
                    {"name": "B", "description": "b"},
                    {"name": "C", "description": "c"},
                ],
                "definitive",
            )
            manager.choose_class("viewer", 1)
            self.assertTrue(manager.set_lore("viewer", "x" * 900))
            self.assertEqual(len(manager.get_profile("viewer")["lore"]), 280)


class SevenTVRegressionTests(unittest.TestCase):
    @staticmethod
    def _search_payload():
        item = {
            "id": "emote-id",
            "defaultName": "TestEmote",
            "deleted": False,
            "flags": {"private": False, "nsfw": False, "publicListed": True},
            "scores": {"trendingWeek": 12},
            "channels": {"totalCount": 100},
        }
        return {"data": {"emotes": {"search": {"items": [item]}}}}

    def test_concurrent_requests_share_one_cache_refresh(self):
        bot = type("Bot", (), {"send_message": lambda *args: None})()
        with tempfile.TemporaryDirectory() as directory:
            feature = SevenTVEmote(bot)
            feature._cache_path = os.path.join(directory, "cache.json")
            calls = []

            def fake_post(*args, **kwargs):
                calls.append(1)
                time.sleep(0.04)
                return FakeResponse(self._search_payload())

            results = []
            threads = [
                threading.Thread(target=lambda: results.append(feature._get_candidates()))
                for _ in range(8)
            ]
            with patch("glorpinia_bot.features.seventv_emote.requests.post", side_effect=fake_post):
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)

            self.assertEqual(len(results), 8)
            self.assertEqual(len(calls), 2)  # trending + popular, sem duplicação por usuário
            self.assertTrue(os.path.exists(feature._cache_path))

    def test_graphql_rate_limit_is_detected_and_reset_is_respected(self):
        bot = type("Bot", (), {"send_message": lambda *args: None})()
        feature = SevenTVEmote(bot)
        payload = {
            "errors": [{
                "message": "rate limit exceeded",
                "extensions": {
                    "code": "RATE_LIMIT_EXCEEDED",
                    "headers": {"x-ratelimit-search-reset": "17"},
                },
            }]
        }
        with patch(
            "glorpinia_bot.features.seventv_emote.requests.post",
            return_value=FakeResponse(payload),
        ):
            with self.assertRaises(SevenTVRateLimitError) as raised:
                feature._get_candidates()
        self.assertEqual(raised.exception.retry_after, 17)


class FortuneCookieRegressionTests(unittest.TestCase):
    def test_prefix_and_author_are_rendered_only_once(self):
        generated = "glorp @felinomascarado, glorp Quem tenta segurar o teto descobre a poeira."
        clean = FortuneCookie._clean_generated_text(generated, "felinomascarado")
        self.assertEqual(clean, "Quem tenta segurar o teto descobre a poeira.")
        self.assertEqual(FortuneCookie._format_cookie_gain(16), "( +16 🍪)")


if __name__ == "__main__":
    unittest.main()
