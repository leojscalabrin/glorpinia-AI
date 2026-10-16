import os
import tempfile
import unittest

from glorpinia_bot.user_rpg import UserRPGManager

OPTS = [{"name": f"Classe {i}", "description": f"Descrição da classe {i}."} for i in range(1, 4)]


class ClassOptionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rpg = UserRPGManager(path=os.path.join(self.tmp.name, "rpg.json"))
        self.calls = []

    def _xp_for_level(self, level):
        return sum(self.rpg.xp_to_next(l) for l in range(1, level))

    def _set_level(self, nick, level, channel="canal"):
        current = (self.rpg.get_profile(nick) or {}).get("xp", 0)
        self.rpg.add_xp(nick, self._xp_for_level(level) - current, channel)
        self.assertEqual(self.rpg.get_profile(nick)["level"], level)

    def test_hook_fires_only_from_prep_level_and_without_class_or_options(self):
        self.rpg.class_options_hook = lambda nick, ch: self.calls.append((nick, ch))
        self._set_level("ana", self.rpg.CLASS_PREP_LEVEL - 1)
        self.assertEqual(self.calls, [])
        self._set_level("ana", self.rpg.CLASS_PREP_LEVEL)
        self.assertEqual(self.calls, [("ana", "canal")])
        self.assertTrue(self.rpg.needs_class_options("ana"))
        # Com opções prontas, não dispara mais.
        self.assertTrue(self.rpg.set_class_options("ana", OPTS))
        self.calls.clear()
        self.rpg.add_xp("ana", 1, "canal")
        self.assertEqual(self.calls, [])
        self.assertFalse(self.rpg.needs_class_options("ana"))

    def test_with_hook_no_synchronous_pool_options_at_level_10(self):
        self.rpg.class_options_hook = lambda nick, ch: None
        self._set_level("bia", 10)
        self.assertEqual(self.rpg.get_profile("bia")["class_options"], [])

    def test_without_hook_keeps_legacy_pool_fallback_on_crossing_10(self):
        self._set_level("caio", 9)
        self.assertFalse(self.rpg.get_profile("caio").get("class_options"))
        self._set_level("caio", 10)
        profile = self.rpg.get_profile("caio")
        self.assertEqual(len(profile["class_options"]), 3)
        self.assertEqual(profile["class_options_source"], "pool")

    def test_set_class_options_rules(self):
        self._set_level("duda", 7)
        self.assertFalse(self.rpg.set_class_options("duda", OPTS))  # abaixo do nível de preparo
        self._set_level("duda", self.rpg.CLASS_PREP_LEVEL)
        self.assertFalse(self.rpg.set_class_options("duda", OPTS[:2]))  # quantidade errada
        self.assertFalse(self.rpg.set_class_options("duda", [{"name": "x"}] * 3))  # formato inválido
        self.assertFalse(self.rpg.set_class_options("ninguem", OPTS))  # sem perfil
        self.assertTrue(self.rpg.set_class_options("duda", OPTS, "ai"))
        self.assertFalse(self.rpg.set_class_options("duda", OPTS))  # não sobrescreve
        self.assertEqual(self.rpg.get_profile("duda")["class_options_source"], "ai")

    def test_options_persist_to_disk(self):
        self._set_level("edu", 9)
        self.rpg.set_class_options("edu", OPTS, "ai")
        reloaded = UserRPGManager(path=self.rpg.path)
        self.assertEqual(reloaded.get_profile("edu")["class_options"], OPTS)

    def test_fallback_only_for_unlocked_users(self):
        self.rpg.class_options_hook = lambda nick, ch: None
        self._set_level("flavia", 9)
        self.assertFalse(self.rpg.assign_fallback_class_options("flavia"))
        self._set_level("flavia", 10)
        self.assertTrue(self.rpg.assign_fallback_class_options("flavia"))
        self.assertFalse(self.rpg.assign_fallback_class_options("flavia"))
        self.assertEqual(self.rpg.get_profile("flavia")["class_options_source"], "pool")

    def test_choose_class_blocks_before_10_and_reports_missing_options(self):
        self.rpg.class_options_hook = lambda nick, ch: None
        self._set_level("gabi", 9)
        self.rpg.set_class_options("gabi", OPTS, "ai")
        self.assertEqual(self.rpg.choose_class("gabi", "1")[:2], (False, "level"))
        self._set_level("heitor", 10)
        self.assertEqual(self.rpg.choose_class("heitor", "1")[:2], (False, "no_options"))

    def test_choose_class_with_prepared_options_clears_them(self):
        self.rpg.class_options_hook = lambda nick, ch: None
        self._set_level("iris", 9)
        self.rpg.set_class_options("iris", OPTS, "ai")
        self._set_level("iris", 10)
        ok, reason, profile = self.rpg.choose_class("iris", "2")
        self.assertTrue(ok)
        self.assertEqual(profile["class_name"], "Classe 2")
        stored = self.rpg.get_profile("iris")
        self.assertEqual(stored["class_options"], [])
        self.assertNotIn("class_options_source", stored)
        self.assertFalse(self.rpg.needs_class_options("iris"))


if __name__ == "__main__":
    unittest.main()
