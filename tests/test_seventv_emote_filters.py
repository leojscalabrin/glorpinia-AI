import unittest
from unittest.mock import patch

from glorpinia_bot.features.seventv_emote import MIN_CHANNELS, SevenTVEmote


class DummyBot:
    def send_message(self, *args, **kwargs):
        pass


class SevenTVEmoteFilterTests(unittest.TestCase):
    def setUp(self):
        self.feature = SevenTVEmote(DummyBot())

    def test_default_minimum_is_ten_channels(self):
        self.assertEqual(MIN_CHANNELS, 10)

    def test_trending_selection_is_uniform_random_choice(self):
        candidates = [
            {"id": "a", "name": "TrendA", "trending_score": 100, "channel_count": 1},
            {"id": "b", "name": "TrendB", "trending_score": 1, "channel_count": 0},
        ]
        with patch.object(self.feature, "_get_candidates", return_value=candidates) as get_candidates:
            with patch("glorpinia_bot.features.seventv_emote.random.choice", return_value=candidates[1]) as choose:
                with patch("glorpinia_bot.features.seventv_emote.random.choices") as weighted_choose:
                    name, _ = self.feature._emote_aleatorio(trending_only=True)

        self.assertEqual(name, "TrendB")
        get_candidates.assert_called_once_with(trending_only=True)
        choose.assert_called_once_with(candidates)
        weighted_choose.assert_not_called()

    def test_default_selection_uses_ten_channel_candidate_pool(self):
        candidates = [
            {"id": "a", "name": "PopularA", "trending_score": 0, "channel_count": 10},
            {"id": "b", "name": "PopularB", "trending_score": 0, "channel_count": 20},
        ]
        with patch.object(self.feature, "_get_candidates", return_value=candidates) as get_candidates:
            with patch("glorpinia_bot.features.seventv_emote.random.choices", return_value=[candidates[0]]) as choose:
                name, _ = self.feature._emote_aleatorio()

        self.assertEqual(name, "PopularA")
        get_candidates.assert_called_once_with(trending_only=False)
        choose.assert_called_once()


if __name__ == "__main__":
    unittest.main()
