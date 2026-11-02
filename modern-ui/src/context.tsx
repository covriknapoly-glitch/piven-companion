import { useEffect, useState } from "react";
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

/** How much of the model's context window the current chat fills, and what it is made of. */
export function ContextTab({ api, state }: { api: WebApi; state: EngineState }) {
  const [usage, setUsage] = useState<ContextUsage | null>(null);
  // Counted again when the chat, its length, the model or the busy state changes (a finished answer lengthens it).
  useEffect(() => {
    let stale = false;
    void api.context_usage().then((reply) => { if (!stale && reply.ok) setUsage(reply); });
    return () => { stale = true; };
  }, [api, state.activeChatId, state.items.length, state.busy, state.settings.model]);

  if (!usage) return <div className="workspace-slot context-tab"><Decor corner="br" /></div>;
  if (!usage.model) return <div className="workspace-slot context-tab"><Decor corner="br" /><p className="pane-note">Модель не выбрана</p></div>;

  const limit = usage.limit;
  const share = limit ? usage.used / limit : 0;
  const level = share > 0.9 ? "full" : share > usage.historyShare ? "high" : "";
  const histBudget = Math.round(limit * usage.historyShare);
  return (
    <div className="workspace-slot context-tab">
      <Decor corner="br" />
      <div className="context-total">
        <strong className={level}>{limit ? `${Math.min(999, Math.round(share * 100))}%` : count(usage.used)}</strong>
        <span>{limit ? <>{count(usage.used)} <small>из</small> {count(limit)} <small>токенов</small></> : <small>токенов в этом чате</small>}</span>
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
            <span>{part.label}{part.key === "history" && usage.turns > 0 && <small> · {usage.turns}</small>}{part.key === "images" && usage.images > 0 && <small> · {usage.images}</small>}{part.key === "tools" && usage.toolCount > 0 && <small> · {usage.toolCount}</small>}</span>
            <em>{count(usage.parts[part.key])}</em>
          </li>
        ))}
      </ul>
      {limit > 0 && (
        <p className="pane-note">{usage.compress
          ? `Окно модели — ${count(limit)} токенов. Когда переписка займёт ${count(histBudget)}, старые сообщения сожмутся в краткое содержание; вторая половина окна остаётся для ответа.`
          : `Окно модели — ${count(limit)} токенов. Когда переписка займёт ${count(histBudget)}, старые сообщения перестанут отправляться модели; вторая половина окна остаётся для ответа.`}</p>
      )}
      {usage.cloud && <p className="pane-note">Размер окна у облачной модели задаёт сервис, поэтому здесь только размер чата.</p>}
      {usage.serversWaiting.length > 0 && <p className="pane-note">{`Серверы MCP ещё не запущены, их инструменты появятся здесь после первого ответа: ${usage.serversWaiting.join(", ")}`}</p>}
      <p className="pane-note">Это оценка, около трёх символов на токен. Точное число знает только сама модель. Сведения из долговременной памяти добавляются при каждом ответе и сюда не входят. Навыки и инструменты посчитаны для обычного ответа; при выключенных инструментах они не отправляются.</p>
    </div>
  );
}
