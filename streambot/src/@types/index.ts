export interface VideoFormat {
    hasVideo: boolean;
    hasAudio: boolean;
    url: string;
    bitrate?: number;
    qualityLabel?: string;
    container?: string;
    isLiveContent?: boolean;
}