"use client";

import { create } from "zustand";

export interface PlayerTrack {
  id: string;
  title: string;
  style: string;
  src: string;
  durationSeconds: number | null;
}

interface PlayerState {
  track: PlayerTrack | null;
  playing: boolean;
  currentTime: number;
  duration: number;
  volume: number;
  muted: boolean;
  play: (track: PlayerTrack) => void;
  toggle: () => void;
  setPlaying: (playing: boolean) => void;
  setCurrentTime: (value: number) => void;
  setDuration: (value: number) => void;
  setVolume: (value: number) => void;
  setMuted: (value: boolean) => void;
  seekRequest: number | null;
  requestSeek: (value: number) => void;
  clearSeek: () => void;
  close: () => void;
}

export const usePlayer = create<PlayerState>((set, get) => ({
  track: null,
  playing: false,
  currentTime: 0,
  duration: 0,
  volume: 0.9,
  muted: false,
  seekRequest: null,
  play: (track) => {
    const current = get().track;
    if (current?.id === track.id) {
      set({ playing: !get().playing });
      return;
    }
    set({ track, playing: true, currentTime: 0, duration: track.durationSeconds ?? 0 });
  },
  toggle: () => set({ playing: !get().playing }),
  setPlaying: (playing) => set({ playing }),
  setCurrentTime: (currentTime) => set({ currentTime }),
  setDuration: (duration) => set({ duration }),
  setVolume: (volume) => set({ volume, muted: volume === 0 }),
  setMuted: (muted) => set({ muted }),
  requestSeek: (seekRequest) => set({ seekRequest }),
  clearSeek: () => set({ seekRequest: null }),
  close: () => set({ track: null, playing: false, currentTime: 0, duration: 0 }),
}));
