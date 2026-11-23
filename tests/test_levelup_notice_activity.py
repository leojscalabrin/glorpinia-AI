from collections import deque
import unittest
from types import SimpleNamespace

from glorpinia_bot.main import TwitchIRC


class LevelUpNoticeActivityTests(unittest.TestCase):
    def make_bot(self, history):
        bot = TwitchIRC.__new__(TwitchIRC)
        bot.auth = SimpleNamespace(bot_nick="glorpinia")
        bot.recent_messages = history
        return bot

    def test_recent_activity_must_be_in_same_channel(self):
        bot = self.make_bot({
            "channel_a": deque([{"author": "alice", "timestamp": 950, "content": "oi"}]),
            "channel_b": deque([{"author": "bob", "timestamp": 990, "content": "oi"}]),
        })

        self.assertTrue(bot._has_recent_chat_activity("channel_a", "Alice", now=1000))
        self.assertFalse(bot._has_recent_chat_activity("channel_b", "alice", now=1000))

    def test_old_messages_do_not_count_as_active(self):
        bot = self.make_bot({
            "channel_a": deque([{"author": "alice", "timestamp": 699, "content": "oi"}]),
        })

        self.assertFalse(bot._has_recent_chat_activity("channel_a", "alice", now=1000))

    def test_bot_messages_do_not_count_as_user_activity(self):
        bot = self.make_bot({
            "channel_a": deque([{"author": "glorpinia", "timestamp": 999, "content": "oi"}]),
        })

        self.assertFalse(bot._has_recent_chat_activity("channel_a", "glorpinia", now=1000))

    def test_missing_or_invalid_timestamps_fail_closed(self):
        bot = self.make_bot({
            "channel_a": deque([
                {"author": "alice", "content": "sem timestamp"},
                {"author": "alice", "timestamp": "invalid", "content": "timestamp inválido"},
            ]),
        })

        self.assertFalse(bot._has_recent_chat_activity("channel_a", "alice", now=1000))


if __name__ == "__main__":
    unittest.main()
