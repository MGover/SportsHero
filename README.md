# SportsHero
This is a discord bot that combines the abilities of an official discord bot and a ['self-bot'](https://github.com/AstraaDev/Discord-SelfBot) to create an ultimate IPTV streaming experience all contained within Discord. *You will need to have your own IPTV streaming subscription and M3U link*

## Features
- Stream Tevelvision Programmes live in Discord
- Search and Browse currently live programmes using discord slash commands

## Requirements
- [Bun](https://bun.sh/)
- [FFMpeg](https://www.ffmpeg.org/)
- [Python](https://www.python.org/)
- [A Discord Account](https://discord.com/)
- [A Discord Bot](https://discord.com/developers/applications)

## Python Dependences
Open up your OS Terminal and PIP Install the following libraries:
```
pip install discord
pip install requests
pip install dotenv
```

(TODO: Add these into a python environment)

## Installation
1. Clone this repo. Run the following in your OS Terminal:
   
   ```
   git clone https://github.com/MGover/SportsHero.git
   ```
3. Use Bun to install Node dependences:
   
   ```
   cd ./streambot
   ```
   
   ```
   bun install
   ```

5. Configure Environment Variables
   - There are 2 .env.example files. One in the project root and another under /streambot/ directory
   - See below on how to configure these values
  
## Usage
Run the following in the project root:

```
python sport-hero.py
```

If you get "Logged in as <BotNameHere> then you got everything right so far

## Commands
|Command|Description|
|---------|---------|
|/watch| An interactive slash command that will show you currently active programmes matching with what you type|
|/stop| Tells the bot to stop streaming|

*Special Notes About Commands*: 
- These commands are slow. The bot may take up to a whole 30 seconds to start streaming, and even longer to stop. This is mostly due to how I implemented the Python portion of this project interfacing with the TypeScript portion.
- These commands fail sometimes. If the stream doesn't start, try again. Try /stop then try /watch. Or just keep trying /watch. This can depend on the rules of your OS
- If the bot replies with "Channel Stream Not Found", that's typically a miss on the Electronic Programme Guide (EPG). There's no perfect EPG's out there. I recommend using the one your service provider gives you before turning to public EPG sources

## Configuration
Reanme both .env.example files to .env

/./.env

```
  DISCORD_BOT_TOKEN = "xxxxxxxxxxxxxxxxxsecretxxxxxxxxxxx"
  M3U_URL = "http://example-iptv.com/get.php?username=example&password=example&type=m3u_plus&output=tsL"
  EPG_URL = "https://epgshare01.online/epgshare01/"
```

DISCORD_BOT_TOKEN is the token from your OFFICIAL discord bot. This bot needs [application.commands permission](https://discord.com/developers/docs/topics/permissions) for the slash commands to work. 

M3U_URL is the URL provided to you by your IPTV subscription service. It NEEDS to be formatted with username and password in the link like the example above

EPG_URL is the link to your Electronic Programme Guide. This is how the bot knows what is currently playing on TV. There are publicly available ones but no EPG is perfect. Try to use the one your IPTV service provides you. 

TODO: Allow users to use a local epg.xml 

/./streambot/.env

```
# Selfbot options
TOKEN = "" # Your Discord self-bot token
PREFIX = "$" # The prefix used to trigger your self-bot commands
GUILD_ID = "" # The ID of the Discord server your self-bot will be running on
COMMAND_CHANNEL_ID = "" # The ID of the Discord channel where your self-bot will respond to commands
VIDEO_CHANNEL_ID = "" # The ID of the Discord voice/video channel where your self-bot will stream videos

# General options
VIDEOS_DIR = "./videos" # The local path where you store video files
PREVIEW_CACHE_DIR = "./tmp/preview-cache" # The local path where your self-bot will cache video preview thumbnails

# Stream options
STREAM_RESPECT_VIDEO_PARAMS = "false"  # This option is used to respect video parameters such as width, height, fps, bitrate, and max bitrate.
STREAM_WIDTH = "1280" # The width of the video stream in pixels
STREAM_HEIGHT = "720" # The height of the video stream in pixels
STREAM_FPS = "30" # The frames per second (FPS) of the video stream
STREAM_BITRATE_KBPS = "2000" # The bitrate of the video stream in kilobits per second (Kbps)
STREAM_MAX_BITRATE_KBPS = "2500" # The maximum bitrate of the video stream in kilobits per second (Kbps)
STREAM_HARDWARE_ACCELERATION = "false" # Whether to use hardware acceleration for video decoding, set to "true" to enable, "false" to disable
STREAM_VIDEO_CODEC = "H264" # The video codec to use for the stream, can be "H264" or "H265" or "VP8"

# STREAM_H26X_PRESET: Determines the encoding preset for H26x video streams. 
# If the STREAM_H26X_PRESET environment variable is set, it parses the value 
# using the parsePreset function. If not set, it defaults to 'ultrafast' for 
# optimal encoding speed. This preset is only applicable when the codec is 
# H26x; otherwise, it should be disabled or ignored.
# Available presets: "ultrafast", "superfast", "veryfast", "faster", 
# "fast", "medium", "slow", "slower", "veryslow".
STREAM_H26X_PRESET = "ultrafast"

# Videos server options
SERVER_ENABLED = "false" # Whether to enable the built-in video server
SERVER_USERNAME = "admin" # The username for the video server's admin interface
SERVER_PASSWORD = "admin" # The password for the video server's admin interface
SERVER_PORT = "8080" # The port number the video server will listen on
```

The only variable NEEDED is the your Discord Account's self-bot token. See [this wiki on how to find your discord account token](https://github.com/ysdragon/StreamBot/wiki/Get-Discord-user-token)

All other variables are not needed. Only the stream options are used. Everything else is ignored. 

TODO: Reduce size of streambot .env

## Special Notes:
- If it isn't obvious by now, this bot borrows heavily from [StreamBot](https://github.com/ysdragon/StreamBot) . I merely added IPTV and Discord Bot function. If you are developer on the StreamBot project and reading this, please add these features to your project. I'd do it myself but I don't feel like learning TS/JS/Node. Feel free to borrow from my Python code or make a request for my assistance if needed
- This bot is never gonna be perfect. Please do not open requests for issues like "stream not found" or "I typed /watch and the bot only sometimes joins". If you can get the bot to sometimes join and stream stuff from your IPTV service, then the bot is working as expected. It is far more difficult than what is worth my time to make this bot more robust. That being said:
- Pull Requests are encouraged. So are Issues. If you see improvements that can be made, point it out.
  
