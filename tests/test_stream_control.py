import unittest

from stream_control import StreamCommand, build_play_command, build_stop_command
from channel_search import rank_catalog_channels, rank_search_matches


class StreamControlTests(unittest.TestCase):
    def test_channel_search_matches_regional_station_name(self):
        channels = [
            {"name": "US| CBS 13 SACRAMENTO CA (KOVR)", "stream_id": "173140"},
            {"name": "US| CBS 5 SAN FRANCISCO CA (KPIX)", "stream_id": "173141"},
        ]

        matches = rank_search_matches("cbs sacramento", channels, lambda channel: channel["name"], limit=2)

        self.assertEqual(matches[0][1]["stream_id"], "173140")

    def test_channel_search_matches_affiliate_callsign_and_network_alias(self):
        channels = [
            {"name": "US| CBS 13 SACRAMENTO CA", "epg_channel_id": "loc.CBS (KOVR) Sacramento, CA", "stream_id": "173140"},
            {"name": "US| ABC 10 SACRAMENTO CA", "epg_channel_id": "loc.ABC (KXTV) Sacramento, CA", "stream_id": "172932"},
        ]

        kovr_matches = rank_catalog_channels("KOVR", channels, limit=2)
        cbs_matches = rank_catalog_channels("CBS Sacramento", channels, limit=2)
        kxtv_matches = rank_catalog_channels("KXTV", channels, limit=2)

        self.assertEqual(kovr_matches[0][1]["stream_id"], "173140")
        self.assertEqual(cbs_matches[0][1]["stream_id"], "173140")
        self.assertEqual(kxtv_matches[0][1]["stream_id"], "172932")

    def test_nfl_network_query_prefers_us_epg_mapping(self):
        channels = [
            {"name": "MXC| NFL NETWORK", "epg_channel_id": "", "stream_id": "1870426"},
            {"name": "US| NFL NETWORK HD", "epg_channel_id": "NFLNetwork.us", "stream_id": "45526"},
        ]

        matches = rank_catalog_channels("NFL Network", channels, limit=2)

        self.assertEqual(matches[0][1]["stream_id"], "45526")

    def test_fast_catalog_autocomplete_matches_prefixes_and_aliases(self):
        channels = [
            {"name": "US| CBS 13 SACRAMENTO CA", "epg_channel_id": "loc.CBS (KOVR) Sacramento, CA", "stream_id": "173140"},
            {"name": "MXC| NFL NETWORK", "epg_channel_id": "", "stream_id": "1870426"},
            {"name": "US| NFL NETWORK HD", "epg_channel_id": "NFLNetwork.us", "stream_id": "45526"},
        ]

        cbs_matches = rank_catalog_channels("KOVR", channels, limit=2, fast_autocomplete=True)
        nfl_matches = rank_catalog_channels("NFL Net", channels, limit=2, fast_autocomplete=True)

        self.assertEqual(cbs_matches[0][1]["stream_id"], "173140")
        self.assertEqual(nfl_matches[0][1]["stream_id"], "1870426")

    def test_channel_search_matches_show_with_quality_and_playlist_prefixes(self):
        channels = [
            {"name": "US| 24/7 KING OF THE HILL", "stream_id": "559534"},
            {"name": "US| SOUTH PARK FHD", "stream_id": "1430221"},
        ]

        king_matches = rank_search_matches("King of the Hill", channels, lambda channel: channel["name"])
        south_park_matches = rank_search_matches("south-park", channels, lambda channel: channel["name"])

        self.assertEqual(king_matches[0][1]["stream_id"], "559534")
        self.assertEqual(south_park_matches[0][1]["stream_id"], "1430221")

    def test_play_command_has_session_and_payload(self):
        command = build_play_command(
            session_id="sess-123",
            video_url="https://example.com/live.m3u8",
            channel_id="999",
            guild_id="777",
            title="Test channel",
        )

        self.assertEqual(command.cmd, "play")
        self.assertEqual(command.session_id, "sess-123")
        self.assertEqual(command.video_url, "https://example.com/live.m3u8")
        self.assertEqual(command.channel_id, "999")
        self.assertEqual(command.guild_id, "777")
        self.assertEqual(command.title, "Test channel")

        payload = command.to_json_line()
        self.assertIn('"cmd":"play"', payload)
        self.assertIn('"session_id":"sess-123"', payload)
        self.assertIn('"video_url":"https://example.com/live.m3u8"', payload)

    def test_stop_command_is_clean_and_session_scoped(self):
        command = build_stop_command(session_id="sess-456")
        self.assertEqual(command.cmd, "stop")
        self.assertEqual(command.session_id, "sess-456")
        self.assertIn('"cmd":"stop"', command.to_json_line())
        self.assertIn('"session_id":"sess-456"', command.to_json_line())

    def test_leave_command_is_explicit_and_session_scoped(self):
        command = build_leave_command(session_id="sess-789")
        self.assertEqual(command.cmd, "leave")
        self.assertEqual(command.session_id, "sess-789")
        self.assertIn('"cmd":"leave"', command.to_json_line())
        self.assertIn('"session_id":"sess-789"', command.to_json_line())


if __name__ == "__main__":
    unittest.main()
