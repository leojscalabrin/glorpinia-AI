import unittest
from types import SimpleNamespace
from unittest import mock

from glorpinia_bot.features.fortune_cookie import FortuneCookie

PROVERB = "glorp ⛩️🦊 A água que contorna a pedra chega ao mar sem pressa."
OLD_STYLE = PROVERB + " - ...os espíritos riram dessa sua sorte. Onde está meu Tofu? glorp"


class _SyncThread:
    """Executa o alvo na hora, para testar o fluxo completo sem concorrência."""
    def __init__(self, target=None, args=(), kwargs=None, **_):
        self._target, self._args, self._kwargs = target, args, kwargs or {}
        self.daemon = False

    def start(self):
        self._target(*self._args, **self._kwargs)


class FortuneCookieTests(unittest.TestCase):
    def _bot(self, response, credited=True, with_cookie_system=True):
        bot = SimpleNamespace()
        bot.sent_long, bot.sent, bot.prompts, bot.cookies = [], [], [], []

        def add_cookies(nick, n):
            bot.cookies.append((nick, n))
            return credited
        bot.cookie_system = SimpleNamespace(add_cookies=add_cookies) if with_cookie_system else None
        bot.training_logger = SimpleNamespace(log_interaction=lambda *a, **k: None)
        bot.memory_mgr = object()
        bot.get_live_context = lambda ch: None

        def get_response(query, channel, author, memory_mgr, skip_search, live_context):
            bot.prompts.append(query)
            return response
        bot.gemini_client = SimpleNamespace(get_response=get_response)
        bot.send_long_message = lambda ch, msg: bot.sent_long.append(msg)
        bot.send_message = lambda ch, msg: bot.sent.append(msg)
        return bot

    def _run(self, response, gain=4, **bot_options):
        bot = self._bot(response, **bot_options)
        feature = FortuneCookie(bot)
        with mock.patch("glorpinia_bot.features.fortune_cookie.threading.Thread", _SyncThread), \
             mock.patch("glorpinia_bot.features.fortune_cookie.random.sample", return_value=[41, 5, 1, 60, 13, 2]), \
             mock.patch("glorpinia_bot.features.fortune_cookie.random.randint", return_value=gain):
            feature.get_fortune("canal", "ana")
        return bot

    # ---- números da sorte ----
    def test_lucky_numbers_are_hyphenated_without_spaces_and_zero_padded(self):
        self.assertEqual(FortuneCookie._format_lucky_numbers([1, 2, 13, 41, 55, 60]), "01-02-13-41-55-60")

    def test_final_message_has_sorted_hyphenated_numbers(self):
        bot = self._run(PROVERB)
        self.assertEqual(bot.sent_long, [PROVERB + " | 🍀 Números da sorte: [01-02-05-13-41-60] | 🍪 +4 cookies"])
        self.assertNotIn(" - ", bot.sent_long[0])
        self.assertEqual(bot.cookies, [("ana", 4)])

    # ---- comentário ----
    def test_prompt_no_longer_asks_for_a_persona_comment(self):
        prompt = FortuneCookie(self._bot(PROVERB))._build_prompt("ana")
        self.assertNotIn("COMENTÁRIO", prompt)
        self.assertNotIn("PERSONA GLOPSUNE", prompt)
        self.assertNotIn("Tofu", prompt)
        self.assertIn("NÃO adicione nada depois da frase", prompt)
        self.assertIn("NÃO gere números de sorte", prompt)
        self.assertIn("Comece a resposta com 'glorp'", prompt)

    def test_comment_is_removed_even_if_the_model_ignores_the_prompt(self):
        bot = self._run(OLD_STYLE)
        self.assertEqual(bot.sent_long, [PROVERB + " | 🍀 Números da sorte: [01-02-05-13-41-60] | 🍪 +4 cookies"])
        self.assertNotIn("Tofu", bot.sent_long[0])

    def test_strip_comment_handles_separator_variants(self):
        for sep in (" - ", " – ", " — "):
            self.assertEqual(FortuneCookie._strip_comment(f"{PROVERB}{sep}comentário extra"), PROVERB)

    def test_strip_comment_keeps_only_the_first_part_when_there_are_several(self):
        self.assertEqual(FortuneCookie._strip_comment("Frase. - um - dois"), "Frase.")

    def test_strip_comment_leaves_clean_phrases_and_inner_hyphens_alone(self):
        self.assertEqual(FortuneCookie._strip_comment(PROVERB), PROVERB)
        self.assertEqual(FortuneCookie._strip_comment("Leve o guarda-chuva e o bem-estar."), "Leve o guarda-chuva e o bem-estar.")

    def test_strip_comment_never_returns_empty(self):
        self.assertEqual(FortuneCookie._strip_comment(" - só comentário"), "- só comentário")

    # ---- comportamento existente preservado ----
    def test_daily_cooldown_still_applies(self):
        bot = self._bot(PROVERB)
        feature = FortuneCookie(bot)
        with mock.patch("glorpinia_bot.features.fortune_cookie.threading.Thread", _SyncThread):
            feature.get_fortune("canal", "ana")
            feature.get_fortune("canal", "ana")
        self.assertEqual(len(bot.sent_long), 1)
        self.assertIn("templo está fechado", bot.sent[0])

    def test_api_failure_still_reports_the_cookies_already_credited(self):
        bot = self._run(None, gain=7)
        self.assertEqual(bot.sent_long, [])
        self.assertEqual(bot.sent, ["@ana, os espíritos silenciaram... (Erro na API) Sadge | 🍪 +7 cookies"])
        self.assertEqual(bot.cookies, [("ana", 7)])

    def test_api_failure_message_is_unchanged_when_nothing_was_credited(self):
        bot = self._run(None, credited=False)
        self.assertEqual(bot.sent, ["@ana, os espíritos silenciaram... (Erro na API) Sadge"])

    # ---- ganho de cookies ----
    def test_gain_text_uses_singular_and_plural(self):
        self.assertEqual(FortuneCookie._format_cookie_gain(1), "🍪 +1 cookie")
        self.assertEqual(FortuneCookie._format_cookie_gain(2), "🍪 +2 cookies")
        self.assertEqual(FortuneCookie._format_cookie_gain(10), "🍪 +10 cookies")

    def test_message_shows_singular_when_user_won_one_cookie(self):
        bot = self._run(PROVERB, gain=1)
        self.assertTrue(bot.sent_long[0].endswith("[01-02-05-13-41-60] | 🍪 +1 cookie"))

    def test_gain_is_not_shown_when_credit_was_not_confirmed(self):
        bot = self._run(PROVERB, credited=False)
        self.assertEqual(bot.sent_long, [PROVERB + " | 🍀 Números da sorte: [01-02-05-13-41-60]"])
        self.assertNotIn("🍪", bot.sent_long[0])

    def test_message_works_without_cookie_system(self):
        bot = self._run(PROVERB, with_cookie_system=False)
        self.assertEqual(bot.sent_long, [PROVERB + " | 🍀 Números da sorte: [01-02-05-13-41-60]"])
        self.assertEqual(bot.cookies, [])


class AddCookiesReturnTests(unittest.TestCase):
    """add_cookies precisa dizer se creditou, para o *cookie não anunciar um ganho que não houve."""

    def setUp(self):
        import os, tempfile
        from glorpinia_bot.features.cookie_system import CookieSystem
        self._cwd = os.getcwd()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.chdir(tmp.name)  # o CookieSystem cria glorpinia_cookies.db no diretório atual
        self.addCleanup(os.chdir, self._cwd)
        self.cs = CookieSystem(None)

    def test_returns_true_and_credits_the_amount(self):
        self.assertTrue(self.cs.add_cookies("ana", 5, award_xp=False))
        self.assertEqual(self.cs.get_cookies("ana"), 5)
        self.assertTrue(self.cs.add_cookies("ana", 3, award_xp=False))
        self.assertEqual(self.cs.get_cookies("ana"), 8)

    def test_returns_false_for_invalid_or_forbidden_nicks(self):
        self.assertFalse(self.cs.add_cookies("", 5, award_xp=False))
        self.assertFalse(self.cs.add_cookies("nightbot", 5, award_xp=False))
        self.assertEqual(self.cs.get_cookies("nightbot"), 0)

    def test_returns_false_when_database_write_fails(self):
        self.cs.db_path = "/nonexistent-dir/x.db"
        self.assertFalse(self.cs.add_cookies("ana", 5, award_xp=False))

    def test_still_true_when_only_the_xp_step_fails(self):
        # Sem bot, o passo de XP levanta exceção, mas os cookies já foram gravados.
        self.assertTrue(self.cs.add_cookies("ana", 4))
        self.assertEqual(self.cs.get_cookies("ana"), 4)


if __name__ == "__main__":
    unittest.main()
