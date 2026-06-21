"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

type Phase = "input" | "result" | "matching" | "chat";

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
};

type Message = {
  id: string;
  sender_alias: string;
  content: string;
  created_at: string;
};

type Conversation = {
  id: string;
  self_alias: string;
  partner_alias: string;
  match_score: number;
  match_reason: string;
  messages: Message[];
};

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === "production" ? "/_/backend" : "http://localhost:8000")
).replace(/\/$/, "");

function websocketBaseUrl() {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL.replace(/\/$/, "");
  }
  if (API_URL.startsWith("/") && typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}${API_URL}`;
  }
  return API_URL.replace(/^http/, "ws");
}

const examples = [
  "比赛快开始了，我既期待又有点紧张",
  "忙完一天，突然很想找个人安静聊聊",
  "今天有件小事让我开心了很久",
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

function apiErrorMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export default function Home() {
  const [phase, setPhase] = useState<Phase>("input");
  const [text, setText] = useState("");
  const [emotion, setEmotion] = useState<EmotionResult | null>(null);
  const [ticket, setTicket] = useState<MatchTicket | null>(null);
  const [match, setMatch] = useState<MatchStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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
      const response = await fetch(`${API_URL}/api/matches/join`, {
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
        `${API_URL}/api/matches/${ticket.ticket_id}?access_token=${encodeURIComponent(ticket.access_token)}`,
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
        `${API_URL}/api/matches/${ticket.ticket_id}/demo?access_token=${encodeURIComponent(ticket.access_token)}`,
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
        `${API_URL}/api/matches/${ticket.ticket_id}/cancel?access_token=${encodeURIComponent(ticket.access_token)}`,
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
      <div className="ambient ambientOne" />
      <div className="ambient ambientTwo" />
      <header className="siteHeader">
        <button className="brand" onClick={reset} aria-label="返回 VibeChat 首页">
          <span className="brandMark"><span /></span>
          <span>VibeChat</span>
        </button>
        <div className="privacyPill"><span className="statusDot" />匿名 · 安全 · 此刻</div>
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
          <ChatPanel match={match} onLeave={reset} />
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
      </div>

      <form className="inputCard" onSubmit={analyze}>
        <div className="cardTopline">
          <span>此刻，你感觉如何？</span>
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
            <button type="button" key={example} onClick={() => setText(example)}>{index + 1}</button>
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
        <div className="eyebrow"><span /> EMOTION READOUT</div>
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
          {loading ? "正在连接…" : "先和同频向导聊聊"}
        </button>
      )}
      <button className="textButton cancelButton" onClick={onCancel}>退出匹配</button>
    </div>
  );
}

function ChatPanel({ match, onLeave }: { match: MatchStatus; onLeave: () => void }) {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [connection, setConnection] = useState<"connecting" | "online" | "offline">("connecting");
  const [error, setError] = useState("");
  const socketRef = useRef<WebSocket | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!match.conversation_id || !match.access_token) return;
    let disposed = false;
    const token = encodeURIComponent(match.access_token);
    fetch(`${API_URL}/api/conversations/${match.conversation_id}?access_token=${token}`)
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(apiErrorMessage(payload, "无法进入这段对话"));
        if (!disposed) {
          setConversation(payload);
          setMessages(payload.messages);
        }
      })
      .catch((reason) => !disposed && setError(reason.message));

    const socket = new WebSocket(`${websocketBaseUrl()}/ws/conversations/${match.conversation_id}?token=${token}`);
    socketRef.current = socket;
    socket.onopen = () => !disposed && setConnection("online");
    socket.onclose = () => !disposed && setConnection("offline");
    socket.onerror = () => !disposed && setConnection("offline");
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "message") {
        setMessages((current) => current.some((item) => item.id === payload.message.id) ? current : [...current, payload.message]);
      }
    };
    return () => {
      disposed = true;
      socket.close();
    };
  }, [match.access_token, match.conversation_id]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = (event: FormEvent) => {
    event.preventDefault();
    const content = draft.trim();
    if (!content || socketRef.current?.readyState !== WebSocket.OPEN) return;
    socketRef.current.send(JSON.stringify({ type: "message", content }));
    setDraft("");
  };

  const score = Math.round((match.match_score || conversation?.match_score || 0) * 100);
  const selfAlias = conversation?.self_alias || match.alias || "我";
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
            <span className="avatar">{(match.partner_alias || "同").slice(0, 1)}</span>
            <div><b>{match.partner_alias || "同频的人"}</b><span><i className={`connectionDot ${connection}`} />{connection === "online" ? "此刻在线" : connection === "connecting" ? "正在连接" : "连接已断开"}</span></div>
          </div>
          <span className="anonymousBadge">匿名会话</span>
        </header>
        <div className="messageList" aria-live="polite">
          <div className="systemMessage"><span>✦</span> 你们因为相近的情绪频率来到这里<br /><small>不用急着表现，做此刻的自己就好</small></div>
          {messages.map((message) => {
            const mine = message.sender_alias === selfAlias;
            return (
              <div className={`messageRow ${mine ? "mine" : "theirs"}`} key={message.id}>
                {!mine && <span className="avatar messageAvatar">{message.sender_alias.slice(0, 1)}</span>}
                <div>
                  <div className="messageBubble">{message.content}</div>
                  <time>{new Date(message.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time>
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
    </div>
  );
}
