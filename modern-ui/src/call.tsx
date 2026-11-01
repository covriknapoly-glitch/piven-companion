import { useEffect, useState } from "react";
import type { EngineState, WebApi } from "./bridge";
import { Icon, type IconName } from "./icons";
import { Logo } from "./ui";

type Phase = "connecting" | "listening" | "hearing" | "thinking" | "speaking" | "muted";
const PHASE_TEXT: Record<Phase, string> = {
  connecting: "Подключается", listening: "Слушает", hearing: "Слышит тебя",
  thinking: "Думает", speaking: "Говорит", muted: "Микрофон выключен",
};

function phaseOf(state: EngineState): Phase {
  if (state.call.speaking) return "speaking";
  if (state.busy) return "thinking";
  if (/Запуск|Parakeet · CUDA/.test(state.activity)) return "connecting";
  if (state.call.muted) return "muted";
  return state.call.hearing ? "hearing" : "listening";
}

function lastLine(state: EngineState, roles: string[]) {
  const item = [...state.items].reverse().find((entry) => roles.includes(entry.role) && entry.text.trim());
  return item ? item.text.replace(/\s+/g, " ").trim() : "";
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

/** The right pane during a call: who is talking, the last lines, and phone-style buttons. */
export function CallPanel({ api, state, onError }: { api: WebApi; state: EngineState; onError: (message?: string) => void }) {
  const [startedAt] = useState(() => Date.now());
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
  const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  const phase = phaseOf(state);
  const options = state.listening.options;
  const heard = lastLine(state, ["user", "computer"]);
  const said = lastLine(state, ["assistant"]);
  const speech = state.settings.speechEnabled;

  return (
    <div className={`call-pane phase-${phase}`}>
      <header className="call-head">
        <span className="live-dot" /><strong>Звонок</strong><span className="call-clock">{clock}</span>
      </header>

      <div className="call-stage">
        <div className="call-avatar">
          <i className="ring r1" /><i className="ring r2" /><i className="ring r3" />
          <Logo size={96} />
        </div>
        <div className="call-name">PIVEN</div>
        <div className="call-phase">{PHASE_TEXT[phase]}{phase === "thinking" && <span className="call-dots"><i /><i /><i /></span>}</div>
        <div className="call-bars" aria-hidden="true">{Array.from({ length: 7 }, (_, index) => <i key={index} style={{ animationDelay: `${index * 0.11}s` }} />)}</div>
      </div>

      <div className="call-lines">
        {heard && <p><small>Ты</small>{heard}</p>}
        {said && <p><small>PIVEN</small>{said}</p>}
      </div>

      <div className="call-keys">
        <CallKey icon="mic" label={state.call.muted ? "Включить" : "Микрофон"} off={state.call.muted} disabled={!options.mic}
          onClick={() => { void api.set_mic_muted(!state.call.muted); }} />
        <CallKey icon="volume" label={speech ? "Голос" : "Без голоса"} off={!speech}
          onClick={() => { void api.update_settings({ speechEnabled: !speech }).then(() => onError()); }} />
        <CallKey icon="stop" label="Перебить" disabled={!state.call.speaking && !state.busy}
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
