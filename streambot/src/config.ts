import dotenv from "dotenv"
import bcrypt from "bcryptjs";


dotenv.config()

const VALID_VIDEO_CODECS = ['VP8', 'H264', 'H265', 'VP9', 'AV1'];

export default {
    // Selfbot options
    token: process.env.TOKEN || '',

    // General options
    videosDir: process.env.VIDEOS_DIR ? process.env.VIDEOS_DIR : './videos',
    previewCacheDir: process.env.PREVIEW_CACHE_DIR ? process.env.PREVIEW_CACHE_DIR : './tmp/preview-cache',

    // Stream options
    respect_video_params: process.env.STREAM_RESPECT_VIDEO_PARAMS ? parseBoolean(process.env.STREAM_RESPECT_VIDEO_PARAMS) : false,
    width: process.env.STREAM_WIDTH ? parseInt(process.env.STREAM_WIDTH) : 1280,
    height: process.env.STREAM_HEIGHT ? parseInt(process.env.STREAM_HEIGHT) : 720,
    fps: process.env.STREAM_FPS ? parseInt(process.env.STREAM_FPS) : 30,
    bitrateKbps: process.env.STREAM_BITRATE_KBPS ? parseInt(process.env.STREAM_BITRATE_KBPS) : 1000,
    maxBitrateKbps: process.env.STREAM_MAX_BITRATE_KBPS ? parseInt(process.env.STREAM_MAX_BITRATE_KBPS) : 2500,
    hardwareAcceleratedDecoding: process.env.STREAM_HARDWARE_ACCELERATION ? parseBoolean(process.env.STREAM_HARDWARE_ACCELERATION) : false,
    h26xPreset: process.env.STREAM_H26X_PRESET ? parsePreset(process.env.STREAM_H26X_PRESET) : 'ultrafast',
    videoCodec: process.env.STREAM_VIDEO_CODEC ? parseVideoCodec(process.env.STREAM_VIDEO_CODEC) : 'H264',
}

function parseVideoCodec(value: string): "VP8" | "H264" | "H265" {
    if (typeof value === "string") {
        value = value.trim().toUpperCase();
    }
    if (VALID_VIDEO_CODECS.includes(value)) {
        return value as "VP8" | "H264" | "H265";
    }
    return "H264";
}

function parsePreset(value: string): "ultrafast" | "superfast" | "veryfast" | "faster" | "fast" | "medium" | "slow" | "slower" | "veryslow" {
    if (typeof value === "string") {
        value = value.trim().toLowerCase();
    }
    switch (value) {
        case "ultrafast":
        case "superfast":
        case "veryfast":
        case "faster":
        case "fast":
        case "medium":
        case "slow":
        case "slower":
        case "veryslow":
            return value as "ultrafast" | "superfast" | "veryfast" | "faster" | "fast" | "medium" | "slow" | "slower" | "veryslow";
        default:
            return "ultrafast";
    }
}

function parseBoolean(value: string | undefined): boolean {
    if (typeof value === "string") {
        value = value.trim().toLowerCase();
    }
    switch (value) {
        case "true":
            return true;
        default:
            return false;
    }
}