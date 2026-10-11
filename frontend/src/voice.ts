import { useAudioPlayer, AudioModule, useAudioRecorder, RecordingPresets } from "expo-audio";
import { useEffect, useRef, useState, useCallback } from "react";
import { api, getToken } from "./api";
import { Platform } from "react-native";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;

/** Hook to play back TTS from a given text; call play(text) to speak. */
export function useTTS() {
  const [audioUri, setAudioUri] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const player = useAudioPlayer(audioUri);

  const play = useCallback(async (text: string) => {
    if (!text) return;
    setLoading(true);
    try {
      const r = await api("/api/tts/generate", { method: "POST", body: JSON.stringify({ text }) });
      if (r?.audio_url) {
        setAudioUri(r.audio_url);
      }
    } catch (e) {
      console.warn("TTS failed", e);
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    if (audioUri && player) {
      try { player.seekTo(0); player.play(); } catch {}
    }
  }, [audioUri, player]);

  const stop = useCallback(() => {
    try { player?.pause(); } catch {}
  }, [player]);

  return { play, stop, loading, playing: !!player?.playing };
}

/** Hook to record audio -> upload -> get text back. */
export function useSTT(onTranscript: (text: string) => void) {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const [recording, setRecording] = useState(false);
  const [loading, setLoading] = useState(false);

  const start = useCallback(async () => {
    try {
      const perm = await AudioModule.requestRecordingPermissionsAsync();
      if (!perm.granted) return;
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecording(true);
    } catch (e) {
      console.warn("record start failed", e);
    }
  }, [recorder]);

  const stop = useCallback(async () => {
    try {
      await recorder.stop();
      setRecording(false);
      const uri = recorder.uri;
      if (!uri) return;
      setLoading(true);
      const token = await getToken();
      const form = new FormData();
      if (Platform.OS === "web") {
        const res = await fetch(uri);
        const blob = await res.blob();
        form.append("audio", blob, "voice.webm");
      } else {
        form.append("audio", { uri, name: "voice.m4a", type: "audio/m4a" } as any);
      }
      const r = await fetch(`${BASE}/api/stt/transcribe`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const data = await r.json();
      if (data?.text) onTranscript(data.text);
    } catch (e) {
      console.warn("stt failed", e);
    } finally { setLoading(false); }
  }, [recorder, onTranscript]);

  return { start, stop, recording, loading };
}
