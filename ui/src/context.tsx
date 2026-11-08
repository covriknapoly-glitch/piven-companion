import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ContextUsage, EngineState, WebApi } from "./bridge";
import { Decor } from "./ui";

const PARTS: { key: keyof ContextUsage["parts"]; label: string }[] = [
  { key: "system", label: "Инструкция" },
  { key: "summary", label: "Краткое содержание" },
  { key: "skills", label: "Навыки" },
  { key: "tools", label: "Инструменты" },
  { key: "history", label: "Сообщения" },
  { key: "images", label: "Картинки" },
];

const count = (value: number) => Math.round(value).toLocaleString("ru-RU").replace(/ /g, " ");

let currentDraft = "";
const draftListeners = new Set<(text: string) => void>();

export function publishDraft(text: string) {
  if (text === currentDraft) return;
  currentDraft = text;
  draftListeners.forEach((listener) => listener(text));
}

const PLACEHOLDER: ContextUsage = {
  ok: true, model: "-", cloud: false, exact: true, used: 1000, limit: 16384, turns: 0, images: 0, toolCount: 0, serversWaiting: [],
  parts: { system: 1000, summary: 1000, skills: 1000, tools: 1000, history: 1000, images: 1000 },
  historyShare: 0.5, compress: true,
};
let lastUsage = PLACEHOLDER;

const Line = ({ children }: { children: ReactNode }) => <span className="ctx-text">{children}</span>;

function useContextUsage(api: WebApi, state: EngineState, every: number) {
  const [loaded, setUsage] = useState<ContextUsage | null>(null);
  const [failed, setFailed] = useState(false);
  const [draft, setDraft] = useState(currentDraft);

  useEffect(() => {
    draftListeners.add(setDraft);
    return () => { draftListeners.delete(setDraft); };
  }, []);

  useEffect(() => {
    setUsage(null);
    setFailed(false);
  }, [state.activeChatId, state.settings.model]);

  useEffect(() => {
    let stale = false;
    let waiting = false;
    const load = () => {
      if (waiting) return;
      waiting = true;
      void api.context_usage(draft).then((reply) => {
        waiting = false;
        if (stale) return;
        if (reply.ok) setUsage(reply);
        setFailed(!reply.ok);
      }).catch(() => {
        waiting = false;
        if (!stale) setFailed(true);
      });
    };
    const first = window.setTimeout(load, 150);
    const timer = state.busy ? window.setInterval(load, every) : 0;
    return () => { stale = true; window.clearTimeout(first); window.clearInterval(timer); };
  }, [api, draft, every, state.activeChatId, state.items.length, state.busy, state.settings.model]);

  return { loaded, failed };
}

/** A small ring beside the chat: how full the model's window is. A click opens the details. */
export function ContextRing({ api, state, onOpen }: { api: WebApi; state: EngineState; onOpen: () => void }) {
  const { loaded } = useContextUsage(api, state, 3000);
  const seen = useRef<ContextUsage | null>(null);
  if (loaded) seen.current = loaded;
  const usage = loaded ?? seen.current;
  if (!state.settings.model || !usage || !usage.limit) return null;
  const share = loaded ? Math.min(loaded.used / loaded.limit, 1) : 0;
  const level = share > 0.9 ? "full" : share > usage.historyShare ? "high" : "";
  const percent = share < 0.1 ? (share * 100).toFixed(1) : String(Math.round(share * 100));
  const radius = 8;
  const length = 2 * Math.PI * radius;
  const label = loaded ? `Контекст: ${percent}% (${count(loaded.used)} из ${count(loaded.limit)} токенов)` : "Контекст: считаем…";
  return (
    <button type="button" className={`context-ring ${level}`} aria-label={label} title={label} onClick={onOpen}>
      <svg viewBox="0 0 22 22" width="22" height="22" aria-hidden="true">
        <circle className="ring-track" cx="11" cy="11" r={radius} />
        <circle className="ring-fill" cx="11" cy="11" r={radius} strokeDasharray={`${share * length} ${length}`} transform="rotate(-90 11 11)" />
      </svg>
      <span>{loaded ? `${Math.round(share * 100)}%` : "0%"}</span>
    </button>
  );
}

export function ContextTab({ api, state }: { api: WebApi; state: EngineState }) {
  const { loaded, failed } = useContextUsage(api, state, 1000);

  if (!loaded && failed) return <div className="workspace-slot context-tab"><Decor corner="br" /><p className="pane-note">Не удалось посчитать контекст</p></div>;
  if (!state.settings.model || (loaded && !loaded.model)) return <div className="workspace-slot context-tab"><Decor corner="br" /><p className="pane-note">Модель не выбрана</p></div>;
  if (loaded) lastUsage = loaded;

  const usage = loaded ?? lastUsage;
  const limit = usage.limit;
  const share = limit ? usage.used / limit : 0;
  const level = share > 0.9 ? "full" : share > usage.historyShare ? "high" : "";
  const histBudget = Math.round(limit * usage.historyShare);
  return (
    <div className={`workspace-slot context-tab ${loaded ? "" : "context-loading"}`} aria-hidden={loaded ? undefined : true}>
      <Decor corner="br" />
      <div className="context-total">
        <strong className={level}><Line>{limit ? `${share < 0.1 ? (share * 100).toFixed(1) : Math.min(999, Math.round(share * 100))}%` : count(usage.used)}</Line></strong>
        <span><Line>{limit ? <>{count(usage.used)} <small>из</small> {count(limit)} <small>токенов</small></> : <small>токенов в этом чате</small>}</Line></span>
      </div>
      <div className="context-bar" role="img" aria-label="Заполненность контекста">
        {PARTS.map((part) => usage.parts[part.key] > 0 && (
          <i key={part.key} className={`ctx-${part.key}`} style={{ width: `${(usage.parts[part.key] / Math.max(limit || usage.used, 1)) * 100}%` }} />
        ))}
        {limit > 0 && <b style={{ left: `${usage.historyShare * 100}%` }} />}
      </div>
      <ul className="context-legend">
        {PARTS.map((part) => (
          <li key={part.key} className={usage.parts[part.key] ? "" : "zero"}>
            <i className={`ctx-${part.key}`} />
            <span><Line>{part.label}{part.key === "history" && usage.turns > 0 && <small> · {usage.turns}</small>}{part.key === "images" && usage.images > 0 && <small> · {usage.images}</small>}{part.key === "tools" && usage.toolCount > 0 && <small> · {usage.toolCount}</small>}</Line></span>
            <em><Line>{count(usage.parts[part.key])}</Line></em>
          </li>
        ))}
      </ul>
      {limit > 0 && (
        <p className="pane-note"><Line>{usage.compress
          ? `Окно модели — ${count(limit)} токенов. Когда переписка займёт ${count(histBudget)}, старые сообщения сожмутся в краткое содержание; вторая половина окна остаётся для ответа.`
          : `Окно модели — ${count(limit)} токенов. Когда переписка займёт ${count(histBudget)}, старые сообщения перестанут отправляться модели; вторая половина окна остаётся для ответа.`}</Line></p>
      )}
      {usage.cloud && <p className="pane-note"><Line>Размер окна у облачной модели задаёт сервис, поэтому здесь только размер чата.</Line></p>}
      {usage.serversWaiting.length > 0 && <p className="pane-note"><Line>{`Серверы MCP ещё не запущены, их инструменты появятся здесь после первого ответа: ${usage.serversWaiting.join(", ")}`}</Line></p>}
      <p className="pane-note"><Line>{usage.exact ? "Текст посчитан самой моделью. Инструменты указаны с небольшим запасом: модель получает их в более короткой записи." : usage.cloud ? "Это оценка: облачная модель не сообщает точное число." : "Это оценка: точный подсчёт сейчас недоступен."}</Line></p>
      <p className="pane-note"><Line>Сведения из долговременной памяти добавляются при каждом ответе и сюда не входят. Навыки и инструменты посчитаны для обычного ответа; при выключенных инструментах они не отправляются.</Line></p>
    </div>
  );
}
