import json
import os
import tempfile
import time
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
                return_value=[2, 7, 10, 4],
            ) as sample_pages:
                results = self.feature._search_emote_sample({"sortBy": "TOP_WEEKLY"})

        self.assertEqual({item["id"] for item in results}, {"first", "p2", "p7", "p10", "p4"})
        sample_pages.assert_called_once_with(range(2, 11), 4)
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
                return_value=[2],
            ):
                results = self.feature._search_emote_sample({"sortBy": "TOP_WEEKLY"})

        self.assertEqual([item["id"] for item in results], ["same", "first", "second"])


    def test_obscure_pool_uses_random_query_fragments(self):
        with patch.object(self.feature, "_random_hash", side_effect=["a7", "k2", "m9", "z4"]):
            with patch.object(self.feature, "_search_emotes", return_value={"items": []}) as search:
                self.feature._search_obscure_emotes()

        self.assertEqual(search.call_count, 4)
        self.assertEqual(
            [call.kwargs for call in search.call_args_list],
            [
                {"page": 1, "query": "a7"},
                {"page": 1, "query": "k2"},
                {"page": 1, "query": "m9"},
                {"page": 1, "query": "z4"},
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
        with patch.object(self.feature, "_search_emote_sample") as trending_search:
            with patch.object(self.feature, "_search_obscure_emotes", return_value=obscure):
                candidates, trending = self.feature._fetch_candidates()

        self.assertEqual({item["id"] for item in candidates}, {"min", "max"})
        self.assertEqual(trending, [])
        trending_search.assert_not_called()


    def test_default_selection_rejects_trending_sized_emotes_even_if_source_is_contaminated(self):
        candidates = [
            {"id": "valid", "name": "Valid", "channel_count": 42},
            {"id": "too_popular", "name": "TooPopular", "channel_count": 8900},
            {"id": "too_small", "name": "TooSmall", "channel_count": 9},
        ]
        with patch.object(self.feature, "_get_candidates", return_value=candidates):
            with patch(
                "glorpinia_bot.features.seventv_emote.random.choice",
                side_effect=lambda pool: pool[0],
            ) as choose:
                name, _ = self.feature._emote_aleatorio(trending_only=False)

        self.assertEqual(name, "Valid")
        choose.assert_called_once_with([candidates[0]])

    def test_persisted_cache_discards_candidates_outside_ten_to_one_hundred_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = os.path.join(directory, "cache.json")
            with open(cache_path, "w", encoding="utf-8") as cache_file:
                json.dump({
                    "schema_version": 2,
                    "updated_at": time.time(),
                    "candidates": [
                        {"id": "valid", "name": "Valid", "channel_count": 10},
                        {"id": "popular", "name": "Popular", "channel_count": 8900},
                        {"id": "missing", "name": "Missing"},
                    ],
                    "trending_candidates": [
                        {"id": "trend", "name": "Trend", "channel_count": 8900}
                    ],
                }, cache_file)

            with patch.dict(os.environ, {"SEVENTV_EMOTE_CACHE_FILE": cache_path}):
                feature = SevenTVEmote(DummyBot())

            self.assertEqual([item["id"] for item in feature._candidate_cache], ["valid"])
            # O pool trending continua intencionalmente independente do filtro.
            self.assertEqual([item["id"] for item in feature._trending_candidate_cache], ["trend"])


    def test_trending_refresh_does_not_search_obscure_pool(self):
        trending = [{
            "id": "trend", "defaultName": "Trend", "deleted": False,
            "flags": {"private": False, "nsfw": False, "publicListed": True},
            "scores": {"trendingWeek": 10}, "channels": {"totalCount": 9000},
        }]
        with patch.object(self.feature, "_search_emote_sample", return_value=trending) as trending_search:
            with patch.object(self.feature, "_search_obscure_emotes") as obscure_search:
                candidates, trending_candidates = self.feature._fetch_candidates(trending_only=True)

        self.assertEqual(candidates, [])
        self.assertEqual([item["id"] for item in trending_candidates], ["trend"])
        trending_search.assert_called_once_with({"sortBy": "TRENDING_WEEKLY", "order": "DESCENDING"})
        obscure_search.assert_not_called()

    def test_random_hash_is_two_lowercase_alphanumeric_characters(self):
        value = self.feature._random_hash()
        self.assertEqual(len(value), 2)
        self.assertTrue(value.isalnum())
        self.assertEqual(value, value.lower())


if __name__ == "__main__":
    unittest.main()
