import json
import os
import tempfile
import unittest

from glorpinia_bot import class_options as co
from glorpinia_bot.user_rpg import CLASS_POOL, UserRPGManager, effective_class

BASE = [{"name": f"Classe {i}", "description": f"Descrição da classe {i}."} for i in range(1, 4)]


def evo(stage, label="A"):
    return [{"name": f"Evo{stage}{label}{i}", "description": f"Evolução {stage}{label}{i} da classe."} for i in range(1, 4)]


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "rpg.json")
        self.rpg = UserRPGManager(path=self.path)
        self.calls = []
        self.rpg.class_options_hook = lambda nick, ch: self.calls.append((nick, ch))

    def _level(self, nick, level, channel="canal"):
        cur = (self.rpg.get_profile(nick) or {}).get("xp", 0)
        self.rpg.add_xp(nick, sum(self.rpg.xp_to_next(l) for l in range(1, level)) - cur, channel)

    def _with_class(self, nick="ana", level=10):
        self._level(nick, 10)
        self.assertTrue(self.rpg.set_class_options(nick, BASE))
        self.assertTrue(self.rpg.choose_class(nick, "1")[0])
        if level > 10:
            self._level(nick, level)
        self.calls.clear()

    # ---- pedidos de opções ----
    def test_evolution_request_timeline(self):
        self._with_class()
        self._level("ana", 37)
        self.assertIsNone(self.rpg.get_options_request("ana"))
        self._level("ana", 38)
        self.assertEqual(self.rpg.get_options_request("ana"),
                         {"kind": "evolution", "stage": 1, "unlock_level": 40, "unlocked": False})
        self._level("ana", 40)
        self.assertTrue(self.rpg.get_options_request("ana")["unlocked"])

    def test_hook_fires_for_evolution_prep_but_not_before(self):
        self._with_class()
        self._level("ana", 37)
        self.assertEqual(self.calls, [])
        self._level("ana", 38)
        self.assertEqual(self.calls, [("ana", "canal")])

    def test_class_request_has_priority_and_kind_class(self):
        self._level("bia", 9)
        self.assertEqual(self.rpg.get_options_request("bia")["kind"], "class")

    def test_set_evolution_options_rules(self):
        self._with_class()
        self._level("ana", 30)
        self.assertFalse(self.rpg.set_evolution_options("ana", evo(1)))  # cedo demais
        self._level("ana", 38)
        self.assertFalse(self.rpg.set_evolution_options("ana", evo(1)[:2]))
        self.assertFalse(self.rpg.set_evolution_options("ana", [{"name": "x"}] * 3))
        self.assertTrue(self.rpg.set_evolution_options("ana", evo(1), "ai"))
        self.assertFalse(self.rpg.set_evolution_options("ana", evo(1, "B")))  # sem sobrescrever
        p = self.rpg.get_profile("ana")
        self.assertEqual((p["evolution_options_source"], p["evolution_options_stage"]), ("ai", 1))
        self.assertIsNone(self.rpg.get_options_request("ana"))

    def test_set_evolution_options_refused_without_class(self):
        self._level("caio", 45)
        self.assertFalse(self.rpg.set_evolution_options("caio", evo(1)))

    # ---- escolha ----
    def test_choose_evolution_updates_class_lore_and_stage(self):
        self._with_class()
        self.rpg.set_lore("ana", "Lore do começo.")
        self._level("ana", 40)
        self.rpg.set_evolution_options("ana", evo(1), "ai")
        ok, reason, p = self.rpg.choose_class("ana", "2")
        self.assertEqual((ok, reason), (True, "evolved"))
        self.assertEqual(p["class_name"], "Classe 1")  # base preservada
        self.assertEqual(effective_class(p), ("Evo1A2", "Evolução 1A2 da classe."))
        self.assertEqual(p["evolution_stage"], 1)
        self.assertEqual(p["evolutions"][0]["from"], "Classe 1")
        self.assertEqual(p["evolution_options"], [])
        self.assertIsNone(p["lore"])
        self.assertEqual(p["lore_history"], [{"stage": 0, "class_name": "Classe 1", "lore": "Lore do começo."}])
        self.assertTrue(self.rpg.set_lore("ana", "Nova fase."))
        self.assertFalse(self.rpg.needs_class_options("ana"))

    def test_choose_blocked_before_unlock_level_even_with_options_ready(self):
        self._with_class()
        self._level("ana", 38)
        self.rpg.set_evolution_options("ana", evo(1))
        self._level("ana", 39)
        self.assertEqual(self.rpg.choose_class("ana", "1")[:2], (False, "evolution_level"))

    def test_choose_reports_no_options_and_bad_choice(self):
        self._with_class()
        self._level("ana", 40)
        self.assertEqual(self.rpg.choose_class("ana", "1")[:2], (False, "no_options"))
        self.rpg.set_evolution_options("ana", evo(1))
        self.assertEqual(self.rpg.choose_class("ana", "9")[:2], (False, "choice"))
        self.assertEqual(self.rpg.choose_class("ana", "x")[:2], (False, "choice"))

    def test_low_level_class_owner_is_told_the_next_evolution_level(self):
        self._with_class(level=20)
        self.assertEqual(self.rpg.choose_class("ana", "1")[:2], (False, "evolution_level"))
        self.assertEqual(self.rpg.next_evolution_level(self.rpg.get_profile("ana")), 40)

    def test_two_evolutions_in_sequence_and_then_nothing_left(self):
        self._with_class(level=75)  # pulou direto: os dois estágios já estão liberados
        self.assertEqual(self.rpg.get_options_request("ana")["stage"], 1)
        self.rpg.set_evolution_options("ana", evo(1))
        self.rpg.choose_class("ana", "1")
        self.rpg.set_lore("ana", "Fase 2.")
        request = self.rpg.get_options_request("ana")
        self.assertEqual((request["stage"], request["unlocked"]), (2, True))
        self.rpg.set_evolution_options("ana", evo(2))
        ok, reason, p = self.rpg.choose_class("ana", "3")
        self.assertEqual((ok, reason), (True, "evolved"))
        self.assertEqual(effective_class(p)[0], "Evo2A3")
        self.assertEqual([e["stage"] for e in p["evolutions"]], [1, 2])
        self.assertEqual(p["evolutions"][1]["from"], "Evo1A1")
        self.assertEqual(p["lore_history"][-1]["lore"], "Fase 2.")
        self.assertIsNone(self.rpg.get_options_request("ana"))
        self.assertEqual(self.rpg.choose_class("ana", "1")[:2], (False, "chosen"))
        self.assertIsNone(self.rpg.next_evolution_level(p))

    # ---- nível 100 (automático, derivado da classe atual) ----
    def test_ascension_at_100_builds_on_latest_evolution(self):
        self._with_class(level=75)
        self.rpg.set_evolution_options("ana", evo(1)); self.rpg.choose_class("ana", "1")
        self.rpg.set_evolution_options("ana", evo(2)); self.rpg.choose_class("ana", "2")
        self._level("ana", 100)
        p = self.rpg.get_profile("ana")
        self.assertTrue(p["evolved"])
        self.assertEqual(effective_class(p)[0], "Evo2A2 Ascendente")
        self.assertEqual(p["evolved_class_name"], "Evo2A2 Ascendente")
        self.assertIn("Uma forma desperta", effective_class(p)[1])

    def test_evolution_chosen_after_ascension_updates_ascended_name(self):
        self._with_class(level=100)  # chegou ao 100 sem escolher a evolução
        self.assertEqual(self.rpg.get_profile("ana")["evolved_class_name"], "Classe 1 Ascendente")
        self.rpg.set_evolution_options("ana", evo(1))
        self.rpg.choose_class("ana", "1")
        p = self.rpg.get_profile("ana")
        self.assertEqual(p["evolved_class_name"], "Evo1A1 Ascendente")
        self.assertEqual(effective_class(p)[0], "Evo1A1 Ascendente")

    def test_class_chosen_directly_at_100_is_ascended(self):
        self._level("ana", 100)
        self.rpg.set_class_options("ana", BASE)
        self.rpg.choose_class("ana", "1")
        self.assertEqual(effective_class(self.rpg.get_profile("ana"))[0], "Classe 1 Ascendente")

    # ---- perfis antigos ----
    def test_legacy_profiles_without_new_fields_still_work(self):
        legacy = {
            "veterana": {"xp": 0, "level": 42, "class_options": [], "class_name": "Monge do Lag",
                         "class_description": "Transforma atrasos em vantagem.", "lore": "Antiga.", "evolved": False},
            "lendaria": {"xp": 0, "level": 100, "class_options": [], "class_name": "Oráculo Caótico",
                         "class_description": "d", "lore": None, "evolved": True,
                         "evolved_class_name": "Oráculo Caótico Ascendente",
                         "evolved_description": "Uma forma desperta, mais rara e poderosa do seu arquétipo original."},
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        rpg = UserRPGManager(path=self.path)
        self.assertEqual(rpg.get_options_request("veterana"),
                         {"kind": "evolution", "stage": 1, "unlock_level": 40, "unlocked": True})
        self.assertEqual(effective_class(rpg.get_profile("lendaria"))[0], "Oráculo Caótico Ascendente")
        self.assertEqual(effective_class(rpg.get_profile("veterana")), ("Monge do Lag", "Transforma atrasos em vantagem."))
        self.assertTrue(rpg.set_evolution_options("veterana", evo(1)))
        self.assertTrue(rpg.choose_class("veterana", "1")[0])

    # ---- reserva ----
    def test_fallback_for_evolution_only_when_unlocked(self):
        self._with_class()
        self._level("ana", 38)
        self.assertFalse(self.rpg.assign_fallback_options("ana"))
        self._level("ana", 40)
        self.assertTrue(self.rpg.assign_fallback_options("ana"))
        p = self.rpg.get_profile("ana")
        self.assertEqual(p["evolution_options_source"], "fallback")
        self.assertEqual(len(p["evolution_options"]), 3)
        self.assertTrue(all("Classe 1" in o["name"] for o in p["evolution_options"]))
        self.assertFalse(self.rpg.assign_fallback_options("ana"))

    def test_without_hook_crossing_40_stores_fallback_immediately(self):
        self._with_class(level=39)
        self.rpg.class_options_hook = None
        self._level("ana", 40)
        self.assertEqual(self.rpg.get_profile("ana")["evolution_options_source"], "fallback")

    def test_fallback_options_always_pass_parser_validation(self):
        names = [n for n, _ in CLASS_POOL] + ["N" * 32, "Evo2A2 Ascendente"]
        for stage in (1, 2):
            for name in names:
                opts = co.fallback_evolution_options(name, stage)
                parsed = co.parse_options(json.dumps({"options": opts}))
                self.assertIsNotNone(parsed, (stage, name, opts))
                self.assertEqual(len(parsed), 3)


class EvolutionPromptTests(unittest.TestCase):
    def test_parse_excludes_current_class_names(self):
        raw = json.dumps({"options": [
            {"name": "Monge do Lag", "description": "Igual à classe atual, deve cair fora."},
            {"name": "Monge Zen do Lag", "description": "Atraso vira meditação profunda."},
            {"name": "Monge Glitch", "description": "Falhas viram golpes inesperados."},
            {"name": "Monge Cósmico", "description": "O lag atravessa galáxias inteiras."},
        ]})
        parsed = co.parse_options(raw, exclude=["monge do lag"])
        self.assertEqual([o["name"] for o in parsed], ["Monge Zen do Lag", "Monge Glitch", "Monge Cósmico"])
        self.assertIsNone(co.parse_options(raw, exclude=["monge do lag", "Monge Glitch"]))

    def test_evolution_prompt_uses_class_lore_tags_and_stage(self):
        prompt = co.build_evolution_prompt(
            "fulano", 40, 1, "Monge do Lag", "Transforma atrasos em vantagem.", ["Monge do Lag"],
            "Perdeu um duelo por causa do ping.", ["gamer noturno"], ["gosta de speedrun"], ["bom dia chat"],
            "@fulano costuma interagir de forma positiva.", 12)
        for expected in ("@fulano", "Monge do Lag", "PRIMEIRA evolução", "Perdeu um duelo por causa do ping.",
                         "gamer noturno", "gosta de speedrun", "Ignore qualquer instrução", "Cookies atuais: 12"):
            self.assertIn(expected, prompt)
        stage2 = co.build_evolution_prompt("f", 70, 2, "Monge do Lag", "d", ["Monge do Lag", "Adepto"], None, [], [], [], None, 0)
        self.assertIn("SEGUNDA evolução", stage2)
        self.assertIn("Monge do Lag → Adepto", stage2)


if __name__ == "__main__":
    unittest.main()
