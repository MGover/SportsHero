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
from channel_search import rank_catalog_channels, rank_search_matches

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
provider_epg_url = f"{url}/xmltv.php?username={username}&password={password}"
epg_urls = [EPG_URL.strip()] if EPG_URL and EPG_URL.strip() else []
if provider_epg_url not in epg_urls:
    epg_urls.append(provider_epg_url)
epg_url = epg_urls[0]
params = {'username': username, 'password': password, 'action': "get_live_streams", 'catergory_id': ''}
CUSTOM_USER_AGENT = (
    "Connection: Keep-Alive User-Agent: okhttp/5.0.0-alpha.2 "
    "Accept-Encoding: gzip, deflate"
)
headers = {'User-Agent': CUSTOM_USER_AGENT}
proc_bun = None
epg_data = []
m3u_data = []
m3u_fetched_at = 0.0
m3u_refresh_task = None
active_stream_session = None
M3U_CACHE_SECONDS = 300

async def _forward_subprocess_output(stream, prefix: str, ready_event=None):
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").strip()
        if text:
            print(f"[streambot:{prefix}] {text}")
            if prefix == "stdout" and ready_event is not None and "Selfbot ready:" in text:
                ready_event.set()

async def start_streambot_process():
    """Start the Node selfbot once and keep it alive for all stream changes."""
    global proc_bun
    if proc_bun is not None and proc_bun.returncode is None:
        return proc_bun

    streambot_dir = Path(__file__).resolve().parent / "streambot"
    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("node not found in PATH; streambot cannot start")

    ready_event = asyncio.Event()
    proc_bun = await asyncio.create_subprocess_exec(
        node_bin,
        "dist/index.js",
        cwd=str(streambot_dir),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    asyncio.create_task(_forward_subprocess_output(proc_bun.stdout, "stdout", ready_event))
    asyncio.create_task(_forward_subprocess_output(proc_bun.stderr, "stderr"))

    ready_task = asyncio.create_task(ready_event.wait())
    exit_task = asyncio.create_task(proc_bun.wait())
    done, pending = await asyncio.wait(
        (ready_task, exit_task),
        timeout=30,
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    if ready_task not in done:
        if proc_bun.returncode is None:
            proc_bun.terminate()
            await proc_bun.wait()
        proc_bun = None
        if exit_task in done:
            raise RuntimeError("streambot exited before Discord login completed")
        raise RuntimeError("streambot did not become ready within 30 seconds")

    print("DEBUG streambot: Discord login completed and process is ready")
    return proc_bun

async def send_streambot_command(command: dict):
    global proc_bun
    proc = await start_streambot_process()
    if proc.stdin is None:
        raise RuntimeError("streambot stdin is unavailable")
    payload = (json.dumps(command, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    print(f"DEBUG streambot payload: {payload.decode('utf-8', errors='replace').strip()}")
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

async def leave_current_stream():
    global active_stream_session, proc_bun
    if proc_bun is not None and proc_bun.returncode is None and proc_bun.stdin:
        session_id = active_stream_session or str(uuid.uuid4())
        await send_streambot_command({"cmd": "leave", "session_id": session_id})
    active_stream_session = None

async def fetch_epg(max_retries=4, retry_delay=5):
    """Fetch and populate the global `epg_data` list with (title, channel_id) tuples."""
    global epg_url, epg_data

    for source_index, source_url in enumerate(epg_urls):
        for attempt in range(1, max_retries + 1):
            try:
                resp = await asyncio.to_thread(requests.get, source_url, headers=headers, timeout=30)
            except Exception as error:
                if attempt == max_retries:
                    print(f"EPG source {source_index + 1} failed: {type(error).__name__}")
                    break
                await asyncio.sleep(retry_delay)
                continue

            if resp.status_code != 200:
                if resp.status_code in (400, 401, 403, 404, 410):
                    print(f"EPG source {source_index + 1} rejected the request with status {resp.status_code}; trying fallback")
                    break
                if attempt == max_retries:
                    print(f"EPG source {source_index + 1} failed with status {resp.status_code}")
                    break
                await asyncio.sleep(retry_delay)
                continue

            try:
                root = ET.fromstring(resp.content)
                if root.tag.rsplit("}", 1)[-1].lower() != "tv":
                    raise ValueError("document is not XMLTV")
            except Exception as error:
                print(f"EPG source {source_index + 1} returned invalid XMLTV: {type(error).__name__}")
                break

            now = datetime.utcnow()
            matched_programmes = []
            for program in root.findall('.//programme'):
                title_element = program.find('title')
                if title_element is None or not title_element.text:
                    continue
                if parse_epg_time(program.get('start')) <= now <= parse_epg_time(program.get('stop')):
                    channel_id = program.get('channel')
                    if channel_id:
                        matched_programmes.append((title_element.text.strip(), channel_id))

            if matched_programmes:
                epg_data[:] = matched_programmes
                epg_url = source_url
                print(f"EPG loaded from source {source_index + 1}: {len(epg_data)} current programmes")
                return
            print(f"EPG source {source_index + 1} had no current programmes; trying fallback")
            break

    print("No usable XMLTV source found; channel-name search remains available")

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
    global stream_url, m3u_data, m3u_fetched_at
    global params
    global headers
    if m3u_data and time.monotonic() - m3u_fetched_at < M3U_CACHE_SECONDS:
        return m3u_data

    try:
        resp = await asyncio.to_thread(requests.post, stream_url, data=params, headers=headers, timeout=10)
    except Exception as e:
        print(f"Error fetching M3U: {e}")
        return []

    if resp.status_code == 200:
        try:
            records = resp.json()
            if isinstance(records, list):
                m3u_data = records
                m3u_fetched_at = time.monotonic()
                return m3u_data
        except Exception:
            pass
        return m3u_data
    else:
        print(f"Error fetching M3U: {resp.status_code}")
        return m3u_data

def get_m3u_for_autocomplete():
    global m3u_refresh_task
    if time.monotonic() - m3u_fetched_at >= M3U_CACHE_SECONDS:
        if m3u_refresh_task is None or m3u_refresh_task.done():
            m3u_refresh_task = asyncio.create_task(fetch_m3u())
    return m3u_data

def build_stream_url(record):
    stream_id = record.get("stream_id")
    stream_type = record.get("stream_type") or "live"
    extension = record.get("container_extension") or "m3u8"
    if not stream_id:
        return None
    return f"{url}/{stream_type}/{username}/{password}/{stream_id}.{extension}"

def find_catalog_channel(query, channels):
    query = (query or "").strip()
    if query.startswith("stream:"):
        query = query.partition(":")[2]

    by_id = next((record for record in channels if str(record.get("stream_id")) == query), None)
    if by_id is not None:
        return by_id

    matches = rank_catalog_channels(
        query,
        (record for record in channels if record.get("name") and record.get("stream_id")),
        limit=1,
        minimum_score=0.62,
    )
    return matches[0][1] if matches else None

def find_program_stream(query, channels):
    epg_matches = rank_search_matches(
        query,
        epg_data,
        lambda programme: programme[0],
        limit=100,
        minimum_score=0.58,
    )
    channels_by_epg_id = {}
    for record in channels:
        epg_id = str(record.get("epg_channel_id") or "").strip()
        if epg_id:
            channels_by_epg_id.setdefault(epg_id, []).append(record)

    for _, (title, epg_id) in epg_matches:
        matching_channels = channels_by_epg_id.get(str(epg_id), [])
        if matching_channels:
            return title, matching_channels[0]
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
    await interaction.response.defer()

    m3u_content = await fetch_m3u()
    selected_program = None
    if searchterm.startswith("stream:"):
        selected_channel = find_catalog_channel(searchterm, m3u_content)
        if selected_channel:
            selected_program = (selected_channel.get("name") or searchterm, selected_channel)
    else:
        selected_program = find_program_stream(searchterm, m3u_content)
        if selected_program is None:
            selected_channel = find_catalog_channel(searchterm, m3u_content)
            if selected_channel:
                selected_program = (selected_channel.get("name") or searchterm, selected_channel)

    if selected_program is None:
        await interaction.followup.send("No matching live programme or IPTV channel found. Try `/watch_channel` to search channel names.")
        return

    matched_title, matched_channel = selected_program
    channel_url = build_stream_url(matched_channel)
    if not channel_url:
        await interaction.followup.send("The matching IPTV entry has no stream URL.")
        return

    print(f"DEBUG watch match: query={searchterm!r} title={matched_title!r} channel={matched_channel.get('name', '')!r}")

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
    await interaction.followup.send(f"Streaming **{matched_title}** in the voice channel!")
    try:
        await send_streambot_command({
            "cmd": "play",
            "session_id": session_id,
            "video_url": channel_url,
            "channel_id": str(channel.id),
            "guild_id": str(guild),
            "title": matched_title,
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

@tree.command(name="leave", description="leave the current voice channel and stop the stream")
async def leave(interaction: discord.Interaction):
    await interaction.response.send_message("Leaving the current voice channel and stopping the stream.")
    global proc_bun, active_stream_session
    try:
        await leave_current_stream()
    except Exception as e:
        print(f"Error issuing leave to streambot: {e}")
    finally:
        active_stream_session = None

@tree.command(name="help", description="Show SportsHero commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="SportsHero Commands",
        description="Join a voice channel before starting a stream.",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="/watch <search>", value="Find a live programme or stream by name.", inline=False)
    embed.add_field(name="/watch_channel <search>", value="Find an IPTV channel by name or region.", inline=False)
    embed.add_field(name="/search and /search_channel", value="Aliases for `/watch` and `/watch_channel`.", inline=False)
    embed.add_field(name="/stop", value="Stop the current stream.", inline=False)
    embed.add_field(name="/leave", value="Stop the stream and leave voice.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="watch_channel", description="Search IPTV channels by name or region")
async def watch_channel(interaction: discord.Interaction, searchterm: str):
    print(f"DEBUG watch_channel command: user={interaction.user.id} guild={interaction.guild_id} searchterm={searchterm}")
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
    await interaction.response.defer()

    m3u_content = await fetch_m3u()
    matched_channel = find_catalog_channel(searchterm, m3u_content)
    channel_url = build_stream_url(matched_channel) if matched_channel else None
    if not channel_url:
        await interaction.followup.send("No matching IPTV channel found. Try a network name and city, such as `CBS Sacramento`.")
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
    channel_name = matched_channel.get("name") or searchterm
    await interaction.followup.send(f"Streaming **{channel_name}** in the voice channel!")
    try:
        await send_streambot_command({
            "cmd": "play",
            "session_id": session_id,
            "video_url": channel_url,
            "channel_id": str(channel.id),
            "guild_id": str(guild),
            "title": channel_name,
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

@tree.command(name="search", description="Search live programmes and streams")
async def search(interaction: discord.Interaction, searchterm: str):
    await watch.callback(interaction, searchterm)

@search.autocomplete("searchterm")
async def search_autocomplete(interaction: discord.Interaction, current: str):
    return await watch_autocomplete(interaction, current)

@tree.command(name="search_channel", description="Search IPTV channels by name or region")
async def search_channel(interaction: discord.Interaction, searchterm: str):
    await watch_channel.callback(interaction, searchterm)

@search_channel.autocomplete("searchterm")
async def search_channel_autocomplete(interaction: discord.Interaction, current: str):
    return await watch_channel_autocomplete(interaction, current)

@watch.autocomplete("searchterm")
async def watch_autocomplete(interaction: discord.Interaction, current: str):
    current = (current or "").strip()
    if not current:
        return []
    choices = []
    seen_values = set()

    epg_matches = await asyncio.to_thread(
        rank_search_matches,
        current,
        epg_data,
        lambda programme: programme[0],
        limit=25,
        minimum_score=0.42,
    )
    for _, (title, _) in epg_matches:
        if title not in seen_values:
            choices.append(app_commands.Choice(name=title[:100], value=title[:100]))
            seen_values.add(title)
        if len(choices) >= 25:
            return choices

    channels = get_m3u_for_autocomplete()
    channel_matches = await asyncio.to_thread(
        rank_catalog_channels,
        current,
        (item for item in channels if item.get("name") and item.get("stream_id")),
        limit=25,
        minimum_score=0.48,
        fast_autocomplete=True,
    )
    for _, record in channel_matches:
        stream_id = str(record.get("stream_id"))
        value = f"stream:{stream_id}"
        if value in seen_values:
            continue
        choices.append(app_commands.Choice(name=f"Channel: {record['name']}"[:100], value=value))
        seen_values.add(value)
        if len(choices) >= 25:
            break
    return choices

@watch_channel.autocomplete("searchterm")
async def watch_channel_autocomplete(interaction: discord.Interaction, current: str):
    current = (current or "").strip()
    if not current:
        return []
    channels = get_m3u_for_autocomplete()
    matches = await asyncio.to_thread(
        rank_catalog_channels,
        current,
        (item for item in channels if item.get("name") and item.get("stream_id")),
        limit=25,
        minimum_score=0.42,
        fast_autocomplete=True,
    )
    choices = []
    for _, record in matches:
        choices.append(app_commands.Choice(name=str(record["name"])[:100], value=str(record["stream_id"])))
    return choices

@bot.event
async def on_ready():
    await asyncio.gather(fetch_epg(), fetch_m3u())
    await tree.sync()
    print(f'Logged in as {bot.user}')

bot.run(TOKEN)
