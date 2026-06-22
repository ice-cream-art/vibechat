"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

type Phase = "input" | "result" | "matching" | "chat";
type AtmosphereMode = "auto" | "snow" | "stars" | "rain" | "bubbles" | "off";
type SoundCue = "send" | "receive" | "match";

type EmotionResult = {
  primary_emotion: string;
  secondary_emotions: string[];
  valence: number;
  arousal: number;
  intensity: number;
  keywords: string[];
  explanation: string;
  safety_level: "normal" | "concern";
  provider: "demo" | "openai" | "anthropic";
};

type MatchTicket = {
  ticket_id: string;
  access_token: string;
  alias: string;
  status: "waiting" | "matched";
};

type MatchStatus = {
  ticket_id: string;
  status: "waiting" | "matched" | "cancelled";
  waited_seconds: number;
  conversation_id?: string;
  access_token?: string;
  alias?: string;
  partner_alias?: string;
  match_score?: number;
  match_reason?: string;
  demo_available: boolean;
  partner_is_demo?: boolean;
};

type Message = {
  id: string;
  sender_alias: string;
  content: string;
  created_at: string;
  pending?: boolean;
};

type Conversation = {
  id: string;
  self_alias: string;
  partner_alias: string;
  match_score: number;
  match_reason: string;
  messages: Message[];
  partner_is_demo?: boolean;
};

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "production" ? "/_/backend" : "http://localhost:8000")
).replace(/\/$/, "");

const CHAT_API_URL = (
  process.env.NEXT_PUBLIC_CHAT_API_URL || API_URL
).replace(/\/$/, "");

const TTS_API_URL = process.env.NEXT_PUBLIC_TTS_API_URL?.replace(/\/$/, "");
const TTS_REF_AUDIO_PATH = process.env.NEXT_PUBLIC_TTS_REF_AUDIO_PATH || "";
const TTS_PROMPT_TEXT = process.env.NEXT_PUBLIC_TTS_PROMPT_TEXT || "";

function websocketBaseUrl() {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL.replace(/\/$/, "");
  }
  if (CHAT_API_URL.startsWith("/") && typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}${CHAT_API_URL}`;
  }
  return CHAT_API_URL.replace(/^http/, "ws");
}

const examples = [
  "比赛快开始了，我既期待又有点紧张",
  "忙完一天，突然很想找个人安静聊聊",
  "今天有件小事让我开心了很久",
];

const topicCards = [
  { title: "考前焦虑互助", meta: "128 人正在同频" },
  { title: "深夜安静聊天", meta: "76 条温柔回复" },
  { title: "今日小确幸", meta: "42 个开心瞬间" },
];

const guideTips = [
  "今天最想被谁理解？",
  "这件事里最卡住你的点是什么？",
  "如果只说一句真话，会是什么？",
];

const atmosphereOptions: { value: AtmosphereMode; label: string }[] = [
  { value: "auto", label: "自动" },
  { value: "snow", label: "雪" },
  { value: "stars", label: "星" },
  { value: "rain", label: "雨" },
  { value: "bubbles", label: "泡" },
  { value: "off", label: "关" },
];

const emotionMeta: Record<string, { glyph: string; color: string; caption: string }> = {
  开心: { glyph: "✦", color: "#ffd166", caption: "明亮而舒展" },
  兴奋: { glyph: "↗", color: "#ff8a5b", caption: "高能量流动" },
  期待: { glyph: "◌", color: "#ffc57a", caption: "向未来靠近" },
  平静: { glyph: "≈", color: "#76d7c4", caption: "缓慢而安稳" },
  焦虑: { glyph: "⌁", color: "#c7a6ff", caption: "被不确定拉扯" },
  难过: { glyph: "◒", color: "#8bb7e8", caption: "需要被听见" },
  孤独: { glyph: "·", color: "#9fa8da", caption: "渴望真实连接" },
  愤怒: { glyph: "⌁", color: "#ff7b7b", caption: "强烈而紧绷" },
  疲惫: { glyph: "—", color: "#9cb7a5", caption: "能量暂时偏低" },
  复杂: { glyph: "∞", color: "#d7aefb", caption: "不止一种感受" },
};

const guideAvatarMeta: Record<string, { tone: string; face: string; badge: string }> = {
  开心: { tone: "happy", face: "⌣", badge: "✦" },
  兴奋: { tone: "excited", face: "ᗜ", badge: "↗" },
  期待: { tone: "hopeful", face: "ᵕ", badge: "◌" },
  平静: { tone: "calm", face: "–", badge: "≈" },
  焦虑: { tone: "anxious", face: "﹏", badge: "⌁" },
  难过: { tone: "sad", face: "︵", badge: "◒" },
  孤独: { tone: "lonely", face: "·", badge: "·" },
  愤怒: { tone: "angry", face: "へ", badge: "!" },
  疲惫: { tone: "tired", face: "＿", badge: "—" },
  复杂: { tone: "mixed", face: "⌁", badge: "∞" },
};

function apiErrorMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

function sameMessageList(current: Message[], next: Message[]) {
  return current.length === next.length && current.every((message, index) => (
    message.id === next[index]?.id &&
    message.sender_alias === next[index]?.sender_alias &&
    message.content === next[index]?.content &&
    Boolean(message.pending) === Boolean(next[index]?.pending)
  ));
}

function sameConversation(current: Conversation | null, next: Conversation) {
  return Boolean(
    current &&
    current.id === next.id &&
    current.self_alias === next.self_alias &&
    current.partner_alias === next.partner_alias &&
    current.match_score === next.match_score &&
    current.match_reason === next.match_reason &&
    current.partner_is_demo === next.partner_is_demo
  );
}

function hasNewIncomingMessage(current: Message[], next: Message[], selfAlias: string) {
  return next.some((message) => (
    message.sender_alias !== selfAlias &&
    !current.some((item) => item.id === message.id)
  ));
}

function isMatchingOptimisticMessage(pending: Message, confirmed: Message) {
  return Boolean(pending.pending) &&
    pending.sender_alias === confirmed.sender_alias &&
    pending.content === confirmed.content;
}

function mergeConfirmedMessages(current: Message[], confirmed: Message[]) {
  const preserved = current.filter((message) => (
    !confirmed.some((item) => item.id === message.id) &&
    !confirmed.some((item) => isMatchingOptimisticMessage(message, item))
  ));
  return [...confirmed, ...preserved];
}

function mergeIncomingMessage(current: Message[], incoming: Message) {
  if (current.some((message) => message.id === incoming.id)) return current;
  return [
    ...current.filter((message) => !isMatchingOptimisticMessage(message, incoming)),
    incoming,
  ];
}

function atmosphereForMood(mood: string): Exclude<AtmosphereMode, "auto" | "off"> {
  if (["难过", "疲惫"].includes(mood)) return "snow";
  if (["焦虑", "愤怒"].includes(mood)) return "rain";
  if (["开心", "兴奋", "孤独"].includes(mood)) return "stars";
  return "bubbles";
}

function soundFamilyForMood(mood: string): Exclude<AtmosphereMode, "auto" | "off"> {
  return atmosphereForMood(mood);
}

function guideSpeechVoice() {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  const voices = window.speechSynthesis.getVoices();
  const chineseVoices = voices.filter((voice) => /zh|cmn|Chinese|中文/i.test(`${voice.lang} ${voice.name}`));
  const preferred = [
    "Xiaoxiao",
    "晓晓",
    "Xiaoyi",
    "晓伊",
    "Huihui",
    "慧慧",
    "Ting-Ting",
    "Mei-Jia",
    "Yaoyao",
    "瑶瑶",
  ];
  return (
    chineseVoices.find((voice) => preferred.some((name) => voice.name.includes(name))) ||
    chineseVoices.find((voice) => voice.lang.toLowerCase().includes("zh-cn")) ||
    chineseVoices[0] ||
    voices[0] ||
    null
  );
}

function ttsEndpoint() {
  if (!TTS_API_URL) return "";
  if (TTS_API_URL.startsWith("/") || /\/tts(?:[/?#]|$)/.test(TTS_API_URL)) {
    return TTS_API_URL;
  }
  return `${TTS_API_URL}/tts`;
}

function createAudioContext() {
  const AudioContextClass = window.AudioContext || (window as Window & typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  }).webkitAudioContext;
  return AudioContextClass ? new AudioContextClass() : null;
}

class MoodAudioEngine {
  private context: AudioContext | null = null;
  private master?: GainNode;
  private ambientGain?: GainNode;
  private fxGain?: GainNode;
  private ambientSources: AudioScheduledSourceNode[] = [];
  private currentMood = "";

  private ensureContext() {
    if (this.context || typeof window === "undefined") return this.context;
    this.context = createAudioContext();
    if (!this.context) return null;
    this.master = this.context.createGain();
    this.ambientGain = this.context.createGain();
    this.fxGain = this.context.createGain();
    this.master.gain.value = 0.75;
    this.ambientGain.gain.value = 0;
    this.fxGain.gain.value = 0.18;
    this.ambientGain.connect(this.master);
    this.fxGain.connect(this.master);
    this.master.connect(this.context.destination);
    return this.context;
  }

  async resume() {
    const context = this.ensureContext();
    if (context?.state === "suspended") await context.resume();
  }

  startMood(mood: string) {
    const context = this.ensureContext();
    if (!context || !this.ambientGain || this.currentMood === mood) return;
    this.stopAmbient();
    this.currentMood = mood;
    const profiles = {
      snow: { volume: 0.055, tones: [174, 261.63], noise: 0.014, filter: 760 },
      rain: { volume: 0.06, tones: [146.83, 220], noise: 0.022, filter: 1400 },
      stars: { volume: 0.05, tones: [329.63, 493.88, 659.25], noise: 0.006, filter: 2200 },
      bubbles: { volume: 0.052, tones: [220, 330, 440], noise: 0.01, filter: 1200 },
    } satisfies Record<Exclude<AtmosphereMode, "auto" | "off">, {
      volume: number;
      tones: number[];
      noise: number;
      filter: number;
    }>;
    const profile = profiles[soundFamilyForMood(mood)];
    this.ambientGain.gain.cancelScheduledValues(context.currentTime);
    this.ambientGain.gain.setTargetAtTime(profile.volume, context.currentTime, 0.8);
    profile.tones.forEach((frequency, index) => this.addAmbientTone(frequency, index));
    this.addAmbientNoise(profile.noise, profile.filter);
  }

  stopAmbient() {
    const context = this.context;
    if (context && this.ambientGain) {
      this.ambientGain.gain.cancelScheduledValues(context.currentTime);
      this.ambientGain.gain.setTargetAtTime(0, context.currentTime, 0.3);
    }
    this.ambientSources.forEach((source) => {
      try {
        source.stop();
      } catch {
        // Source may already be stopped by the browser.
      }
      source.disconnect();
    });
    this.ambientSources = [];
    this.currentMood = "";
  }

  dispose() {
    this.stopAmbient();
    void this.context?.close();
    this.context = null;
  }

  play(cue: SoundCue, mood: string) {
    const context = this.ensureContext();
    if (!context || !this.fxGain) return;
    const family = soundFamilyForMood(mood);
    if (cue === "send") {
      this.playTone(family === "rain" ? 392 : 523.25, 0.09, 0.13, "sine");
      window.setTimeout(() => this.playTone(family === "stars" ? 880 : 659.25, 0.12, 0.1, "triangle"), 70);
      return;
    }
    if (cue === "receive") {
      const base = family === "snow" ? 349.23 : family === "rain" ? 293.66 : family === "stars" ? 739.99 : 440;
      this.playTone(base, 0.16, 0.11, family === "rain" ? "sine" : "triangle");
      window.setTimeout(() => this.playTone(base * 1.5, 0.18, 0.07, "sine"), 110);
      return;
    }
    [392, 493.88, 659.25].forEach((frequency, index) => {
      window.setTimeout(() => this.playTone(frequency, 0.18, 0.1, "triangle"), index * 95);
    });
  }

  private addAmbientTone(frequency: number, index: number) {
    const context = this.context;
    if (!context || !this.ambientGain) return;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = index % 2 === 0 ? "sine" : "triangle";
    oscillator.frequency.value = frequency;
    oscillator.detune.value = (index - 1) * 4;
    gain.gain.value = 0.012 / (index + 1);
    oscillator.connect(gain);
    gain.connect(this.ambientGain);
    oscillator.start();
    this.ambientSources.push(oscillator);
  }

  private addAmbientNoise(volume: number, filterFrequency: number) {
    const context = this.context;
    if (!context || !this.ambientGain) return;
    const buffer = context.createBuffer(1, context.sampleRate * 2, context.sampleRate);
    const data = buffer.getChannelData(0);
    let last = 0;
    for (let i = 0; i < data.length; i += 1) {
      last = (last + (Math.random() * 2 - 1) * 0.08) * 0.96;
      data[i] = last;
    }
    const source = context.createBufferSource();
    const filter = context.createBiquadFilter();
    const gain = context.createGain();
    source.buffer = buffer;
    source.loop = true;
    filter.type = "lowpass";
    filter.frequency.value = filterFrequency;
    gain.gain.value = volume;
    source.connect(filter);
    filter.connect(gain);
    gain.connect(this.ambientGain);
    source.start();
    this.ambientSources.push(source);
  }

  private playTone(frequency: number, duration: number, volume: number, type: OscillatorType) {
    const context = this.context;
    if (!context || !this.fxGain) return;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = type;
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(volume, context.currentTime + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + duration);
    oscillator.connect(gain);
    gain.connect(this.fxGain);
    oscillator.start();
    oscillator.stop(context.currentTime + duration + 0.03);
  }
}

function AtmosphereLayer({
  mode,
  mood,
  variant = "page",
}: {
  mode: AtmosphereMode;
  mood: string;
  variant?: "page" | "panel";
}) {
  const resolvedMode = mode === "auto" ? atmosphereForMood(mood) : mode;
  if (resolvedMode === "off") return null;
  return (
    <div className={`atmosphere ${variant === "panel" ? "atmosphereInline" : ""} atmosphere-${resolvedMode}`} aria-hidden="true">
      {Array.from({ length: 26 }, (_, index) => (
        <span
          className="atmosphereParticle"
          key={index}
          style={{
            "--i": index,
            "--x": `${(index * 37) % 100}%`,
            "--delay": `${(index % 9) * -0.7}s`,
            "--duration": `${8 + (index % 7) * 1.2}s`,
            "--size": `${5 + (index % 5) * 2}px`,
            "--drift": `${((index % 9) - 4) * 18}px`,
            "--wide-drift": `${((index % 9) - 4) * 24}px`,
            "--fall-drift": `${((index % 5) - 2) * 24}px`,
          } as React.CSSProperties}
        />
      ))}
    </div>
  );
}

function GuideAvatar({
  emotion,
  size = "md",
}: {
  emotion?: string;
  size?: "sm" | "md" | "lg";
}) {
  const meta = guideAvatarMeta[emotion || ""] || guideAvatarMeta["复杂"];
  return (
    <span className={`guideAvatar guideAvatar-${meta.tone} guideAvatar-${size}`} aria-label={`飞行雪绒头像`}>
      <span className="guideAvatarHalo" />
      <img className="guideAvatarImage" src="/guide-avatar.webp" alt="" />
      <span className="guideAvatarBadge">{meta.badge}</span>
    </span>
  );
}

export default function Home() {
  const [phase, setPhase] = useState<Phase>("input");
  const [text, setText] = useState("");
  const [emotion, setEmotion] = useState<EmotionResult | null>(null);
  const [ticket, setTicket] = useState<MatchTicket | null>(null);
  const [match, setMatch] = useState<MatchStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [atmosphereMode, setAtmosphereMode] = useState<AtmosphereMode>("auto");
  const [soundEnabled, setSoundEnabled] = useState(false);
  const soundEngineRef = useRef<MoodAudioEngine | null>(null);
  const previousPhaseRef = useRef<Phase>("input");
  const currentMood = emotion?.primary_emotion || "平静";

  const ensureSoundEngine = useCallback(() => {
    if (!soundEngineRef.current && typeof window !== "undefined") {
      soundEngineRef.current = new MoodAudioEngine();
    }
    return soundEngineRef.current;
  }, []);

  const playSound = useCallback((cue: SoundCue, mood = currentMood) => {
    if (!soundEnabled) return;
    const engine = ensureSoundEngine();
    if (!engine) return;
    void engine.resume().then(() => engine.play(cue, mood)).catch(() => undefined);
  }, [currentMood, ensureSoundEngine, soundEnabled]);

  const toggleSound = () => {
    const next = !soundEnabled;
    setSoundEnabled(next);
    window.localStorage.setItem("vibechat-sound", next ? "on" : "off");
    const engine = ensureSoundEngine();
    if (next) {
      void engine?.resume().then(() => {
        engine.startMood(currentMood);
        engine.play("receive", currentMood);
      }).catch(() => undefined);
    } else {
      engine?.stopAmbient();
    }
  };

  useEffect(() => {
    setSoundEnabled(window.localStorage.getItem("vibechat-sound") === "on");
    return () => soundEngineRef.current?.dispose();
  }, []);

  useEffect(() => {
    const engine = ensureSoundEngine();
    if (!soundEnabled) {
      engine?.stopAmbient();
      return;
    }
    if (!engine) return;
    void engine.resume().then(() => engine.startMood(currentMood)).catch(() => undefined);
  }, [currentMood, ensureSoundEngine, soundEnabled]);

  useEffect(() => {
    if (soundEnabled && previousPhaseRef.current !== "chat" && phase === "chat") {
      playSound("match", currentMood);
    }
    previousPhaseRef.current = phase;
  }, [currentMood, phase, playSound, soundEnabled]);

  const analyze = async (event: FormEvent) => {
    event.preventDefault();
    if (text.trim().length < 2) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/emotions/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text.trim() }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(apiErrorMessage(payload, "情绪分析暂时没有回应"));
      setEmotion(payload);
      setPhase("result");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接情绪分析服务失败");
    } finally {
      setLoading(false);
    }
  };

  const joinMatch = async () => {
    if (!emotion) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${CHAT_API_URL}/api/matches/join`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ emotion, source_text: text.trim() }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(apiErrorMessage(payload, "暂时无法进入匹配"));
      setTicket(payload);
      setPhase("matching");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "进入匹配失败");
    } finally {
      setLoading(false);
    }
  };

  const pollStatus = useCallback(async () => {
    if (!ticket) return;
    try {
      const response = await fetch(
        `${CHAT_API_URL}/api/matches/${ticket.ticket_id}?access_token=${encodeURIComponent(ticket.access_token)}`,
        { cache: "no-store" }
      );
      if (!response.ok) return;
      const payload: MatchStatus = await response.json();
      setMatch(payload);
      if (payload.status === "matched") setPhase("chat");
    } catch {
      // A transient polling failure should not eject the user from the queue.
    }
  }, [ticket]);

  useEffect(() => {
    if (phase !== "matching" || !ticket) return;
    void pollStatus();
    const timer = window.setInterval(() => void pollStatus(), 1200);
    return () => window.clearInterval(timer);
  }, [phase, ticket, pollStatus]);

  const useDemoPartner = async () => {
    if (!ticket) return;
    setLoading(true);
    try {
      const response = await fetch(
        `${CHAT_API_URL}/api/matches/${ticket.ticket_id}/demo?access_token=${encodeURIComponent(ticket.access_token)}`,
        { method: "POST" }
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(apiErrorMessage(payload, "演示伙伴暂时离线"));
      setMatch(payload);
      setPhase("chat");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接演示伙伴失败");
    } finally {
      setLoading(false);
    }
  };

  const cancelMatch = async () => {
    if (ticket) {
      await fetch(
        `${CHAT_API_URL}/api/matches/${ticket.ticket_id}/cancel?access_token=${encodeURIComponent(ticket.access_token)}`,
        { method: "POST" }
      ).catch(() => undefined);
    }
    setTicket(null);
    setMatch(null);
    setPhase("result");
  };

  const reset = () => {
    setPhase("input");
    setText("");
    setEmotion(null);
    setTicket(null);
    setMatch(null);
    setError("");
  };

  return (
    <main className="shell">
      <AtmosphereLayer mode={atmosphereMode} mood={currentMood} />
      <div className="ambient ambientOne" />
      <div className="ambient ambientTwo" />
      <header className="siteHeader">
        <button className="brand" onClick={reset} aria-label="返回 VibeChat 首页">
          <span className="brandMark"><span /></span>
          <span>VibeChat</span>
        </button>
        <nav className="siteNav" aria-label="主导航">
          <button type="button" className="active">首页</button>
          <button type="button">同频广场</button>
          <button type="button">AI向导</button>
          <button type="button">更多</button>
        </nav>
        <div className="searchBox">
          <span>搜索</span>
          <b>⌕</b>
        </div>
        <div className="privacyPill"><span className="statusDot" />匿名 · 安全 · 此刻</div>
        <div className="atmospherePicker" aria-label="氛围模式">
          {atmosphereOptions.map((option) => (
            <button
              aria-pressed={atmosphereMode === option.value}
              className={atmosphereMode === option.value ? "active" : ""}
              key={option.value}
              onClick={() => setAtmosphereMode(option.value)}
              title={`${option.label}氛围`}
              type="button"
            >
              {option.label}
            </button>
          ))}
        </div>
        <button
          aria-pressed={soundEnabled}
          className={`soundToggle ${soundEnabled ? "active" : ""}`}
          onClick={toggleSound}
          title={soundEnabled ? "关闭情绪音效" : "开启情绪音效"}
          type="button"
        >
          <span>{soundEnabled ? "声" : "静"}</span>
          <i />
        </button>
        <button className="registerButton" type="button">注册</button>
        <button className="loginButton" type="button">登录</button>
      </header>

      <section className={`stage phase-${phase}`}>
        {phase === "input" && (
          <InputPanel
            text={text}
            setText={setText}
            analyze={analyze}
            loading={loading}
            error={error}
          />
        )}
        {phase === "result" && emotion && (
          <ResultPanel
            emotion={emotion}
            onBack={() => setPhase("input")}
            onMatch={joinMatch}
            loading={loading}
            error={error}
          />
        )}
        {phase === "matching" && emotion && ticket && (
          <MatchingPanel
            emotion={emotion}
            alias={ticket.alias}
            waited={match?.waited_seconds || 0}
            demoAvailable={Boolean(match?.demo_available)}
            loading={loading}
            onCancel={cancelMatch}
            onDemo={useDemoPartner}
          />
        )}
        {phase === "chat" && ticket && match?.conversation_id && match.access_token && (
          <ChatPanel
            atmosphereMode={atmosphereMode}
            match={match}
            emotion={emotion}
            onLeave={reset}
            onReceiveSound={() => playSound("receive")}
            onSendSound={() => playSound("send")}
          />
        )}
      </section>

      <footer className="siteFooter">
        <span>情绪没有标准答案</span>
        <span className="footerLine" />
        <span>连接从被理解开始</span>
      </footer>
    </main>
  );
}

function InputPanel({
  text,
  setText,
  analyze,
  loading,
  error,
}: {
  text: string;
  setText: (value: string) => void;
  analyze: (event: FormEvent) => void;
  loading: boolean;
  error: string;
}) {
  return (
    <div className="heroGrid">
      <div className="heroCopy">
        <div className="eyebrow"><span /> YOUR FEELING, RIGHT NOW</div>
        <h1>有人会懂得<br /><em>你此刻的频率</em></h1>
        <p className="lead">不需要完美介绍自己。写下现在的心情，AI 会为你找到一位真正同频的陌生人。</p>
        <div className="trustRow">
          <span><b>01</b> AI 理解情绪</span>
          <span><b>02</b> 同频匿名匹配</span>
          <span><b>03</b> 自然开始对话</span>
        </div>
        <div className="topicGrid">
          {topicCards.map((topic) => (
            <article key={topic.title}>
              <strong>{topic.title}</strong>
              <span>{topic.meta}</span>
            </article>
          ))}
        </div>
      </div>

      <form className="inputCard" onSubmit={analyze}>
        <div className="cardTopline">
          <span>写下此刻心情</span>
          <span className="charCount">{text.length}/500</span>
        </div>
        <label className="srOnly" htmlFor="feeling">写下此刻的心情</label>
        <textarea
          id="feeling"
          value={text}
          onChange={(event) => setText(event.target.value.slice(0, 500))}
          placeholder="不用组织语言，想到什么就写什么……"
          rows={7}
          autoFocus
        />
        <div className="promptIdeas">
          <span>试着写下</span>
          {examples.map((example, index) => (
            <button type="button" key={example} onClick={() => setText(example)}>{example}</button>
          ))}
        </div>
        {error && <div className="errorMessage" role="alert">{error}</div>}
        <button className="primaryButton" type="submit" disabled={loading || text.trim().length < 2}>
          {loading ? <><span className="miniSpinner" />正在理解你的情绪</> : <>感受我的情绪 <span>↗</span></>}
        </button>
        <p className="privacyNote"><span>⌾</span> 你的文字仅用于本次情绪匹配，不会公开展示</p>
      </form>
    </div>
  );
}

function ResultPanel({
  emotion,
  onBack,
  onMatch,
  loading,
  error,
}: {
  emotion: EmotionResult;
  onBack: () => void;
  onMatch: () => void;
  loading: boolean;
  error: string;
}) {
  const meta = emotionMeta[emotion.primary_emotion] || emotionMeta["复杂"];
  const positive = Math.round(((emotion.valence + 1) / 2) * 100);
  return (
    <div className="resultLayout" style={{ "--emotion-color": meta.color } as React.CSSProperties}>
      <div className="resultIntro">
        <button className="textButton" onClick={onBack}>← 重新说说</button>
        <div className="eyebrow"><span /> AI 情绪分析</div>
        <h2>你的情绪<br />已经被听见</h2>
        <p>这不是定义，只是对你此刻的一次温柔解读。</p>
      </div>
      <div className="emotionCard">
        <div className="emotionHeader">
          <div>
            <span className="tinyLabel">主情绪</span>
            <h3>{emotion.primary_emotion}</h3>
            <p>{meta.caption}</p>
          </div>
          <div className="emotionOrb" style={{ "--progress": `${Math.round(emotion.intensity * 360)}deg` } as React.CSSProperties}>
            <div><b>{Math.round(emotion.intensity * 100)}</b><span>强度</span></div>
          </div>
        </div>
        <blockquote>“{emotion.explanation}”</blockquote>
        <div className="meterGroup">
          <Meter label="情绪能量" value={Math.round(emotion.arousal * 100)} />
          <Meter label="正向感受" value={positive} />
          <Meter label="表达强度" value={Math.round(emotion.intensity * 100)} />
        </div>
        <div className="keywordRow">
          {emotion.keywords.map((keyword) => <span key={keyword}>#{keyword}</span>)}
          {emotion.secondary_emotions.map((item) => <span key={item}>混合·{item}</span>)}
        </div>
        {emotion.safety_level === "concern" && (
          <div className="safetyNotice">你不必独自承受。如果有即时危险，请先联系身边可信任的人或当地紧急援助。</div>
        )}
        {error && <div className="errorMessage" role="alert">{error}</div>}
        <button className="primaryButton" onClick={onMatch} disabled={loading}>
          {loading ? <><span className="miniSpinner" />正在进入人群</> : <>寻找同频的人 <span>↗</span></>}
        </button>
        <div className="providerTag">由 {emotion.provider === "demo" ? "VibeChat 演示引擎" : emotion.provider} 分析</div>
      </div>
    </div>
  );
}

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div className="meter">
      <div><span>{label}</span><b>{value}</b></div>
      <div className="meterTrack"><span style={{ width: `${value}%` }} /></div>
    </div>
  );
}

function MatchingPanel({
  emotion,
  alias,
  waited,
  demoAvailable,
  loading,
  onCancel,
  onDemo,
}: {
  emotion: EmotionResult;
  alias: string;
  waited: number;
  demoAvailable: boolean;
  loading: boolean;
  onCancel: () => void;
  onDemo: () => void;
}) {
  const meta = emotionMeta[emotion.primary_emotion] || emotionMeta["复杂"];
  return (
    <div className="matchingPanel" style={{ "--emotion-color": meta.color } as React.CSSProperties}>
      <div className="radar" aria-hidden="true">
        <span className="radarRing ringOne" />
        <span className="radarRing ringTwo" />
        <span className="radarRing ringThree" />
        <span className="radarCore">{meta.glyph}</span>
        <span className="floatingDot dotOne" />
        <span className="floatingDot dotTwo" />
        <span className="floatingDot dotThree" />
      </div>
      <div className="eyebrow centered"><span /> SEARCHING THE SAME FREQUENCY</div>
      <h2>正在寻找同频的人</h2>
      <p>我们正从此刻在线的人中，寻找同样带着<strong>{emotion.primary_emotion}</strong>、情绪节奏接近的你们。</p>
      <div className="waitingMeta">
        <span>你的匿名身份 <b>{alias}</b></span>
        <span>已等待 <b>{waited}s</b></span>
      </div>
      {demoAvailable && (
        <button className="secondaryButton" onClick={onDemo} disabled={loading}>
          {loading ? "正在连接…" : "先和飞行雪绒聊聊"}
        </button>
      )}
      <button className="textButton cancelButton" onClick={onCancel}>退出匹配</button>
    </div>
  );
}

function ChatPanel({
  atmosphereMode,
  match,
  emotion,
  onLeave,
  onReceiveSound,
  onSendSound,
}: {
  atmosphereMode: AtmosphereMode;
  match: MatchStatus;
  emotion: EmotionResult | null;
  onLeave: () => void;
  onReceiveSound: () => void;
  onSendSound: () => void;
}) {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [connection, setConnection] = useState<"connecting" | "online" | "offline">("connecting");
  const [error, setError] = useState("");
  const [speakingMessageId, setSpeakingMessageId] = useState<string | null>(null);
  const [speechSupported, setSpeechSupported] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const activeSpeechIdRef = useRef<string | null>(null);
  const speechAudioRef = useRef<HTMLAudioElement | null>(null);
  const speechAudioUrlRef = useRef<string | null>(null);
  const messagesRef = useRef<Message[]>([]);
  const receivedInitialMessagesRef = useRef(false);
  const receiveSoundRef = useRef(onReceiveSound);
  const shouldStickToBottomRef = useRef(true);
  const setSyncedMessages = useCallback((updater: Message[] | ((current: Message[]) => Message[])) => {
    setMessages((current) => {
      const next = typeof updater === "function"
        ? (updater as (value: Message[]) => Message[])(current)
        : updater;
      messagesRef.current = next;
      return next;
    });
  }, []);
  const isNearBottom = useCallback(() => {
    const list = listRef.current;
    if (!list) return true;
    return list.scrollHeight - list.scrollTop - list.clientHeight < 120;
  }, []);
  const selfAlias = conversation?.self_alias || match.alias || "我";

  useEffect(() => {
    receiveSoundRef.current = onReceiveSound;
  }, [onReceiveSound]);

  useEffect(() => {
    if (TTS_API_URL) setSpeechSupported(true);
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const loadVoices = () => setSpeechSupported(true);
    window.speechSynthesis.addEventListener?.("voiceschanged", loadVoices);
    loadVoices();
    return () => {
      window.speechSynthesis.cancel();
      speechAudioRef.current?.pause();
      if (speechAudioUrlRef.current) URL.revokeObjectURL(speechAudioUrlRef.current);
      window.speechSynthesis.removeEventListener?.("voiceschanged", loadVoices);
    };
  }, []);

  useEffect(() => {
    if (!match.conversation_id || !match.access_token) return;
    let disposed = false;
    const token = encodeURIComponent(match.access_token);
    let restAvailable = false;
    receivedInitialMessagesRef.current = false;
    const refreshConversation = () => fetch(`${CHAT_API_URL}/api/conversations/${match.conversation_id}?access_token=${token}`)
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(apiErrorMessage(payload, "无法进入这段对话"));
        if (!disposed) {
          restAvailable = true;
          setConnection((current) => current === "online" ? current : "online");
          setConversation((current) => sameConversation(current, payload) ? current : payload);
          if (
            receivedInitialMessagesRef.current &&
            hasNewIncomingMessage(messagesRef.current, payload.messages, selfAlias)
          ) {
            receiveSoundRef.current();
          }
          receivedInitialMessagesRef.current = true;
          const mergedMessages = mergeConfirmedMessages(messagesRef.current, payload.messages);
          messagesRef.current = mergedMessages;
          setSyncedMessages((current) => sameMessageList(current, mergedMessages) ? current : mergedMessages);
        }
      })
      .catch((reason) => !disposed && setError(reason.message));

    refreshConversation();
    const poller = window.setInterval(refreshConversation, 1500);

    const socket = new WebSocket(`${websocketBaseUrl()}/ws/conversations/${match.conversation_id}?token=${token}`);
    socketRef.current = socket;
    socket.onopen = () => !disposed && setConnection("online");
    socket.onclose = () => !disposed && !restAvailable && setConnection("offline");
    socket.onerror = () => !disposed && !restAvailable && setConnection("offline");
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "message") {
        const incoming = payload.message as Message;
        shouldStickToBottomRef.current = shouldStickToBottomRef.current || isNearBottom();
        if (!messagesRef.current.some((item) => item.id === incoming.id)) {
          if (incoming.sender_alias !== selfAlias) receiveSoundRef.current();
          messagesRef.current = mergeIncomingMessage(messagesRef.current, incoming);
        }
        setSyncedMessages((current) => mergeIncomingMessage(current, incoming));
      }
    };
    return () => {
      disposed = true;
      window.clearInterval(poller);
      socket.close();
    };
  }, [isNearBottom, match.access_token, match.conversation_id, selfAlias, setSyncedMessages]);

  useEffect(() => {
    if (!shouldStickToBottomRef.current) return;
    const list = listRef.current;
    if (list) {
      list.scrollTop = list.scrollHeight;
    } else {
      endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
    shouldStickToBottomRef.current = isNearBottom();
  }, [isNearBottom, messages]);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const content = draft.trim();
    if (!content || !match.conversation_id || !match.access_token || connection !== "online") return;
    const optimisticMessage: Message = {
      id: `local-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      sender_alias: selfAlias,
      content,
      created_at: new Date().toISOString(),
      pending: true,
    };
    setDraft("");
    shouldStickToBottomRef.current = true;
    messagesRef.current = [...messagesRef.current, optimisticMessage];
    setSyncedMessages((current) => [...current, optimisticMessage]);
    onSendSound();
    try {
      const response = await fetch(
        `${CHAT_API_URL}/api/conversations/${match.conversation_id}/messages?access_token=${encodeURIComponent(match.access_token)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
        },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(apiErrorMessage(payload, "消息发送失败"));
      shouldStickToBottomRef.current = true;
      messagesRef.current = mergeIncomingMessage(messagesRef.current, payload);
      setSyncedMessages((current) => mergeIncomingMessage(current, payload));
    } catch (reason) {
      setDraft(content);
      messagesRef.current = messagesRef.current.filter((message) => message.id !== optimisticMessage.id);
      setSyncedMessages((current) => current.filter((message) => message.id !== optimisticMessage.id));
      setError(reason instanceof Error ? reason.message : "消息发送失败");
    }
  };

  const stopGuideSpeech = () => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    speechAudioRef.current?.pause();
    speechAudioRef.current = null;
    if (speechAudioUrlRef.current) {
      URL.revokeObjectURL(speechAudioUrlRef.current);
      speechAudioUrlRef.current = null;
    }
    activeSpeechIdRef.current = null;
    setSpeakingMessageId(null);
  };

  const playBrowserGuideSpeech = (message: Message) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return false;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(message.content);
    utterance.lang = "zh-CN";
    utterance.rate = 0.86;
    utterance.pitch = 1.18;
    utterance.volume = 0.92;
    const voice = guideSpeechVoice();
    if (voice) utterance.voice = voice;
    const clearBrowserSpeech = () => {
      if (activeSpeechIdRef.current === message.id) activeSpeechIdRef.current = null;
      setSpeakingMessageId((current) => current === message.id ? null : current);
    };
    utterance.onend = clearBrowserSpeech;
    utterance.onerror = clearBrowserSpeech;
    window.speechSynthesis.speak(utterance);
    return true;
  };

  const playExternalGuideSpeech = async (message: Message) => {
    const endpoint = ttsEndpoint();
    if (!endpoint) return false;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: message.content,
        speaker: "飞行雪绒",
        lang: "zh-CN",
        text_lang: "zh",
        ref_audio_path: TTS_REF_AUDIO_PATH,
        prompt_text: TTS_PROMPT_TEXT,
        prompt_lang: "zh",
        text_split_method: "cut5",
        batch_size: 1,
        media_type: "wav",
        streaming_mode: false,
      }),
    });
    if (!response.ok) throw new Error("本地 TTS 暂时没有回应");
    const contentType = response.headers.get("content-type") || "";
    let audioUrl = "";
    if (contentType.includes("application/json")) {
      const payload = await response.json();
      audioUrl = payload.audio_url || payload.audioUrl || payload.url || "";
      if (audioUrl && endpoint.startsWith("http") && audioUrl.startsWith("/")) {
        audioUrl = new URL(audioUrl, endpoint).toString();
      }
    } else {
      const blob = await response.blob();
      audioUrl = URL.createObjectURL(blob);
      speechAudioUrlRef.current = audioUrl;
    }
    if (!audioUrl) throw new Error("本地 TTS 没有返回音频");
    const audio = new Audio(audioUrl);
    speechAudioRef.current = audio;
    audio.onended = () => stopGuideSpeech();
    audio.onerror = () => stopGuideSpeech();
    await audio.play();
    return true;
  };

  const speakGuideMessage = (message: Message) => {
    if (speakingMessageId === message.id) {
      stopGuideSpeech();
      return;
    }
    stopGuideSpeech();
    activeSpeechIdRef.current = message.id;
    setSpeakingMessageId(message.id);
    void playExternalGuideSpeech(message)
      .then((played) => {
        if (activeSpeechIdRef.current !== message.id) return;
        if (!played && !playBrowserGuideSpeech(message)) stopGuideSpeech();
      })
      .catch(() => {
        if (activeSpeechIdRef.current !== message.id) return;
        if (!playBrowserGuideSpeech(message)) stopGuideSpeech();
      });
  };

  const score = Math.round((match.match_score || conversation?.match_score || 0) * 100);
  const guideEmotion = emotion?.primary_emotion || "复杂";
  const partnerIsGuide = Boolean(conversation?.partner_is_demo ?? match.partner_is_demo);
  return (
    <div className="chatLayout">
      <aside className="chatAside">
        <button className="textButton" onClick={onLeave}>← 结束对话</button>
        <div className="connectionPortrait"><span>{score}</span><small>%</small></div>
        <span className="tinyLabel">同频指数</span>
        <h2>{score}%</h2>
        <p>{match.match_reason || conversation?.match_reason}</p>
        <div className="identityCard">
          <span className="avatar selfAvatar">你</span>
          <div><small>你的匿名身份</small><b>{selfAlias}</b></div>
        </div>
        <p className="chatSafety">不交换隐私，也不急着给建议。先好好听见彼此。</p>
      </aside>
      <section className="chatRoom">
        <header className="chatHeader">
          <div className="partnerIdentity">
            {partnerIsGuide ? (
              <GuideAvatar emotion={guideEmotion} size="lg" />
            ) : (
              <span className="avatar">{(match.partner_alias || "同").slice(0, 1)}</span>
            )}
            <div><b>{match.partner_alias || "同频的人"}</b><span><i className={`connectionDot ${connection}`} />{(conversation?.partner_is_demo ?? match.partner_is_demo) ? "飞行雪绒 · 自动回复" : connection === "online" ? "真人伙伴 · 等待回复" : connection === "connecting" ? "正在连接" : "连接已断开"}</span></div>
          </div>
          <span className="anonymousBadge">匿名会话</span>
        </header>
        <div className="messageList" ref={listRef} aria-live="polite">
          <AtmosphereLayer mode={atmosphereMode} mood={guideEmotion} variant="panel" />
          <div className="systemMessage"><span>✦</span> 你们因为相近的情绪频率来到这里<br /><small>不用急着表现，做此刻的自己就好</small></div>
          {messages.map((message) => {
            const mine = message.sender_alias === selfAlias;
            const guideMessage = partnerIsGuide && !mine;
            return (
              <div className={`messageRow ${mine ? "mine" : "theirs"} ${message.pending ? "pending" : ""}`} key={message.id}>
                {!mine && (
                  guideMessage ? (
                    <GuideAvatar emotion={guideEmotion} size="sm" />
                  ) : (
                    <span className="avatar messageAvatar">{message.sender_alias.slice(0, 1)}</span>
                  )
                )}
                <div>
                  <div className="messageBubble">{message.content}</div>
                  <div className="messageMeta">
                    <time>{message.pending ? "发送中" : new Date(message.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time>
                    {guideMessage && (
                      <button
                        aria-pressed={speakingMessageId === message.id}
                        className={`speechButton ${speakingMessageId === message.id ? "active" : ""}`}
                        disabled={!speechSupported}
                        onClick={() => speakGuideMessage(message)}
                        title={speechSupported ? "用飞行雪绒原创声线朗读" : "当前浏览器不支持朗读"}
                        type="button"
                      >
                        <span>{speakingMessageId === message.id ? "停止" : "朗读"}</span>
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          {error && <div className="errorMessage" role="alert">{error}</div>}
          <div ref={endRef} />
        </div>
        <form className="messageComposer" onSubmit={send}>
          <label className="srOnly" htmlFor="message">发送消息</label>
          <input
            id="message"
            value={draft}
            onChange={(event) => setDraft(event.target.value.slice(0, 1000))}
            placeholder={connection === "online" ? "从一句“我懂”开始……" : "等待连接恢复"}
            disabled={connection !== "online"}
            autoComplete="off"
          />
          <button type="submit" disabled={!draft.trim() || connection !== "online"} aria-label="发送消息">↑</button>
        </form>
      </section>
      <aside className="chatGuide">
        <div className="guideBlock">
          <span className="tinyLabel">今日同频话题</span>
          {topicCards.map((topic, index) => (
            <div className="topicItem" key={topic.title}>
              <b>{index + 1}</b>
              <div><strong>{topic.title}</strong><span>{topic.meta}</span></div>
            </div>
          ))}
        </div>
        <div className="guideBlock">
          <span className="tinyLabel">破冰提示</span>
          {guideTips.map((tip) => <button type="button" key={tip}>{tip}</button>)}
        </div>
      </aside>
    </div>
  );
}
