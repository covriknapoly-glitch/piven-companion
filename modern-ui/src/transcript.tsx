import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { ChatSummary, DialogueItem, EngineState, HfFile, WebApi } from "./bridge";
import { Attachment } from "./cards";
import { Icon } from "./icons";
import { Markdown } from "./markdown";
import { IconButton, Logo, formatElapsed } from "./ui";

const SUGGESTIONS: { label: string; text: string }[] = [
  { label: "объяснить", text: "Объясни простыми словами, как работает видеокарта" },
  { label: "нарисовать", text: "Нарисуй уютный ночной город под дождём" },
  { label: "презентация", text: "Сделай презентацию про Марс на 6 слайдов" },
  { label: "код", text: "Найди и исправь ошибку в проекте" },
  { label: "компьютер", text: "Открой проводник" },
];

interface MessageProps {
  api: WebApi;
  item: DialogueItem;
  index: number;
  model: string;
  canRetry: boolean;
  onCopy: (text: string) => void;
  onView: (path: string) => void;
  onRetry: () => void;
}

/** First launch without models: three steps and one button that downloads a model chosen for this computer. */
function Welcome({ api, state }: { api: WebApi; state: EngineState }) {
  const [pick, setPick] = useState<{ repo?: string; record?: Record<string, unknown>; tag?: string; size?: number; why?: string; error?: string } | null>(null);
  const [started, setStarted] = useState("");
  useEffect(() => { void api.recommended_model().then(setPick); }, [api]);
  const downloading = state.downloads.some((row) => row.kind === "model" && row.state === "running");
  return (
    <div className="intro welcome">
      <div className="intro-brand"><Logo size={72} /><div><strong>PIVEN</strong><span>Добро пожаловать</span></div></div>
      <p>PIVEN — помощник, который работает прямо на твоём компьютере: отвечает на вопросы, рисует, делает презентации, говорит голосом. Для начала нужна модель — «мозг» помощника.</p>
      <ol className="welcome-steps">
        <li className={downloading || started ? "done" : "current"}>
          <strong>Скачай модель</strong>
          {!pick ? <span>Подбор модели под твою видеокарту…</span>
            : pick.repo ? <span>Рекомендуем <b className="mono">{pick.tag}</b> ({((pick.size ?? 0) / 2 ** 30).toFixed(1)} ГБ) — {pick.why}.</span>
            : <span>Не удалось связаться с Hugging Face. Проверь интернет или скачай модель вручную через меню выбора модели.</span>}
          {pick?.repo && !started && !downloading && (
            <button type="button" className="btn btn-primary" onClick={() => {
              void api.hf_start(pick.repo!, (pick.record ?? {}) as unknown as HfFile, pick.tag ?? "", "").then((reply) => setStarted(reply.ok ? "ok" : reply.error ?? "Не удалось начать загрузку."));
            }}>Скачать рекомендуемую модель</button>
          )}
          {(downloading || started === "ok") && <span>Загрузка идёт — прогресс виден в панели слева. Окно можно не закрывать.</span>}
          {started && started !== "ok" && <span className="error-text">{started}</span>}
        </li>
        <li><strong>Напиши сообщение</strong><span>Внизу окна, обычными словами — как другу.</span></li>
        <li><strong>По желанию — голос</strong><span>Кнопка звонка внизу: говори вслух, помощник ответит голосом.</span></li>
      </ol>
    </div>
  );
}

/** A poll the model asked: the chosen option goes back to the model as the user's message. */
function PollCard({ api, text, index }: { api: WebApi; text: string; index: number }) {
  const poll = (() => { try { return JSON.parse(text) as { question: string; options: string[]; twitch?: boolean }; } catch { return null; } })();
  const [chosen, setChosen] = useState("");
  const openTwitch = useContext(TwitchPollContext);
  if (!poll) return null;
  return (
    <div className="msg msg-poll" id={`msg-${index}`}>
      <div className="poll-question"><Icon name="chat" size={14} /> {poll.question}</div>
      <div className="poll-options">
        {poll.options.map((option) => (
          <button key={option} type="button" className={chosen === option ? "on" : ""} disabled={Boolean(chosen)}
            onClick={() => { setChosen(option); void api.answer_poll(poll.question, option); }}>{option}</button>
        ))}
      </div>
      {poll.twitch && <button type="button" className="link-btn" onClick={() => openTwitch(poll)}><Icon name="twitch" size={13} /> Запустить этот опрос для зрителей Twitch</button>}
    </div>
  );
}

/** Opens the Twitch dialog with a poll from the chat filled in (set by App). */
export const TwitchPollContext = createContext<(poll: { question: string; options: string[] }) => void>(() => undefined);

function Message({ api, item, index, model, canRetry, onCopy, onView, onRetry }: MessageProps) {
  const attachments = item.images.length > 0 && (
    <div className="attachments">{item.images.map((path) => <Attachment key={path} api={api} path={path} onView={onView} />)}</div>
  );
  if (item.role === "poll") return <PollCard api={api} text={item.text} index={index} />;
  if (item.role === "system") {
    return <div className="msg msg-system" id={`msg-${index}`}><span className="msg-mark">#</span><p className="plain">{item.text}</p>{attachments}</div>;
  }
  if (item.role === "user" || item.role === "computer") {
    return (
      <div className="msg msg-user" id={`msg-${index}`}>
        {item.role === "computer" && <div className="msg-label"><Icon name="volume" size={13} /> звук компьютера</div>}
        {attachments}
        {item.text && <p className="plain" data-i18n-skip>{item.text}</p>}
        <div className="msg-actions">
          <IconButton icon="copy" label="Копировать" size={14} className="msg-action" onClick={() => onCopy(item.text)} />
        </div>
      </div>
    );
  }
  return (
    <div className="msg msg-assistant" id={`msg-${index}`}>
      <div className="msg-head"><Logo size={24} /><strong>piven</strong><span>{model}</span></div>
      {item.text && <Markdown text={item.text} onCopy={onCopy} />}
      {attachments}
      <div className="msg-actions">
        <IconButton icon="copy" label="Копировать ответ" size={14} className="msg-action" onClick={() => onCopy(item.text)} />
        <IconButton icon="volume" label="Озвучить" size={14} className="msg-action" onClick={() => { void api.speak(item.text); }} />
        {canRetry && <IconButton icon="retry" label="Ответить заново" size={14} className="msg-action" onClick={onRetry} />}
      </div>
    </div>
  );
}

function Working({ state, onStop }: { state: EngineState; onStop: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const elapsed = state.busySince ? Math.max(0, Math.floor(now / 1000 - state.busySince)) : 0;
  return (
    <div className="msg msg-working">
      <div className="working-line">
        <span className="spinner" aria-hidden="true" />
        <span className="activity">{state.activity || "Думает"}</span>
        <span className="elapsed">{formatElapsed(elapsed)}</span>
        <button type="button" className="text-btn" onClick={onStop}>стоп <kbd>esc</kbd></button>
      </div>
      {state.reasoning && (
        <>
          <button type="button" className="text-btn" onClick={() => setExpanded((value) => !value)}>
            <Icon name="chevronRight" size={13} className={expanded ? "rot90" : ""} /> рассуждения
          </button>
          {expanded && <pre className="reasoning">{state.reasoning.slice(-4000)}</pre>}
        </>
      )}
    </div>
  );
}

export function Transcript({ api, state, focusIndex, recent, onCopy, onView, onRetry, onStop, onPrefill, onSelectChat }:
  { api: WebApi; state: EngineState; focusIndex: { index: number; nonce: number } | null; recent: ChatSummary[];
    onCopy: (text: string) => void; onView: (path: string) => void; onRetry: () => void; onStop: () => void;
    onPrefill: (text: string) => void; onSelectChat: (chat: ChatSummary) => void }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const lastAssistant = state.items.map((item) => item.role).lastIndexOf("assistant");

  // Follow new output while the reader is at the bottom; leave them alone once they scroll up.
  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (element && stickToBottom.current) element.scrollTop = element.scrollHeight;
  }, [state.items.length, state.busy, state.activity, state.reasoning]);
  useLayoutEffect(() => {
    stickToBottom.current = true;
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [state.activeChatId]);
  useEffect(() => {
    if (!focusIndex) return;
    const element = document.getElementById(`msg-${focusIndex.index}`);
    if (!element) return;
    element.scrollIntoView({ block: "center", behavior: "smooth" });
    element.classList.remove("flash");
    void element.offsetWidth;
    element.classList.add("flash");
  }, [focusIndex]);

  let body: ReactNode;
  if (!state.models.length && !state.busy) {
    body = <Welcome api={api} state={state} />;
  } else if (!state.items.length && !state.busy) {
    body = (
      <div className="intro">
        <div className="intro-brand"><Logo size={72} /><div><strong>PIVEN</strong><span>{state.settings.model || "модель не выбрана"}</span></div></div>
        <p>Пиши обычным языком. Компаньон отвечает, рисует, собирает презентации, правит код и делает действия на компьютере.</p>
        <div className="intro-list">
          {SUGGESTIONS.map((item) => (
            <button key={item.label} type="button" onClick={() => onPrefill(item.text)}><span>{item.label}</span>{item.text}</button>
          ))}
        </div>
        {recent.length > 0 && (
          <div className="intro-list">
            <h3>Недавние</h3>
            {recent.map((chat) => <button key={chat.id} type="button" onClick={() => onSelectChat(chat)}><span>{chat.title}</span>{chat.preview}</button>)}
          </div>
        )}
      </div>
    );
  } else {
    body = (
      <>
        {state.items.map((item, index) => (
          <Message key={index} api={api} item={item} index={index} model={state.settings.model}
            canRetry={index === lastAssistant && !state.busy} onCopy={onCopy} onView={onView} onRetry={onRetry} />
        ))}
        {state.busy && <Working state={state} onStop={onStop} />}
      </>
    );
  }
  return (
    <div className="transcript" ref={scrollRef}
      onScroll={(event) => { const el = event.currentTarget; stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }}>
      <div className="transcript-inner">{body}</div>
    </div>
  );
}
