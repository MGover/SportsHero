import { Client, CustomStatus, ActivityOptions } from "discord.js-selfbot-v13";
import { Encoders, Streamer, Utils, prepareStream, playStream } from "@dank074/discord-video-stream";
import config from "./config.js";
import fs from 'fs';
import path from 'path';
import readline from 'node:readline';
import logger from './utils/logger.js';

function redactUrls(text: string): string {
    return text.replace(/https?:\/\/[^\s"'<>]+/gi, '[URL redacted]');
}

const client = new Client();
const streamer = new Streamer(client);
const originalSendOpcode = streamer.sendOpcode.bind(streamer);
streamer.sendOpcode = ((code: number, data: unknown) => {
    if (code === 4 && data && typeof data === 'object') {
        const payload = data as Record<string, unknown>;
        const hasVoiceStatePayload = Object.prototype.hasOwnProperty.call(payload, 'guild_id') || Object.prototype.hasOwnProperty.call(payload, 'channel_id');
        if (hasVoiceStatePayload) {
            const isVideoPayload = payload.self_video === true || payload.self_video === 'true' || payload.self_stream === true || payload.self_stream === 'true';
            payload.self_video = payload.self_video === undefined ? true : payload.self_video;
            payload.self_stream = payload.self_stream === undefined ? isVideoPayload : payload.self_stream;
            payload.flags = isVideoPayload ? 2 : 0;
        }
    }
    return originalSendOpcode(code, data);
}) as typeof streamer.sendOpcode;

client.on('raw', (packet: any) => {
    if (!packet || typeof packet !== 'object' || !packet.t) {
        return;
    }
    if (packet.t === 'VOICE_STATE_UPDATE' || packet.t === 'VOICE_SERVER_UPDATE' || packet.t === 'STREAM_CREATE' || packet.t === 'STREAM_SERVER_UPDATE') {
        const eventData = { ...packet.d };
        for (const sensitiveField of ['token', 'stream_key']) {
            if (sensitiveField in eventData) {
                eventData[sensitiveField] = '[redacted]';
            }
        }
        logger.info(`Discord raw gateway: ${packet.t} ${JSON.stringify(eventData)}`);
    }
});

let controller: AbortController | undefined;

const streamOpts = {
    encoder: Encoders.software({
        x264: { preset: config.h26xPreset, tune: 'zerolatency' },
        x265: { preset: config.h26xPreset, tune: 'zerolatency' },
    }),
    width: config.width,
    height: config.height,
    frameRate: config.fps,
    bitrateVideo: config.bitrateKbps,
    bitrateVideoMax: config.maxBitrateKbps,
    videoCodec: Utils.normalizeVideoCodec(config.videoCodec),
    hardwareAcceleratedDecoding: config.hardwareAcceleratedDecoding,
    minimizeLatency: true,
    customInputOptions: [
        '-re',
        '-fflags', 'nobuffer',
    ],
    customFfmpegFlags: [
        '-flags', '+global_header',
    ]
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

async function joinVoiceWithDiagnostics(guildId?: string, channelId?: string) {
    logger.info(`joinVoice diagnostics: clientUser=${client.user?.id ?? 'unknown'} guildId=${guildId} channelId=${channelId}`);
    logger.info(`joinVoice diagnostics: cachedGuilds=${Array.from(client.guilds.cache.keys()).slice(0, 10).join(', ') || 'none'}`);

    const guild = guildId ? client.guilds.cache.get(guildId) : undefined;
    const channel = channelId ? (guild?.channels.cache.get(channelId) ?? client.channels.cache.get(channelId)) : undefined;

    logger.info(`joinVoice diagnostics: guildFound=${!!guild} guildName=${guild?.name ?? 'n/a'}`);
    logger.info(`joinVoice diagnostics: channelFound=${!!channel} channelType=${(channel as any)?.type ?? 'n/a'} channelName=${(channel as any)?.name ?? 'n/a'}`);
    logger.info(`joinVoice diagnostics: guildVoiceChannelExists=${!!guild?.channels.cache.get(channelId ?? '')}`);
    logger.info(`joinVoice diagnostics: clientChannelCacheHas=${client.channels.cache.has(channelId ?? '')}`);

    const joinTimeoutMs = Number(process.env.STREAM_JOIN_TIMEOUT_MS ?? 60000);

    return Promise.race([
        (async () => {
            logger.info('joinVoice diagnostics: starting native joinVoice call');
            const startedAt = Date.now();
            const result = await streamer.joinVoice(guildId, channelId);
            logger.info(`joinVoice diagnostics: native joinVoice resolved after ${Date.now() - startedAt}ms`);
            return result;
        })(),
        new Promise((_, reject) => {
            setTimeout(() => reject(new Error(`joinVoice timed out after ${joinTimeoutMs}ms for guild=${guildId} channel=${channelId}`)), joinTimeoutMs);
        })
    ]) as Promise<void>;
}

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

    logger.info(`Starting stream session=${sessionId}`);
    logger.info(`Selfbot join attempt: guild=${guildId} channel=${channelId} title=${title ?? ''} session=${sessionId}`);

    streamStatus.manualStop = false;
    streamStatus.currentSessionId = sessionId;

    try {
        logger.info('Calling streamer.joinVoice...');
        await joinVoiceWithDiagnostics(guildId, channelId);
        logger.info('joinVoice resolved successfully');

        streamStatus.joined = true;
        streamStatus.playing = true;
        streamStatus.channelInfo = { guildId: guildId ?? '', channelId: channelId ?? '' };

        if (title) {
            client.user?.setActivity(status_watch(title) as ActivityOptions);
        }

        controller?.abort();
        controller = new AbortController();
        logger.info(`stream start: preparing ffmpeg for session=${sessionId}`);

        const { command, output } = prepareStream(video, streamOpts, controller.signal);
        logger.info(`stream start: ffmpeg command object created for session=${sessionId}`);
        command.on('start', () => {
            logger.info(`FFmpeg started for session=${sessionId}`);
        });
        command.on('stderr', (data) => {
            const text = redactUrls(data.toString().trim());
            if (text) {
                logger.info('FFmpeg stderr: ' + text);
            }
        });
        command.on('error', (err) => {
            logger.info('An error happened with ffmpeg: ' + redactUrls(String(err)));
        });
        command.on('end', () => {
            logger.info('FFmpeg ended normally for session ' + sessionId);
        });

        logger.info(`stream start: invoking playStream for session=${sessionId}`);
        try {
            await playStream(output, streamer, { type: 'go-live' }, controller.signal);
            logger.info(`playStream resolved without raising an exception for session ${sessionId}`);
        } catch (err) {
            logger.info('playStream catch: ' + redactUrls(String(err)));
            controller?.abort();
            throw err;
        }

        if (!streamStatus.manualStop && streamStatus.currentSessionId === sessionId) {
            logger.info(`playStream ended without a manual stop for session ${sessionId}; cleaning up`);
            await cleanupStreamStatus();
        }
    } catch (error) {
        logger.info('Error occurred while playing video: ' + redactUrls(String(error)));
        logger.info(`Join/play debug: guild=${guildId} channel=${channelId} session=${sessionId}`);
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

    logger.info('Streambot command received');

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
                logger.info(`Rejected invalid play command session=${sessionId}`);
                return;
            }

            logger.info(`Dispatching play for session=${sessionId} guild=${guildId} channel=${channelId}`);
            await playVideo(sessionId, videoUrl, title, channelId, guildId).catch((err) => {
                logger.info(`playVideo promise rejected: ${redactUrls(String(err))}`);
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
            logger.info(`Legacy URL command received channel=${channelId} guild=${guildId}`);
            await playVideo(`legacy-${Date.now()}`, link, title, channelId, guildId).catch((err) => {
                logger.info(`legacy playVideo promise rejected: ${redactUrls(String(err))}`);
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

        logger.info(`Could not parse streambot command: ${error}`);
    }
});

