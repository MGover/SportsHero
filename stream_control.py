import json
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass
class StreamCommand:
    cmd: str
    session_id: str = ""
    video_url: str = ""
    channel_id: str = ""
    guild_id: str = ""
    title: str = ""

    def to_json_line(self) -> str:
        payload: Dict[str, Any] = {
            "cmd": self.cmd,
            "session_id": self.session_id,
            "video_url": self.video_url,
            "channel_id": self.channel_id,
            "guild_id": self.guild_id,
            "title": self.title,
        }
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json_line(cls, line: str) -> Optional["StreamCommand"]:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None

        return cls(
            cmd=str(data.get("cmd", "")).strip(),
            session_id=str(data.get("session_id", "") or ""),
            video_url=str(data.get("video_url", "") or ""),
            channel_id=str(data.get("channel_id", "") or ""),
            guild_id=str(data.get("guild_id", "") or ""),
            title=str(data.get("title", "") or ""),
        )


def build_play_command(session_id: str, video_url: str, channel_id: str, guild_id: str, title: str = "") -> StreamCommand:
    return StreamCommand(
        cmd="play",
        session_id=session_id,
        video_url=video_url,
        channel_id=channel_id,
        guild_id=guild_id,
        title=title,
    )


def build_stop_command(session_id: str) -> StreamCommand:
    return StreamCommand(cmd="stop", session_id=session_id)


def build_leave_command(session_id: str) -> StreamCommand:
    return StreamCommand(cmd="leave", session_id=session_id)
