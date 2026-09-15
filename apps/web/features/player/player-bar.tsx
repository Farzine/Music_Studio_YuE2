"use client";

import { Download, Pause, Play, Volume2, VolumeX, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/controls";
import { Waveform, usePeaks } from "@/features/player/waveform";
import { api } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { usePlayer } from "@/store/player";

/** Persistent mini-player. One audio element for the whole application. */
export function PlayerBar() {
  const {
    track,
    playing,
    currentTime,
    duration,
    volume,
    muted,
    seekRequest,
    toggle,
    setPlaying,
    setCurrentTime,
    setDuration,
    setVolume,
    setMuted,
    clearSeek,
    close,
  } = usePlayer();
  const audioRef = React.useRef<HTMLAudioElement>(null);
  const { peaks } = usePeaks(track?.src ?? null);

  React.useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !track) return;
    if (playing) {
      void audio.play().catch(() => setPlaying(false));
    } else {
      audio.pause();
    }
  }, [playing, track, setPlaying]);

  React.useEffect(() => {
    const audio = audioRef.current;
    if (audio) audio.volume = muted ? 0 : volume;
  }, [volume, muted]);

  React.useEffect(() => {
    const audio = audioRef.current;
    if (audio && seekRequest != null) {
      audio.currentTime = seekRequest;
      clearSeek();
    }
  }, [seekRequest, clearSeek]);

  React.useEffect(() => {
    if (!track) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
      if (event.code === "Space") {
        event.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [track, toggle]);

  if (!track) return null;
  const progress = duration > 0 ? currentTime / duration : 0;

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--color-line)] bg-[color-mix(in_oklch,var(--color-surface)_92%,transparent)] backdrop-blur-xl">
      <audio
        ref={audioRef}
        src={track.src}
        preload="metadata"
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
        onEnded={() => setPlaying(false)}
      />
      <div className="mx-auto flex max-w-[1600px] items-center gap-4 px-4 py-3 sm:px-6">
        <Button
          variant="primary"
          size="icon"
          onClick={toggle}
          aria-label={playing ? "Pause" : "Play"}
          className="h-10 w-10 shrink-0 rounded-full"
        >
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 translate-x-[1px]" />}
        </Button>

        <div className="hidden min-w-0 sm:block sm:w-52">
          <Link
            href={`/generations/${track.id}`}
            className="block truncate text-sm font-medium hover:text-[var(--color-accent)]"
          >
            {track.title || "Untitled"}
          </Link>
          <p className="truncate text-xs text-[var(--color-ink-faint)]">{track.style}</p>
        </div>

        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="w-10 shrink-0 text-right text-xs tabular-nums text-[var(--color-ink-faint)]">
            {formatDuration(currentTime)}
          </span>
          <Waveform
            peaks={peaks}
            progress={progress}
            height={36}
            onSeek={(ratio) => {
              const audio = audioRef.current;
              if (audio && Number.isFinite(audio.duration)) audio.currentTime = ratio * audio.duration;
            }}
            className="flex-1"
          />
          <span className="w-10 shrink-0 text-xs tabular-nums text-[var(--color-ink-faint)]">
            {formatDuration(duration || track.durationSeconds)}
          </span>
        </div>

        <div className="hidden items-center gap-2 md:flex">
          <Button variant="ghost" size="icon" onClick={() => setMuted(!muted)} aria-label={muted ? "Unmute" : "Mute"}>
            {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
          </Button>
          <Slider
            className="w-24"
            value={[muted ? 0 : volume * 100]}
            max={100}
            step={1}
            aria-label="Volume"
            onValueChange={([value]) => setVolume(value / 100)}
          />
        </div>

        <Button variant="ghost" size="icon" asChild aria-label="Download">
          <a href={api.downloadUrl(track.id)} download>
            <Download className="h-4 w-4" />
          </a>
        </Button>
        <Button variant="ghost" size="icon" onClick={close} aria-label="Close player">
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
