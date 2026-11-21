import { useEffect, useRef, useState, type CSSProperties } from "react";
import { isPhone, type CallLive, type EngineState, type WebApi } from "./bridge";
import { Icon, type IconName } from "./icons";
import { Decor } from "./ui";

type Phase = "connecting" | "listening" | "hearing" | "thinking" | "speaking" | "muted";
const PHASE_TEXT: Record<Phase, string> = {
  connecting: "Подключается", listening: "Слушает", hearing: "Слышит тебя",
  thinking: "Думает", speaking: "Говорит", muted: "Микрофон выключен",
};
const BARS = 9;
const QUIET: CallLive = { level: 0, voice: 0, heard: "", said: "", saying: "", speaking: false };

function phaseOf(state: EngineState, live: CallLive): Phase {
  if (state.call.speaking || live.speaking) return "speaking";
  if (state.busy) return "thinking";
  if (/Запуск|Parakeet · CUDA/.test(state.activity)) return "connecting";
  if (state.call.muted) return "muted";
  return state.call.hearing ? "hearing" : "listening";
}

/** The microphone level and the words of both sides, asked for ten times a second while the call is open. */
function useCallLive(api: WebApi) {
  const [live, setLive] = useState<CallLive>(QUIET);
  useEffect(() => {
    if (isPhone) return;
    let alive = true;
    let timer = 0;
    const tick = () => {
      void api.call_live().then((next) => { if (alive) setLive(next); }).catch(() => {}).finally(() => { if (alive) timer = window.setTimeout(tick, 100); });
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [api]);
  return live;
}

function CallKey({ icon, label, on = false, off = false, disabled = false, onClick }:
  { icon: IconName; label: string; on?: boolean; off?: boolean; disabled?: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`call-key ${on ? "on" : ""} ${off ? "off" : ""}`} disabled={disabled} onClick={onClick} aria-pressed={on || off}>
      <span className="call-key-face"><Icon name={icon} size={22} /></span>
      <span className="call-key-label">{label}</span>
    </button>
  );
}

interface Line { who: "you" | "piven" | "pc"; text: string; live?: boolean; spoken?: string }

export function CallPanel({ api, state, onError }: { api: WebApi; state: EngineState; onError: (message?: string) => void }) {
  const [startedAt] = useState(() => Date.now());
  const [firstItem] = useState(() => state.items.length);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  const live = useCallLive(api);
  const phase = phaseOf(state, live);
  const options = state.listening.options;
  const speech = state.settings.speechEnabled;

  // The bars follow whoever is talking: PIVEN's voice while it speaks, the microphone otherwise.
  const [levels, setLevels] = useState<number[]>(() => Array(BARS).fill(0));
  const current = phase === "speaking" ? live.voice : phase === "muted" ? 0 : live.level;
  useEffect(() => { setLevels((list) => [...list.slice(1), current]); }, [live]);

  // What was said in this call, oldest first; PIVEN's line grows as it speaks, the user's as the words are recognised.
  const lines: Line[] = state.items.slice(firstItem)
    .filter((item) => ["user", "computer", "assistant"].includes(item.role) && item.text.trim())
    .map((item) => ({ who: item.role === "assistant" ? "piven" : item.role === "computer" ? "pc" : "you", text: item.text.replace(/\s+/g, " ").trim() }));
  if (phase === "speaking" && live.said) {
    const spoken = live.saying && live.said.endsWith(live.saying) ? live.said.slice(0, -live.saying.length) : live.said;
    const line = { who: "piven" as const, text: live.said, spoken, live: true };
    if (lines.length && lines[lines.length - 1].who === "piven") lines[lines.length - 1] = line; else lines.push(line);
  }
  if ((phase === "hearing" || phase === "thinking") && live.heard && lines[lines.length - 1]?.text !== live.heard) {
    lines.push({ who: "you", text: live.heard, live: true });
  }
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => { list.current?.scrollTo({ top: list.current.scrollHeight }); }, [lines.length, live.heard, live.said]);

  return (
    <div className={`call-pane phase-${phase}`}>
      <header className="call-head">
        <span className="live-dot" /><strong>Звонок</strong><span className="call-clock">{clock}</span>
      </header>

      <div className="call-stage">
        <div className="call-avatar" style={{ "--level": Math.min(1, current * 1.4) } as CSSProperties}>
          <i className="ring r1" /><i className="ring r2" /><i className="ring r3" />
          <Decor />
        </div>
        <div className="call-name">PIVEN</div>
        <div className="call-phase" key={phase}>{PHASE_TEXT[phase]}{phase === "thinking" && <span className="call-dots"><i /><i /><i /></span>}</div>
        <div className="call-bars" aria-hidden="true">
          {levels.map((level, index) => <i key={index} style={{ transform: `scaleY(${.16 + Math.min(1, level * 1.6) * .84})` }} />)}
        </div>
      </div>

      <div className="call-lines" ref={list} aria-live="polite">
        {lines.slice(-8).map((line, index) => (
          <p key={index} className={`call-line ${line.who} ${line.live ? "live" : ""}`}>
            <small>{line.who === "piven" ? "PIVEN" : line.who === "pc" ? "Звук ПК" : "Ты"}</small>
            <span data-i18n-skip>{line.spoken !== undefined
              ? <>{line.spoken}<mark>{line.text.slice(line.spoken.length)}</mark></>
              : line.text}</span>
          </p>
        ))}
        {!lines.length && <p className="call-hint">Говори, когда будешь готов. Перебить можно в любой момент: просто начни говорить.</p>}
      </div>

      <div className="call-keys">
        <CallKey icon="mic" label={state.call.muted ? "Включить" : "Микрофон"} off={state.call.muted} disabled={!options.mic}
          onClick={() => { void api.set_mic_muted(!state.call.muted); }} />
        <CallKey icon="volume" label={speech ? "Голос" : "Без голоса"} off={!speech}
          onClick={() => { void api.update_settings({ speechEnabled: !speech }).then(() => onError()); }} />
        <CallKey icon="stop" label="Перебить" disabled={phase !== "speaking" && !state.busy}
          onClick={() => { void api.interrupt().then(() => onError()); }} />
      </div>
      <div className="call-sources">
        {[["mic", "микрофон"], ["loopback", "звук ПК"], ["screen", "экран"]].filter(([key]) => options[key as keyof typeof options]).map(([, label]) => label).join(" · ")}
      </div>
      <button type="button" className="call-end" onClick={() => { void api.stop_listening().then(() => onError()); }} aria-label="Завершить звонок" title="Завершить звонок">
        <Icon name="call" size={26} />
      </button>
    </div>
  );
}
