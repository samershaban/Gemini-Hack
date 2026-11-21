import { useEffect, useState } from 'react';

export type CameraState =
  | { status: 'idle' | 'requesting' }
  | { status: 'ready'; stream: MediaStream }
  | { status: 'error'; error: string };

/** Opens camera + mic once and keeps the stream for the page's lifetime. */
export function useCamera(opts: { facingMode?: 'user' | 'environment'; enabled?: boolean } = {}) {
  const { facingMode = 'user', enabled = true } = opts;
  const [state, setState] = useState<CameraState>({ status: 'idle' });

  useEffect(() => {
    if (!enabled) return;
    let stream: MediaStream | null = null;
    let cancelled = false;
    setState({ status: 'requesting' });
    if (!navigator.mediaDevices?.getUserMedia) {
      setState({ status: 'error', error: 'Camera needs HTTPS (or localhost).' });
      return;
    }
    navigator.mediaDevices
      .getUserMedia({
        video: { facingMode, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      .then((s) => {
        if (cancelled) return s.getTracks().forEach((t) => t.stop());
        stream = s;
        setState({ status: 'ready', stream: s });
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ status: 'error', error: e instanceof Error ? e.message : String(e) });
      });
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [facingMode, enabled]);

  return state;
}

const MIME_CANDIDATES = [
  'video/webm;codecs=vp9,opus',
  'video/webm;codecs=vp8,opus',
  'video/webm',
  'video/mp4;codecs=avc1,mp4a', // Safari / iOS
  'video/mp4',
];

export function pickMime(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  return MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m));
}

/** One tap starts, next tap stops: records exactly one clip. */
export class ClipRecorder {
  private rec: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private startedAt = 0;

  constructor(private stream: MediaStream) {}

  get recording() {
    return this.rec?.state === 'recording';
  }
  get elapsedMs() {
    return this.recording ? performance.now() - this.startedAt : 0;
  }

  start() {
    if (this.recording) return;
    const mimeType = pickMime();
    this.chunks = [];
    this.rec = new MediaRecorder(this.stream, {
      mimeType,
      videoBitsPerSecond: 2_500_000,
      audioBitsPerSecond: 128_000,
    });
    this.rec.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.rec.start(250); // timeslice so a crash mid-clip still leaves data
    this.startedAt = performance.now();
  }

  stop(): Promise<{ blob: Blob; durationMs: number }> {
    const rec = this.rec;
    if (!rec || rec.state === 'inactive') return Promise.reject(new Error('not recording'));
    const durationMs = performance.now() - this.startedAt;
    return new Promise((resolve) => {
      rec.onstop = () => resolve({ blob: new Blob(this.chunks, { type: rec.mimeType }), durationMs });
      rec.stop();
    });
  }
}

/** Grab a JPEG data URL of the frame at t_s in a recorded clip (local fallback for the BUSTED still). */
export async function frameAt(blob: Blob, tSec: number): Promise<string | null> {
  const url = URL.createObjectURL(blob);
  const v = document.createElement('video');
  v.muted = true;
  v.playsInline = true;
  v.src = url;
  try {
    await new Promise<void>((res, rej) => {
      v.onloadedmetadata = () => res();
      v.onerror = () => rej(new Error('video load failed'));
    });
    // MediaRecorder WebM often reports duration=Infinity until you seek past the end.
    if (!Number.isFinite(v.duration)) {
      v.currentTime = 1e9;
      await new Promise((r) => (v.onseeked = r));
    }
    const dur = Number.isFinite(v.duration) ? v.duration : tSec;
    v.currentTime = Math.max(0, Math.min(tSec, dur - 0.05));
    await new Promise((r) => (v.onseeked = r));
    const c = document.createElement('canvas');
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext('2d')!.drawImage(v, 0, 0);
    return c.toDataURL('image/jpeg', 0.85);
  } catch {
    return null;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Host voice: browser speechSynthesis (swap for a Gemini voice later). */
export function say(text: string) {
  if (!('speechSynthesis' in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.02;
  u.pitch = 0.9;
  speechSynthesis.speak(u);
}
