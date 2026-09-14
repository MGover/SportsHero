import { Client, CustomStatus, ActivityOptions } from "discord.js-selfbot-v13";
import { Streamer, Utils, prepareStream, playStream } from "@dank074/discord-video-stream";
import config from "./config.js";
import fs from 'fs';
import path from 'path';
import readline from 'node:readline';
import logger from './utils/logger.js';

const client = new Client();
const streamer = new Streamer(client);
let controller: AbortController | undefined;

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

const streamStatus = {
    joined: false,
    joinsucc: false,
    playing: false,
    manualStop: false,
    channelInfo: {
        guildId: config.guildId || '',
        channelId: config.videoChannelId || '',
    }
};

if (!fs.existsSync(path.dirname(config.previewCacheDir))) {
    fs.mkdirSync(path.dirname(config.previewCacheDir), { recursive: true });
}

if (!fs.existsSync(config.previewCacheDir)) {
    fs.mkdirSync(config.previewCacheDir, { recursive: true });
}

const status_idle = (): ActivityOptions => new CustomStatus(new Client())
    .setEmoji('📽')
    .setState('Watching Something!') as unknown as ActivityOptions;

const status_watch = (name: string): ActivityOptions => new CustomStatus(new Client())
    .setEmoji('📽')
    .setState(`Playing ${name}...`) as unknown as ActivityOptions;

async function cleanupStreamStatus() {
    if (streamStatus.manualStop) {
        return;
    }

    try {
        controller?.abort();
        streamer.stopStream();
        streamer.leaveVoice();
        client.user?.setActivity(status_idle() as ActivityOptions);

        streamStatus.joined = false;
        streamStatus.joinsucc = false;
        streamStatus.playing = false;
        streamStatus.manualStop = false;
        streamStatus.channelInfo = { guildId: '', channelId: '' };
    } catch (error) {
        logger.info('Error during cleanup: ' + error);
    }
}

async function stopVideo() {
    if (!streamStatus.joined) {
        logger.info('already stopped');
        return;
    }

    try {
        streamStatus.manualStop = true;
        controller?.abort();
        streamer.stopStream();
        streamer.leaveVoice();
        client.user?.setActivity(status_idle() as ActivityOptions);

        streamStatus.joined = false;
        streamStatus.joinsucc = false;
        streamStatus.playing = false;
        streamStatus.channelInfo = { guildId: '', channelId: '' };
    } catch (error) {
        logger.info('Error stopping video: ' + error);
    }
}

async function playVideo(video: string, title?: string, channelId?: string, guildId?: string) {
    logger.info('Starting video: ' + video);
    logger.info(`Selfbot join attempt: guild=${guildId} channel=${channelId} title=${title ?? ''}`);

    streamStatus.manualStop = false;

    try {
        logger.info('Calling streamer.joinVoice...');
        await streamer.joinVoice(guildId, channelId);
        logger.info('joinVoice resolved successfully');

        streamStatus.joined = true;
        streamStatus.playing = true;
        streamStatus.channelInfo = { guildId: guildId ?? '', channelId: channelId ?? '' };

        if (title) {
            client.user?.setActivity(status_watch(title) as ActivityOptions);
        }

        controller?.abort();
        controller = new AbortController();

        const { command, output } = prepareStream(video, streamOpts, controller.signal);
        command.on('error', (err) => {
            logger.info('An error happened with ffmpeg: ' + err);
        });

        logger.info('Starting playStream...');
        await playStream(output, streamer, undefined, controller.signal).catch((err) => {
            logger.info('playStream catch: ' + err);
            controller?.abort();
        });

        logger.info('Finished playing video');
    } catch (error) {
        logger.info('Error occurred while playing video: ' + error);
        logger.info(`Join/play debug: guild=${guildId} channel=${channelId} video=${video}`);
        controller?.abort();
    } finally {
        await cleanupStreamStatus();
    }
}

process.on('uncaughtException', (error) => {
    if (!(error instanceof Error && error.message.includes('SIGTERM'))) {
        logger.info('Uncaught Exception: ' + error);
        return;
    }
});

if (!config.token) {
    logger.info('Selfbot token missing. Set streambot/.env TOKEN=... before starting the streambot.');
    process.exit(1);
}

logger.info(`Selfbot token loaded: ${config.token.slice(0, 4)}...${config.token.slice(-4)} (length=${config.token.length})`);

client.on('ready', () => {
    logger.info(`Selfbot ready: ${client.user?.tag ?? 'unknown user'}`);
    client.user?.setActivity(status_idle() as ActivityOptions);
});

client.on('error', (error) => {
    logger.info('Discord client error: ' + error);
});

client.on('disconnect', (event) => {
    logger.info('Discord client disconnected: ' + JSON.stringify(event));
});

client.login(config.token).catch((error) => {
    logger.info('Selfbot login failed: ' + error);
    process.exit(1);
});

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

logger.info('Type something! (type \'exit\' to quit)');

rl.on('line', (input: string) => {
    logger.info(`Input recieved: ${input}`);
    const prefix = input.substring(0, 4);

    switch (prefix) {
        case 'http': {
            const [link, channelId, guildId, ...rest] = input.trim().split(' ');
            const title = rest.join(' ');
            logger.info(`Link: ${link}\nTitle: ${title}\nChannelID: ${channelId}\nGuildID: ${guildId}`);
            logger.info('Attempting to play video');
            playVideo(link, title, channelId, guildId).catch((err) => {
                logger.info(`playVideo promise rejected: ${err}`);
            });
            break;
        }
        case 'stop': {
            logger.info('Leaving and stopping');
            stopVideo().catch((err) => {
                logger.info(`stopVideo promise rejected: ${err}`);
            });
            break;
        }
        case 'exit': {
            logger.info('👋 Goodbye!');
            rl.close();
            break;
        }
        default:
            logger.info(`🤔 You said: ${input}`);
    }
});

