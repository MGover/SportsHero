import { Client, CustomStatus, ActivityOptions } from "discord.js-selfbot-v13";
import { Streamer, Utils, prepareStream, playStream } from "@dank074/discord-video-stream";
import config from "./config.js";
import fs from 'fs';
import path from 'path';
import logger from './utils/logger.js';

// Create a new instance of Streamer
const streamer = new Streamer(new Client());

// Declare a controller to abort the stream
let controller: AbortController;

const streamOpts = {
    width: config.width,
    height: config.height,
    frameRate: config.fps,
    bitrateVideo: config.bitrateKbps,
    bitrateVideoMax: config.maxBitrateKbps,
    videoCodec: Utils.normalizeVideoCodec(config.videoCodec),
    hardwareAcceleratedDecoding: config.hardwareAcceleratedDecoding,
    minimizeLatency: false,
    h26xPreset: config.h26xPreset
};

// Create previewCache parent dir if it doesn't exist
if (!fs.existsSync(path.dirname(config.previewCacheDir))) {
    fs.mkdirSync(path.dirname(config.previewCacheDir), { recursive: true });
}

// Create the previewCache dir if it doesn't exist
if (!fs.existsSync(config.previewCacheDir)) {
    fs.mkdirSync(config.previewCacheDir);
}

// Ready event
streamer.client.on("ready", async () => {
    if (streamer.client.user) {
        streamer.client.user?.setActivity(status_idle() as ActivityOptions);
    }
});

// Stream status object
const streamStatus = {
    joined: false,
    joinsucc: false,
    playing: false,
    manualStop: false,
    channelInfo: {
        guildId: "",
        channelId: "",
    }
}

// Function to stop video
async function stopVideo() {
    if (!streamStatus.joined) {
        logger.info("already stopped")
        return;
    }
    try {
        streamStatus.manualStop = true;
        
        controller?.abort();

        streamer.stopStream();
        streamer.leaveVoice();
        streamer.client.user?.setActivity(status_idle() as ActivityOptions);

        streamStatus.joined = false;
        streamStatus.joinsucc = false;
        streamStatus.playing = false;
        streamStatus.channelInfo = {
            guildId: "",
            channelId: "",
        };

    } catch (error) {
        logger.info("Error:" + error)
    }
}

// Function to play video
async function playVideo(video: string, title?: string, channelId?: string, guildId?: string) {
    logger.info("Starting video: " + video);
    logger.info("GuildID: " + guildId + "\nChannelId: " + channelId)
    // Reset manual stop flag
    streamStatus.manualStop = false;

    // Join voice channel
    await streamer.joinVoice(guildId, channelId)
    streamStatus.joined = true;
    streamStatus.playing = true;
    streamStatus.channelInfo = {
        guildId: guildId,
        channelId: channelId
    }

    try {
        if (title) {
            streamer.client.user?.setActivity(status_watch(title) as ActivityOptions);
        }

        // Abort any existing controller
        controller?.abort();
        controller = new AbortController();

        const { command, output } = prepareStream(video, streamOpts, controller.signal);

        command.on("error", (err) => {
            logger.info("An error happened with ffmpeg" + err);
        });

        await playStream(output, streamer, undefined, controller.signal)
            .catch(() => controller.abort());

        logger.info("Finished playing video");
    } catch (error) {
        logger.info("Error occurred while playing video:" + error);
        controller?.abort();
    } finally {
        await cleanupStreamStatus();
    }
}

// Function to cleanup stream status - updated
async function cleanupStreamStatus() {
    if (streamStatus.manualStop) {
        return;
    }

    try {
        controller?.abort();
        streamer.stopStream();
        streamer.leaveVoice();

        streamer.client.user?.setActivity(status_idle() as ActivityOptions);

        // Reset all status flags
        streamStatus.joined = false;
        streamStatus.joinsucc = false;
        streamStatus.playing = false;
        streamStatus.manualStop = false;
        streamStatus.channelInfo = {
            guildId: "",
            channelId: ""
        };
    } catch (error) {
        logger.info("Error during cleanup:" + error);
    }
}

const status_idle = () => {
    return new CustomStatus(new Client())
        .setEmoji('📽')
        .setState('Watching Something!')
}

const status_watch = (name: string) => {
    return new CustomStatus(new Client())
        .setEmoji('📽')
        .setState(`Playing ${name}...`)
}

// Handle uncaught exceptions
process.on('uncaughtException', (error) => {
    if (!(error instanceof Error && error.message.includes('SIGTERM'))) {
        logger.info('Uncaught Exception:' + error);
        return
    }
});

// Login to Discord
streamer.client.login(config.token);

// start.ts
const readline = require('readline');


const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

logger.info("Type something! (type 'exit' to quit)");

// handle input from console
rl.on('line', (input: string) => {
    logger.info(`Input recieved: ${input}`);
    const firstFour = input.substring(0, 4);
    switch (firstFour) {
      case 'http':
        const [link, channelId, guildId, ...rest] = input.trim().split(" ");
        const title = rest.join(" ");
        logger.info(`Link: ${link}\nTitle: ${title}\nChannelID: ${channelId}\nGuildID: ${guildId}`);
        logger.info("Attempting to play video");
        playVideo(link, title, channelId, guildId);
        break;
      case 'stop':
        logger.info(`Leaving and stopping`);
        stopVideo()
        break;
      case 'exit':
        logger.info("👋 Goodbye!");
        rl.close();
        break;
      default:
        logger.info(`🤔 You said: ${input}`);
    }
  });

