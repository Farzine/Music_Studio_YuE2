"use client";

import * as React from "react";

import { cn } from "@/lib/cn";

/**
 * Peaks decoded from the real audio file.
 *
 * When the browser cannot decode the container (FLAC support varies), this
 * returns null and the caller shows a plain seek bar instead of drawing an
 * invented waveform.
 */
export function usePeaks(url: string | null, buckets = 240) {
  const [peaks, setPeaks] = React.useState<Float32Array | null>(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    if (!url) {
      setPeaks(null);
      setFailed(false);
      return;
    }
    let cancelled = false;
    setPeaks(null);
    setFailed(false);

    (async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error("fetch failed");
        const bytes = await response.arrayBuffer();
        const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const context = new Ctor();
        const buffer = await context.decodeAudioData(bytes);
        const channel = buffer.getChannelData(0);
        const size = Math.floor(channel.length / buckets) || 1;
        const result = new Float32Array(buckets);
        for (let index = 0; index < buckets; index += 1) {
          let peak = 0;
          const start = index * size;
          for (let offset = 0; offset < size; offset += 1) {
            const value = Math.abs(channel[start + offset] ?? 0);
            if (value > peak) peak = value;
          }
          result[index] = peak;
        }
        await context.close();
        if (!cancelled) setPeaks(result);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [url, buckets]);

  return { peaks, failed };
}

export function Waveform({
  peaks,
  progress,
  onSeek,
  className,
  height = 56,
}: {
  peaks: Float32Array | null;
  progress: number;
  onSeek?: (ratio: number) => void;
  className?: string;
  height?: number;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !peaks) return;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, height);

    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--color-accent").trim() || "#4ade80";
    const idle = styles.getPropertyValue("--color-line").trim() || "#3f3f46";
    const barWidth = Math.max(1, width / peaks.length - 1);
    const maximum = Math.max(...peaks, 0.001);

    peaks.forEach((peak, index) => {
      const x = (index * width) / peaks.length;
      const amplitude = Math.max(2, (peak / maximum) * (height - 4));
      context.fillStyle = x / width <= progress ? accent : idle;
      context.beginPath();
      context.roundRect(x, (height - amplitude) / 2, barWidth, amplitude, barWidth / 2);
      context.fill();
    });
  }, [peaks, progress, height]);

  const seek = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!onSeek) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    onSeek(Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)));
  };

  if (!peaks) {
    return (
      <div
        role={onSeek ? "slider" : undefined}
        aria-label="Seek"
        aria-valuenow={Math.round(progress * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        tabIndex={onSeek ? 0 : undefined}
        onClick={seek}
        className={cn("group relative w-full cursor-pointer rounded-full bg-[var(--color-surface-2)]", className)}
        style={{ height: 6 }}
      >
        <div
          className="h-full rounded-full bg-[var(--color-accent)] transition-[width]"
          style={{ width: `${Math.min(100, progress * 100)}%` }}
        />
      </div>
    );
  }

  return (
    <div onClick={seek} className={cn("w-full cursor-pointer", className)} style={{ height }}>
      <canvas ref={canvasRef} className="h-full w-full" style={{ height }} />
    </div>
  );
}
