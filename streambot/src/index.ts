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
    currentSessionId: '',
    channelInfo: {
        guildId: config.guildId || '',
        channelId: config.videoChannelId || '',
    }
};

interface StreamCommand {
    cmd?: string;
    session_id?: string;
    video_url?: string;
    channel_id?: string;
    guild_id?: string;
    title?: string;
}

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
    try {
        controller?.abort();
        streamer.stopStream();
        streamer.leaveVoice();
        client.user?.setActivity(status_idle() as ActivityOptions);

        streamStatus.joined = false;
        streamStatus.joinsucc = false;
        streamStatus.playing = false;
        streamStatus.manualStop = false;
        streamStatus.currentSessionId = '';
        streamStatus.channelInfo = { guildId: '', channelId: '' };
    } catch (error) {
        logger.info('Error during cleanup: ' + error);
    }
}

async function stopVideo(sessionId?: string) {
    if (sessionId && streamStatus.currentSessionId && sessionId !== streamStatus.currentSessionId) {
        logger.info(`Ignoring stop for stale session ${sessionId}; active session is ${streamStatus.currentSessionId}`);
        return;
    }

    if (!streamStatus.joined && !streamStatus.playing) {
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
        streamStatus.currentSessionId = '';
        streamStatus.channelInfo = { guildId: '', channelId: '' };
    } catch (error) {
        logger.info('Error stopping video: ' + error);
    }
}

async function playVideo(sessionId: string, video: string, title?: string, channelId?: string, guildId?: string) {
    if (streamStatus.currentSessionId && streamStatus.currentSessionId !== sessionId) {
        logger.info(`Replacing stale session ${streamStatus.currentSessionId} with ${sessionId}`);
        await stopVideo(streamStatus.currentSessionId);
    }

    if (streamStatus.currentSessionId === sessionId && streamStatus.playing) {
        logger.info(`Session ${sessionId} already playing; ignoring duplicate play command`);
        return;
    }

    logger.info('Starting video: ' + video);
    logger.info(`Selfbot join attempt: guild=${guildId} channel=${channelId} title=${title ?? ''} session=${sessionId}`);

    streamStatus.manualStop = false;
    streamStatus.currentSessionId = sessionId;

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
        command.on('start', (commandLine) => {
            logger.info('FFmpeg started: ' + commandLine);
        });
        command.on('stderr', (data) => {
            const text = data.toString().trim();
            if (text) {
                logger.info('FFmpeg stderr: ' + text);
            }
        });
        command.on('error', (err) => {
            logger.info('An error happened with ffmpeg: ' + err);
        });
        command.on('end', () => {
            logger.info('FFmpeg ended normally for session ' + sessionId);
        });

        logger.info('Starting playStream...');
        try {
            await playStream(output, streamer, undefined, controller.signal);
            logger.info(`playStream resolved without raising an exception for session ${sessionId}`);
        } catch (err) {
            logger.info('playStream catch: ' + err);
            controller?.abort();
            throw err;
        }

        if (!streamStatus.manualStop && streamStatus.currentSessionId === sessionId) {
            logger.info(`playStream ended without a manual stop for session ${sessionId}; cleaning up`);
            await cleanupStreamStatus();
        }
    } catch (error) {
        logger.info('Error occurred while playing video: ' + error);
        logger.info(`Join/play debug: guild=${guildId} channel=${channelId} video=${video} session=${sessionId}`);
        controller?.abort();
        if (!streamStatus.manualStop && streamStatus.currentSessionId === sessionId) {
            await cleanupStreamStatus();
        }
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

logger.info('Streambot ready for JSON session commands.');

rl.on('line', async (input: string) => {
    const trimmed = input.trim();
    if (!trimmed) {
        return;
    }

    logger.info(`Input received: ${trimmed}`);

    try {
        const command = JSON.parse(trimmed) as StreamCommand;
        const sessionId = command.session_id || '';
        const cmd = command.cmd || '';

        if (cmd === 'play') {
            const videoUrl = command.video_url || '';
            const channelId = command.channel_id || '';
            const guildId = command.guild_id || '';
            const title = command.title || '';

            if (!videoUrl || !channelId || !guildId) {
                logger.info(`Rejected invalid play command: ${trimmed}`);
                return;
            }

            logger.info(`Dispatching play for session=${sessionId} guild=${guildId} channel=${channelId}`);
            await playVideo(sessionId, videoUrl, title, channelId, guildId).catch((err) => {
                logger.info(`playVideo promise rejected: ${err}`);
            });
            return;
        }

        if (cmd === 'stop' || cmd === 'leave') {
            logger.info(`${cmd === 'leave' ? 'Leaving' : 'Stopping'} stream for session=${sessionId || '<none>'}`);
            await stopVideo(sessionId).catch((err) => {
                logger.info(`stopVideo promise rejected: ${err}`);
            });
            return;
        }

        if (cmd === 'exit') {
            logger.info('👋 Goodbye!');
            await stopVideo();
            rl.close();
            return;
        }

        logger.info(`Unrecognized command: ${cmd}`);
    } catch (error) {
        const prefix = trimmed.substring(0, 4);
        if (prefix === 'http') {
            const [link, channelId, guildId, ...rest] = trimmed.split(' ');
            const title = rest.join(' ');
            logger.info(`Legacy URL command received: ${link} channel=${channelId} guild=${guildId}`);
            await playVideo(`legacy-${Date.now()}`, link, title, channelId, guildId).catch((err) => {
                logger.info(`legacy playVideo promise rejected: ${err}`);
            });
            return;
        }

        if (trimmed === 'stop' || trimmed === 'leave') {
            logger.info(`Legacy ${trimmed} command received`);
            await stopVideo().catch((err) => {
                logger.info(`legacy stopVideo promise rejected: ${err}`);
            });
            return;
        }

        logger.info(`Could not parse command input: ${trimmed} | ${error}`);
    }
});

