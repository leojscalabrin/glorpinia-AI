import unittest
from unittest.mock import patch

from glorpinia_bot.features.seventv_emote import MAX_CHANNELS, MIN_CHANNELS, SevenTVEmote


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

    def test_default_selection_is_uniform_random_from_ten_channel_pool(self):
        candidates = [
            {"id": "a", "name": "PopularA", "trending_score": 0, "channel_count": 10},
            {"id": "b", "name": "PopularB", "trending_score": 0, "channel_count": 20},
        ]
        with patch.object(self.feature, "_get_candidates", return_value=candidates) as get_candidates:
            with patch("glorpinia_bot.features.seventv_emote.random.choice", return_value=candidates[1]) as choose:
                with patch("glorpinia_bot.features.seventv_emote.random.choices") as weighted_choose:
                    name, _ = self.feature._emote_aleatorio()

        self.assertEqual(name, "PopularB")
        get_candidates.assert_called_once_with(trending_only=False)
        choose.assert_called_once_with(candidates)
        weighted_choose.assert_not_called()


    def test_search_samples_random_pages_across_full_result_set(self):
        first_page = {"totalCount": 300, "items": [{"id": "first"}]}
        other_pages = [
            {"items": [{"id": "p2"}]},
            {"items": [{"id": "p7"}]},
            {"items": [{"id": "p10"}]},
            {"items": [{"id": "p4"}]},
        ]
        with patch.object(
            self.feature,
            "_search_emotes",
            side_effect=[first_page, *other_pages],
        ) as search:
            with patch(
                "glorpinia_bot.features.seventv_emote.random.sample",
                return_value=[2, 7, 10, 4, 1],
            ) as sample_pages:
                results = self.feature._search_emote_sample({"sortBy": "TOP_WEEKLY"})

        self.assertEqual({item["id"] for item in results}, {"first", "p2", "p7", "p10", "p4"})
        sample_pages.assert_called_once_with(range(1, 11), 5)
        self.assertEqual(
            [call.kwargs["page"] for call in search.call_args_list],
            [1, 2, 7, 10, 4],
        )

    def test_search_sample_deduplicates_emotes_returned_on_multiple_pages(self):
        first_page = {"totalCount": 60, "items": [{"id": "same"}, {"id": "first"}]}
        second_page = {"items": [{"id": "same"}, {"id": "second"}]}
        with patch.object(
            self.feature,
            "_search_emotes",
            side_effect=[first_page, second_page],
        ):
            with patch(
                "glorpinia_bot.features.seventv_emote.random.sample",
                return_value=[1, 2],
            ):
                results = self.feature._search_emote_sample({"sortBy": "TOP_WEEKLY"})

        self.assertEqual([item["id"] for item in results], ["same", "first", "second"])


    def test_obscure_pool_uses_random_query_fragments(self):
        with patch.object(self.feature, "_random_hash", side_effect=["a7", "k2", "m9", "z4"]):
            with patch.object(self.feature, "_search_emote_sample", return_value=[]) as search:
                self.feature._search_obscure_emotes()

        self.assertEqual(search.call_count, 4)
        self.assertEqual(
            [call.kwargs for call in search.call_args_list],
            [
                {"query": "a7", "max_pages": 3},
                {"query": "k2", "max_pages": 3},
                {"query": "m9", "max_pages": 3},
                {"query": "z4", "max_pages": 3},
            ],
        )

    def test_default_pool_keeps_only_emotes_between_ten_and_one_hundred_channels(self):
        def emote(identifier, channels):
            return {
                "id": identifier,
                "defaultName": identifier,
                "deleted": False,
                "flags": {"private": False, "nsfw": False, "publicListed": True},
                "scores": {"trendingWeek": 0},
                "channels": {"totalCount": channels},
            }

        obscure = [
            emote("below", 9),
            emote("min", MIN_CHANNELS),
            emote("max", MAX_CHANNELS),
            emote("above", MAX_CHANNELS + 1),
        ]
        with patch.object(self.feature, "_search_emote_sample", return_value=[]):
            with patch.object(self.feature, "_search_obscure_emotes", return_value=obscure):
                candidates, trending = self.feature._fetch_candidates()

        self.assertEqual({item["id"] for item in candidates}, {"min", "max"})
        self.assertEqual(trending, [])

    def test_random_hash_is_two_lowercase_alphanumeric_characters(self):
        value = self.feature._random_hash()
        self.assertEqual(len(value), 2)
        self.assertTrue(value.isalnum())
        self.assertEqual(value, value.lower())


if __name__ == "__main__":
    unittest.main()
