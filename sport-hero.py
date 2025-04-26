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
pattern = r'(http[s]?://[^/]+)/get\.php\?username=([^&]*)&password=([^&]*)&type=(m3u_plus|m3u|&output=m3u8)'
match = re.match(pattern, M3U_URL)
url = match.group(1)
username = match.group(2)
password = match.group(3)
stream_url = url+"/player_api.php"
epg_url = f"{url}/xmltv.php?username={username}&password={password}"
params={'username':username,'password':password,'action':"get_live_streams",'catergory_id':''}
CUSTOM_USER_AGENT = (
    "Connection: Keep-Alive User-Agent: okhttp/5.0.0-alpha.2 "
    "Accept-Encoding: gzip, deflate"
)
headers = {'User-Agent': CUSTOM_USER_AGENT}
proc_bun = None
epg_data = []

async def fetch_epg():
    global epg_url
    global headers
    resp = requests.post(url=epg_url, headers=headers, timeout=10)
    xml_content = []
    if resp.status_code == 200:
        xml_content = resp.content
    else:
        print(f"Error fetching M3U: {resp.status_code}")
        return ""
    root = ET.fromstring(xml_content)

    now = datetime.utcnow()
    for prog in root.findall('.//programme'):
        if ((prog.find('title') is None) or (prog.find('title').text is None) or (prog is None)):
            continue
        title = prog.find('title').text.strip()
        channel = prog.get('channel')
        start_time = parse_epg_time(prog.get('start'))
        stop_time = parse_epg_time(prog.get('stop'))
        if start_time <= now <= stop_time:
            curr_tup = (title, channel)
            epg_data.append(curr_tup)

def parse_epg_time(epg_time):
    """Parses EPG time format 'YYYYMMDDHHMMSS ±TZ' into a datetime object."""
    time_str, tz_offset = epg_time[:14], epg_time[15:]  # Split timestamp and timezone
    dt = datetime.strptime(time_str, "%Y%m%d%H%M%S")  # Parse time

    # Convert timezone offset to integer and apply it
    tz_hours = int(tz_offset[:3])  # Get the hours part of ±TZ
    dt = dt - timedelta(hours=tz_hours)  # Adjust for timezone offset

    return dt

async def fetch_m3u():
    global stream_url
    global params
    global headers
    resp = requests.post(url=stream_url, data=params, headers=headers, timeout=10)
    if resp.status_code == 200:
        return resp.json()
    else:
        print(f"Error fetching M3U: {resp.status_code}")
        return ""

def find_channel(query):
    for title, channel_id in epg_data:
        if query.lower() in title.lower():
            return channel_id
    return None

@tree.command(name="watch", description="Watch a live TV channel")
async def watch(interaction: discord.Interaction, searchterm: str):
    if not interaction.user.voice:
        await interaction.response.send_message("You need to be in a voice channel to use this command.", ephemeral=True)
        return

    global url
    global username
    global password
    container_extension = "m3u8"
    await interaction.response.defer()
    
    channel_id = find_channel(searchterm)
    if not channel_id:
        await interaction.followup.send("No matching channel found.")
        return
    
    m3u_content = await fetch_m3u()
    channel_url = None

    for line in m3u_content:
        if line["epg_channel_id"] == channel_id:
            container_extension = line.get("container_extension", "m3u8")
            stream_id = line["stream_id"]
            stream_type = line["stream_type"]
            channel_url = f"{url}/{stream_type}/{username}/{password}/{stream_id}.{container_extension}"
            break
    
    # channel_url = f"{url}/{'live'}/{username}/{password}/{368529}.{container_extension}"
    print(channel_url)
    if not channel_url:
        await interaction.followup.send("Channel stream not found.")
        return
    
    guild = interaction.guild_id
    channel = interaction.user.voice.channel
    global proc_bun
    if proc_bun is not None:
        print("killing old bun")
        if proc_bun.returncode is None:
            proc_bun.communicate(b"stop\n")
            time.sleep(10)
            proc_bun.terminate()
        else:
            print("bun proc already died somehow")
    proc_bun = await asyncio.create_subprocess_exec(
            "bun", "run", "start",
            cwd=r"./streambot",
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
            )

    time.sleep(3)
    await interaction.followup.send(f"Streaming **{searchterm}** in the voice channel!")
    await proc_bun.communicate(channel_url.encode('utf-8')+b" "+str(channel.id).encode('utf-8')+b" "+str(guild).encode('utf-8')+b" "+searchterm.encode('utf-8')+b"\n")

@tree.command(name="stop", description="stop the current stream")
async def stop(interaction: discord.Interaction):
    await interaction.response.send_message("gonna try to kill this guy")
    global proc_bun
    if proc_bun is None:
        print("bun already killed")
    else:
        if proc_bun.returncode is None:
            proc_bun.communicate(b"stop\b")
            time.sleep(10)
            proc_bun.terminate()
        else:
            print("Bun process died somehow")
    proc_bun = None

@tree.command(name="watch_channel", description="Choose from channels")
async def watch_channel(interaction: discord.Interaction, channel_id: str):
    if not interaction.user.voice:
        await interaction.response.send_message("You need to be in a voice channel to use this command.", ephemeral=True)
        return

    global url
    global username
    global password
    container_extension = "m3u8"
    await interaction.response.defer()

    m3u_content = await fetch_m3u()
    channel_url = None

    for line in m3u_content:
        if line["epg_channel_id"] == channel_id:
            container_extension = line.get("container_extension", "m3u8")
            stream_id = line["stream_id"]
            stream_type = line["stream_type"]
            channel_url = f"{url}/{stream_type}/{username}/{password}/{stream_id}.{container_extension}"
            break
    
    # channel_url = f"{url}/{'live'}/{username}/{password}/{368529}.{container_extension}"
    print(channel_url)
    if not channel_url:
        await interaction.followup.send("Channel stream not found.")
        return
    
    guild = interaction.guild_id
    channel = interaction.user.voice.channel
    global proc_bun
    if proc_bun is not None:
        print("killing old bun")
        if proc_bun.returncode is None:
            proc_bun.communicate(b"stop\n")
            time.sleep(10)
            proc_bun.terminate()
        else:
            print("bun proc already died somehow")
    proc_bun = await asyncio.create_subprocess_exec(
            "bun", "run", "start",
            cwd=r"./streambot",
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
            )

    time.sleep(3)
    await interaction.followup.send(f"Streaming **{channel_id}** in the voice channel!")
    await proc_bun.communicate(channel_url.encode('utf-8')+b" "+str(channel.id).encode('utf-8')+b" "+str(guild).encode('utf-8')+b" "+channel_id.encode('utf-8')+b"\n")

@watch.autocomplete("searchterm")
async def search_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=title, value=title) for title, channel in epg_data if current.lower() in title.lower()][:25]

@watch_channel.autocomplete("channel_id")
async def search_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=channel, value=channel) for title, channel in epg_data if current.lower() in channel.lower()][:25]

@bot.event
async def on_ready():
    await fetch_epg()
    await tree.sync()
    print(f'Logged in as {bot.user}')

bot.run(TOKEN)
