import unittest

from stream_control import StreamCommand, build_play_command, build_stop_command


class StreamControlTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
