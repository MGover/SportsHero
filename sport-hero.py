import discord
from discord import app_commands
import xml.etree.ElementTree as ET
import requests
import subprocess
import re
from datetime import datetime, timedelta
import time
import asyncio
import os
import shutil
import json
import uuid
from pathlib import Path
from dotenv import load_dotenv # type: ignore

# Load environment variables
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
M3U_URL = os.getenv("M3U_URL")
EPG_URL = os.getenv("EPG_URL")

# Bot setup
intents = discord.Intents.all()
intents.voice_states = True
intents.messages = True
intents.guilds = True
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# m3u data
if not M3U_URL:
    raise RuntimeError("M3U_URL not set in environment")

pattern = r'(http[s]?://[^/]+)/get\.php\?username=([^&]*)&password=([^&]*)&type=(m3u_plus|m3u)'
match = re.match(pattern, M3U_URL)
if not match:
    raise RuntimeError("M3U_URL environment variable not in expected format")

url = match.group(1)
username = match.group(2)
password = match.group(3)
stream_url = url + "/player_api.php"
epg_url = f"{url}/xmltv.php?username={username}&password={password}"
params = {'username': username, 'password': password, 'action': "get_live_streams", 'catergory_id': ''}
CUSTOM_USER_AGENT = (
    "Connection: Keep-Alive User-Agent: okhttp/5.0.0-alpha.2 "
    "Accept-Encoding: gzip, deflate"
)
headers = {'User-Agent': CUSTOM_USER_AGENT}
proc_bun = None
epg_data = []
active_stream_session = None

async def start_streambot_process():
    """Start the Node selfbot once and keep it alive for all stream changes."""
    global proc_bun
    if proc_bun is not None and proc_bun.returncode is None:
        return proc_bun

    streambot_dir = Path(__file__).resolve().parent / "streambot"
    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("node not found in PATH; streambot cannot start")

    proc_bun = await asyncio.create_subprocess_exec(
        node_bin,
        "dist/index.js",
        cwd=str(streambot_dir),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    await asyncio.sleep(2)
    if proc_bun.returncode is not None:
        stdout_data = await proc_bun.stdout.read() if proc_bun.stdout else b""
        stderr_data = await proc_bun.stderr.read() if proc_bun.stderr else b""
        stdout_text = stdout_data.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
        detail_parts = [part for part in [stdout_text, stderr_text] if part]
        detail = "\n".join(detail_parts) if detail_parts else "streambot process exited without output"
        raise RuntimeError(f"streambot failed to start: {detail}")

    print("DEBUG streambot: started successfully and is still running")
    return proc_bun

async def send_streambot_command(command: dict):
    global proc_bun
    proc = await start_streambot_process()
    if proc.stdin is None:
        raise RuntimeError("streambot stdin is unavailable")
    payload = (json.dumps(command, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    proc.stdin.write(payload)
    await proc.stdin.drain()
    return proc

async def stop_current_stream():
    global active_stream_session, proc_bun
    if not active_stream_session:
        return

    if proc_bun is not None and proc_bun.returncode is None and proc_bun.stdin:
        await send_streambot_command({"cmd": "stop", "session_id": active_stream_session})
    active_stream_session = None

async def fetch_epg():
    """Fetch and populate the global `epg_data` list with (title, channel_id) tuples."""
    global epg_url, headers, epg_data
    try:
        resp = await asyncio.to_thread(requests.post, epg_url, headers=headers, timeout=10)
    except Exception as e:
        print(f"Error fetching EPG: {e}")
        return

    if resp.status_code != 200:
        print(f"Error fetching EPG: {resp.status_code}")
        return

    xml_content = resp.content
    root = ET.fromstring(xml_content)

    now = datetime.utcnow()
    epg_data.clear()
    for prog in root.findall('.//programme'):
        if prog is None:
            continue
        title_el = prog.find('title')
        if title_el is None or title_el.text is None:
            continue
        title = title_el.text.strip()
        channel = prog.get('channel')
        start_time = parse_epg_time(prog.get('start'))
        stop_time = parse_epg_time(prog.get('stop'))
        if start_time <= now <= stop_time:
            epg_data.append((title, channel))

def parse_epg_time(epg_time):
    """Parses EPG time formats like 'YYYYMMDDHHMMSS', 'YYYYMMDDHHMMSS+ZZZZ' or with a space before TZ.
    Returns a UTC datetime.
    """
    if not epg_time:
        return datetime.min

    s = epg_time.strip()
    time_str = s[:14]
    try:
        dt = datetime.strptime(time_str, "%Y%m%d%H%M%S")
    except Exception:
        return datetime.min

    tz_part = s[14:].strip()
    if tz_part:
        # tz_part examples: '+0000', '-0200', '+02'
        if tz_part[0] in ('+', '-'):
            try:
                sign = 1 if tz_part[0] == '+' else -1
                hours = int(tz_part[1:3])
                # Convert to UTC by subtracting the offset
                dt = dt - timedelta(hours=sign * hours)
            except Exception:
                pass

    return dt

async def fetch_m3u():
    global stream_url
    global params
    global headers
    try:
        resp = await asyncio.to_thread(requests.post, stream_url, data=params, headers=headers, timeout=10)
    except Exception as e:
        print(f"Error fetching M3U: {e}")
        return []

    if resp.status_code == 200:
        try:
            return resp.json()
        except Exception:
            return []
    else:
        print(f"Error fetching M3U: {resp.status_code}")
        return []

def find_channel(query):
    for title, channel_id in epg_data:
        if channel_id is None:
            continue
        if query.lower() in title.lower():
            return channel_id
    return None

async def get_current_voice_channel(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    guild = interaction.guild or (bot.get_guild(guild_id) if guild_id else None)
    print(f"DEBUG voice check: user={interaction.user.id} guild_id={guild_id} guild_obj={guild}")
    print(f"DEBUG voice check: bot.guilds_has_target={bool(guild_id and any(g.id == guild_id for g in bot.guilds))}")

    if interaction.user is not None and getattr(interaction.user, "voice", None) is not None:
        channel = interaction.user.voice.channel
        print(f"DEBUG voice check: interaction.user.voice.channel={channel.id if channel else None}")
        return channel

    if guild is None:
        print("DEBUG voice check: guild is None; bot is not in the guild or cache is stale")
        return None

    member = guild.get_member(interaction.user.id)
    print(f"DEBUG voice check: guild.get_member returned={member}")

    if member is None:
        try:
            member = await guild.fetch_member(interaction.user.id)
            print(f"DEBUG voice check: guild.fetch_member returned={member}")
        except discord.NotFound:
            print("DEBUG voice check: fetch_member returned NotFound; falling back to guild voice_states cache")
            voice_state = None
            if hasattr(guild, "voice_states") and isinstance(guild.voice_states, dict):
                voice_state = guild.voice_states.get(interaction.user.id)
            if voice_state and getattr(voice_state, "channel", None) is not None:
                print(f"DEBUG voice check: guild.voice_states channel={voice_state.channel.id}")
                return voice_state.channel
            print("DEBUG voice check: no guild voice state found for user")
            return None
        except Exception as e:
            print(f"DEBUG voice check: fetch_member failed: {e}")
            return None

    if member is None:
        print("DEBUG voice check: member is None")
        return None

    voice_state = member.voice
    if voice_state is None and hasattr(guild, "voice_states") and isinstance(guild.voice_states, dict):
        voice_state = guild.voice_states.get(interaction.user.id)

    print(f"DEBUG voice check: member.voice={voice_state}")
    if voice_state is None or getattr(voice_state, "channel", None) is None:
        print("DEBUG voice check: member not in voice")
        return None

    channel = voice_state.channel
    print(f"DEBUG voice check: resolved channel={channel.id if channel else None} name={channel.name if channel else None}")
    return channel

@tree.command(name="watch", description="Watch a live TV channel")
async def watch(interaction: discord.Interaction, searchterm: str):
    print(f"DEBUG watch command: user={interaction.user.id} guild={interaction.guild_id} searchterm={searchterm}")
    voice_channel = await get_current_voice_channel(interaction)
    if voice_channel is None:
        print("DEBUG watch command: no voice channel found for user")
        await interaction.response.send_message("You need to be in a voice channel to use this command.", ephemeral=True)
        return
    print(f"DEBUG watch command: resolved voice_channel={voice_channel.id} name={voice_channel.name}")

    global url
    global username
    global password
    global active_stream_session
    container_extension = "m3u8"
    await interaction.response.defer()

    channel_id = find_channel(searchterm)
    if not channel_id:
        await interaction.followup.send("No matching channel found.")
        return

    m3u_content = await fetch_m3u()
    channel_url = None

    for line in m3u_content:
        try:
            if str(line.get("epg_channel_id")) == str(channel_id):
                container_extension = line.get("container_extension", "m3u8")
                stream_id = line.get("stream_id")
                stream_type = line.get("stream_type")
                channel_url = f"{url}/{stream_type}/{username}/{password}/{stream_id}.{container_extension}"
                break
        except Exception:
            continue

    print(channel_url)
    if not channel_url:
        await interaction.followup.send("Channel stream not found.")
        return

    guild = interaction.guild_id
    channel = voice_channel
    session_id = str(uuid.uuid4())

    try:
        await start_streambot_process()
    except Exception as e:
        print(f"DEBUG streambot startup failed: {e}")
        await interaction.followup.send(f"Streambot failed to start: {e}")
        return

    if active_stream_session:
        print(f"DEBUG stream switch: stopping prior session {active_stream_session} before starting {session_id}")
        await stop_current_stream()
        await asyncio.sleep(0.75)

    active_stream_session = session_id
    await interaction.followup.send(f"Streaming **{searchterm}** in the voice channel!")
    try:
        await send_streambot_command({
            "cmd": "play",
            "session_id": session_id,
            "video_url": channel_url,
            "channel_id": str(channel.id),
            "guild_id": str(guild),
            "title": searchterm,
        })
    except Exception as e:
        stderr_data = await proc_bun.stderr.read() if proc_bun and proc_bun.stderr else b""
        stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
        print(f"DEBUG streambot stdin write failed: {e}")
        if stderr_text:
            print(f"DEBUG streambot stderr: {stderr_text}")
        active_stream_session = None
        await interaction.followup.send(f"Failed to send stream payload: {e}")
        return

@tree.command(name="stop", description="stop the current stream")
async def stop(interaction: discord.Interaction):
    await interaction.response.send_message("Stopping the current stream.")
    global proc_bun, active_stream_session
    try:
        await stop_current_stream()
    except Exception as e:
        print(f"Error sending stop to streambot: {e}")
    finally:
        active_stream_session = None
        proc_bun = proc_bun

@tree.command(name="watch_channel", description="Choose from channels")
async def watch_channel(interaction: discord.Interaction, channel_id: str):
    print(f"DEBUG watch_channel command: user={interaction.user.id} guild={interaction.guild_id} channel_id={channel_id}")
    voice_channel = await get_current_voice_channel(interaction)
    if voice_channel is None:
        print("DEBUG watch_channel command: no voice channel found for user")
        await interaction.response.send_message("You need to be in a voice channel to use this command.", ephemeral=True)
        return
    print(f"DEBUG watch_channel command: resolved voice_channel={voice_channel.id} name={voice_channel.name}")

    global url
    global username
    global password
    global active_stream_session
    container_extension = "m3u8"
    await interaction.response.defer()

    m3u_content = await fetch_m3u()
    channel_url = None

    for line in m3u_content:
        try:
            if str(line.get("epg_channel_id")) == str(channel_id):
                container_extension = line.get("container_extension", "m3u8")
                stream_id = line.get("stream_id")
                stream_type = line.get("stream_type")
                channel_url = f"{url}/{stream_type}/{username}/{password}/{stream_id}.{container_extension}"
                break
        except Exception:
            continue

    print(channel_url)
    if not channel_url:
        await interaction.followup.send("Channel stream not found.")
        return

    guild = interaction.guild_id
    channel = voice_channel
    session_id = str(uuid.uuid4())

    try:
        await start_streambot_process()
    except Exception as e:
        print(f"DEBUG streambot startup failed: {e}")
        await interaction.followup.send(f"Streambot failed to start: {e}")
        return

    if active_stream_session:
        print(f"DEBUG stream switch: stopping prior session {active_stream_session} before starting {session_id}")
        await stop_current_stream()
        await asyncio.sleep(0.75)

    active_stream_session = session_id
    await interaction.followup.send(f"Streaming **{channel_id}** in the voice channel!")
    try:
        await send_streambot_command({
            "cmd": "play",
            "session_id": session_id,
            "video_url": channel_url,
            "channel_id": str(channel.id),
            "guild_id": str(guild),
            "title": channel_id,
        })
    except Exception as e:
        stderr_data = await proc_bun.stderr.read() if proc_bun and proc_bun.stderr else b""
        stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
        print(f"DEBUG streambot stdin write failed: {e}")
        if stderr_text:
            print(f"DEBUG streambot stderr: {stderr_text}")
        active_stream_session = None
        await interaction.followup.send(f"Failed to send stream payload: {e}")
        return

@watch.autocomplete("searchterm")
async def watch_autocomplete(interaction: discord.Interaction, current: str):
    current = (current or "").strip()
    if not current:
        return []
    return [app_commands.Choice(name=title, value=title) for title, channel in epg_data if title and current.lower() in title.lower()][:25]

@watch_channel.autocomplete("channel_id")
async def watch_channel_autocomplete(interaction: discord.Interaction, current: str):
    current = (current or "").strip()
    if not current:
        return []
    return [app_commands.Choice(name=channel, value=channel) for title, channel in epg_data if channel and current.lower() in str(channel).lower()][:25]

@bot.event
async def on_ready():
    await fetch_epg()
    await tree.sync()
    print(f'Logged in as {bot.user}')

bot.run(TOKEN)
