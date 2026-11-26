/** Read an audio file in the browser and reduce it to mono at the analysis sample rate. The file
 *  stays on the person's device; only the chord estimates are sent anywhere. */

import { SAMPLE_RATE } from "./chroma";

export const MAX_AUDIO_BYTES = 40 * 1024 * 1024;
export const MAX_SECONDS = 10 * 60;
export const MIN_SECONDS = 0.5;

export type AudioErrorCode = "too_large" | "too_long" | "too_short" | "undecodable" | "unsupported";
export class AudioLoadError extends Error {
  constructor(
    public code: AudioErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "AudioLoadError";
  }
}

/** The refusals that can be decided from the file size or length alone. */
export function checkLimits(bytes: number, seconds?: number): void {
  if (bytes > MAX_AUDIO_BYTES) throw new AudioLoadError("too_large", `This file is ${(bytes / 1048576).toFixed(0)} MB. Files over ${MAX_AUDIO_BYTES / 1048576} MB are not supported.`);
  if (seconds !== undefined) {
    if (seconds > MAX_SECONDS) throw new AudioLoadError("too_long", `This recording is ${Math.round(seconds / 60)} minutes long. Recordings over ${MAX_SECONDS / 60} minutes are not supported; try a shorter clip.`);
    if (seconds < MIN_SECONDS) throw new AudioLoadError("too_short", "This recording is too short to contain a chord (under half a second).");
  }
}

export type LoadedAudio = { samples: Float32Array; duration: number; sampleRate: number; originalRate: number; channels: number };

export async function loadAudio(file: Blob): Promise<LoadedAudio> {
  checkLimits(file.size);
  const Ctx = typeof AudioContext !== "undefined" ? AudioContext : undefined;
  if (!Ctx || typeof OfflineAudioContext === "undefined") throw new AudioLoadError("unsupported", "This browser cannot decode audio files.");
  const data = await file.arrayBuffer();
  const ctx = new Ctx();
  let decoded: AudioBuffer;
  try {
    decoded = await ctx.decodeAudioData(data);
  } catch {
    throw new AudioLoadError("undecodable", "This file could not be read as audio. Try a WAV, MP3, M4A or OGG file.");
  } finally {
    void ctx.close();
  }
  checkLimits(file.size, decoded.duration);
  const length = Math.max(1, Math.ceil(decoded.duration * SAMPLE_RATE));
  const offline = new OfflineAudioContext(1, length, SAMPLE_RATE); // mixing down to one channel and resampling happen here
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const rendered = await offline.startRendering();
  return { samples: rendered.getChannelData(0), duration: decoded.duration, sampleRate: SAMPLE_RATE, originalRate: decoded.sampleRate, channels: decoded.numberOfChannels };
}
