import unittest
from unittest.mock import Mock

from glorpinia_bot.emote_manager import EmoteManager
from glorpinia_bot.main import TwitchIRC


class LifecycleMessageTests(unittest.TestCase):
    def test_mentions_are_not_removed_as_emotes(self):
        manager = EmoteManager(base_path=".")
        manager.global_emote_map = {"neutral": ["glorp"]}
        manager.channel_emote_map = {}

        self.assertEqual(
            manager.remove_known_emotes("Boa live @glorp glorp"),
            "Boa live @glorp",
        )
        self.assertEqual(manager.strip_trailing_emote("Boa live @glorp"), "Boa live @glorp")

    def test_lifecycle_message_reintroduces_missing_streamer_name(self):
        bot = TwitchIRC.__new__(TwitchIRC)

        self.assertEqual(
            bot._ensure_streamer_name_in_lifecycle_message(
                "glorp", "Até que enfim apareceu pra consertar a nave", "stream_welcome"
            ),
            "@glorp Até que enfim apareceu pra consertar a nave",
        )
        self.assertEqual(
            bot._ensure_streamer_name_in_lifecycle_message(
                "glorp", "@glorp finalmente chegou", "stream_welcome"
            ),
            "@glorp finalmente chegou",
        )

    def test_comment_is_silently_synced_with_live_state(self):
        bot = TwitchIRC.__new__(TwitchIRC)
        bot.comment_feature = Mock()
        bot.channel_feature_states = {"glorp": {"chat": True, "listen": False, "comment": True}}
        bot._save_channel_feature_states = Mock()
        bot.send_message = Mock()

        # Live ON deve desligar Comment.
        bot._sync_comment_with_live_status("glorp", True)
        self.assertFalse(bot.is_feature_enabled("glorp", "comment"))
        bot.comment_feature.set_enabled.assert_called_once_with("glorp", False)

        # Live OFF deve reativar Comment.
        bot.comment_feature.set_enabled.reset_mock()
        bot._sync_comment_with_live_status("glorp", False)
        self.assertTrue(bot.is_feature_enabled("glorp", "comment"))
        bot.comment_feature.set_enabled.assert_called_once_with("glorp", True)

        # A sincronização não deve publicar notificações no chat.
        bot.send_message.assert_not_called()

    def test_zero_width_emote_is_sent_with_non_zero_width_companion(self):
        manager = EmoteManager(base_path=".")
        manager.global_emote_map = {"neutral": ["base", "overlay"]}
        manager.channel_emote_map = {}
        manager.zero_width_emotes = {"overlay"}

        self.assertEqual(manager._find_zero_width_companion("overlay", ["overlay", "base"]), "base")


if __name__ == "__main__":
    unittest.main()
