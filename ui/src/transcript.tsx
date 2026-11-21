import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { DialogueItem, EngineState, HfFile, WebApi } from "./bridge";
import { Attachment } from "./cards";
import { CodeCard, CodePlan, isFailedCheck, parseCard } from "./codecards";
import { Icon } from "./icons";
import { translate } from "./i18n";
import { Markdown } from "./markdown";
import { KnowledgeExcerpt } from "./knowledge";
import { ProjectStart } from "./projects";
import { Decor, IconButton, Logo, MotionPresence, formatElapsed } from "./ui";

const SUGGESTIONS: { label: string; texts: string[] }[] = [
  { label: "объяснить", texts: [
    "Объясни простыми словами, как работает видеокарта",
    "Объясни простыми словами, почему небо голубое",
    "Объясни простыми словами, как работает интернет",
    "Объясни простыми словами, что такое чёрная дыра",
    "Объясни простыми словами, откуда берётся радуга",
  ] },
  { label: "нарисовать", texts: [
    "Нарисуй уютный ночной город под дождём",
    "Нарисуй кота-космонавта на Луне",
    "Нарисуй домик в лесу зимним утром",
    "Нарисуй маяк во время шторма",
    "Нарисуй старую библиотеку с летающими книгами",
  ] },
  { label: "презентация", texts: [
    "Сделай презентацию про Марс на 6 слайдов",
    "Сделай презентацию про океаны на 5 слайдов",
    "Сделай презентацию про историю видеоигр на 8 слайдов",
    "Сделай презентацию про динозавров на 6 слайдов",
    "Сделай презентацию про Древний Рим на 7 слайдов",
  ] },
  { label: "код", texts: [
    "Найди и исправь ошибку в проекте",
    "Напиши игру «Змейка» для браузера",
    "Сделай простой калькулятор на HTML",
    "Напиши таймер Помодоро на HTML",
    "Объясни, что делает код в проекте",
  ] },
  { label: "компьютер", texts: [
    "Открой проводник",
    "Открой Блокнот",
    "Открой калькулятор",
    "Покажи, что лежит в папке «Загрузки»",
    "Создай на рабочем столе папку «Идеи»",
  ] },
];

function Suggestions({ onPrefill }: { onPrefill: (text: string) => void }) {
  const [items] = useState(() => SUGGESTIONS.map(({ label, texts }) => ({ label, text: texts[Math.floor(Math.random() * texts.length)] })));
  return (
    <div className="intro-list">
      {items.map((item) => (
        <button key={item.label} type="button" onClick={() => onPrefill(translate(item.text) ?? item.text)}><span>{item.label}</span>{item.text}</button>
      ))}
    </div>
  );
}

interface MessageProps {
  api: WebApi;
  item: DialogueItem;
  index: number;
  chatId: string;
  answered: boolean;
  pollAnswers?: string[];
  canRetry: boolean;
  canEdit: boolean;
  onCopy: (text: string) => void;
  onView: (path: string) => void;
  onRetry: () => void;
  onEdit: (index: number, text: string) => void;
  onFork?: (index: number) => void;
}

function UndoFiles({ api, index, count }: { api: WebApi; index: number; count: number }) {
  const [armed, setArmed] = useState(false);
  const [error, setError] = useState("");
  return (
    <div className="undo-files">
      <Icon name="file" size={13} />
      <span>{`Создано файлов и папок: ${count}`}</span>
      {armed
        ? <button type="button" className="link-btn danger" onClick={() => { void api.undo_files(index).then((reply) => setError(reply.ok ? "" : reply.error ?? "")); }}>Точно удалить?</button>
        : <button type="button" className="link-btn" onClick={() => setArmed(true)}><Icon name="trash" size={13} /> Отменить и удалить</button>}
      {error && <span className="error-text">{error}</span>}
    </div>
  );
}

function EditBox({ text, onSend, onCancel }: { text: string; onSend: (text: string) => void; onCancel: () => void }) {
  const [value, setValue] = useState(text);
  const send = () => { if (value.trim()) onSend(value.trim()); };
  return (
    <div className="msg-edit">
      <textarea autoFocus value={value} rows={Math.min(10, Math.max(2, value.split("\n").length))}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); }
          if (event.key === "Escape") onCancel();
        }} />
      <div className="msg-edit-foot">
        <span>Ответ на это сообщение и всё после него будет заменено.</span>
        <button type="button" className="btn" onClick={onCancel}>Отмена</button>
        <button type="button" className="btn btn-primary" disabled={!value.trim()} onClick={send}>Отправить</button>
      </div>
    </div>
  );
}

function Welcome({ api, state }: { api: WebApi; state: EngineState }) {
  const [pick, setPick] = useState<{ repo?: string; record?: Record<string, unknown>; tag?: string; size?: number; why?: string; error?: string } | null>(null);
  const [started, setStarted] = useState("");
  useEffect(() => { void api.recommended_model().then(setPick); }, [api]);
  const downloading = state.downloads.some((row) => row.kind === "model" && row.state === "running");
  return (
    <div className="intro welcome">
      <Decor corner="tr" />
      <p>Для начала нужна модель — «мозг» помощника.</p>
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

type PollOption = { label: string; description?: string; recommended?: boolean };
type PollQuestion = { question: string; multiple?: boolean; options: PollOption[] };

function parsePoll(text: string): { questions: PollQuestion[] } | null {
  try {
    const poll = JSON.parse(text);
    if (Array.isArray(poll.questions)) return poll;
    return { questions: [{ question: poll.question, options: poll.options.map((label: string) => ({ label })) }] };
  } catch {
    return null;
  }
}

function pollReplies(items: DialogueItem[]) {
  const answers = new Map<number, string[]>();
  const replies = new Set<number>();
  items.forEach((item, index) => {
    if (item.role !== "poll") return;
    const poll = parsePoll(item.text);
    const reply = items.findIndex((other, place) => place > index && other.role === "user");
    if (!poll || reply < 0) return;
    const lines = items[reply].text.split(/\r?\n/);
    if (lines.length !== poll.questions.length || !poll.questions.every((question, place) => lines[place].startsWith(`${question.question} — `))) return;
    answers.set(index, lines.map((line, place) => line.slice(poll.questions[place].question.length + 3)));
    replies.add(reply);
  });
  return { answers, replies };
}

function PollCard({ api, text, index, answered, answers }: { api: WebApi; text: string; index: number; answered: boolean; answers?: string[] }) {
  const poll = parsePoll(text);
  const [picked, setPicked] = useState<Record<number, string[]>>({});
  const [own, setOwn] = useState<Record<number, string>>({});
  const [sent, setSent] = useState(false);
  const [step, setStep] = useState(0);
  if (!poll) return null;
  const questions = poll.questions;
  const closed = sent || answered;
  const last = questions.length - 1;
  const answerTo = (at: number) => [...(picked[at] ?? []), (own[at] ?? "").trim()].filter(Boolean).join(", ");
  const next = (at: number, answer: string) => {
    if (at < last) { setStep(at + 1); return; }
    setSent(true);
    void api.answer_poll(questions.map((item, place) => [item.question, place === at ? answer : answerTo(place)]));
  };
  const choose = (item: PollQuestion, label: string) => {
    if (item.multiple) {
      setPicked((old) => {
        const chosen = old[step] ?? [];
        return { ...old, [step]: chosen.includes(label) ? chosen.filter((value) => value !== label) : [...chosen, label] };
      });
      return;
    }
    setPicked((old) => ({ ...old, [step]: [label] }));
    setOwn((old) => ({ ...old, [step]: "" }));
    next(step, label);
  };
  const item = questions[step];
  const answer = answerTo(step);
  if (closed) {
    return (
      <div className="msg msg-poll" id={`msg-${index}`}>
        <ul className="poll-summary" data-i18n-skip>
          {questions.map((question, place) => {
            const reply = answers?.[place] ?? answerTo(place);
            return <li key={place}><Icon name="chat" size={14} /> <span>{question.question}{reply && <strong>{reply}</strong>}</span></li>;
          })}
        </ul>
      </div>
    );
  }
  return (
    <div className="msg msg-poll" id={`msg-${index}`}>
      <div className="poll-block" key={step} role={item.multiple ? "group" : "radiogroup"} aria-label={item.question}>
        <div className="poll-question"><Icon name="chat" size={14} /> <span>{item.question}</span>{questions.length > 1 && <small className="poll-step">{`${step + 1} из ${questions.length}`}</small>}</div>
        <div className="poll-options">
          {item.options.map((option) => (
            <button key={option.label} type="button" className={`${item.multiple ? "many" : ""} ${(picked[step] ?? []).includes(option.label) ? "on" : ""}`}
              aria-pressed={(picked[step] ?? []).includes(option.label)} onClick={() => choose(item, option.label)}>
              <i aria-hidden="true" />
              <span><strong>{option.label}{option.recommended && <em>советую</em>}</strong>{option.description && <small>{option.description}</small>}</span>
            </button>
          ))}
        </div>
        <input className="poll-own" placeholder="Свой вариант" aria-label="Свой вариант" value={own[step] ?? ""}
          onChange={(event) => { const value = event.target.value; setOwn((old) => ({ ...old, [step]: value })); if (!item.multiple) setPicked((old) => ({ ...old, [step]: [] })); }}
          onKeyDown={(event) => { if (event.key === "Enter" && answer) { event.preventDefault(); next(step, answer); } }} />
      </div>
      {(step > 0 || item.multiple || (own[step] ?? "").trim()) && (
        <div className="poll-actions">
          {step > 0 && <button type="button" className="poll-back" onClick={() => setStep(step - 1)}>Назад</button>}
          {(item.multiple || (own[step] ?? "").trim()) && <button type="button" className="poll-send" disabled={!answer} onClick={() => next(step, answer)}>{step < last ? "Далее" : "Ответить"}</button>}
        </div>
      )}
    </div>
  );
}


const PROGRAM_NOTE = /^(Презентация готова · .+|Видео готово\.)$/;
const MESSAGE_CLOCK = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

function MessageTime({ created }: { created?: number | null }) {
  if (typeof created !== "number" || created <= 0) return null;
  const date = new Date(created * 1000);
  if (!Number.isFinite(date.getTime())) return null;
  return <time className="msg-time" dateTime={date.toISOString()} title={date.toLocaleString()}>{MESSAGE_CLOCK.format(date)}</time>;
}

function Message({ api, item, index, chatId, answered, pollAnswers, canRetry, canEdit, onCopy, onView, onRetry, onEdit, onFork }: MessageProps) {
  const [editing, setEditing] = useState(false);
  const [sourceNumber, setSourceNumber] = useState(0);
  const source = item.sources?.[sourceNumber - 1];
  const fork = onFork && <IconButton icon="branch" label="Создать ветку отсюда" size={14} className="msg-action branch-action" onClick={() => onFork(index)} />;
  const attached = [...item.images, ...(item.files ?? [])];
  const attachments = attached.length > 0 && (
    <div className="attachments">{attached.map((path) => <Attachment key={path} api={api} path={path} onView={onView} />)}</div>
  );
  if (item.role === "poll") return <PollCard api={api} text={item.text} index={index} answered={answered} answers={pollAnswers} />;
  if (item.role === "code") {
    const card = parseCard(item.text);
    return card && <div className={`msg msg-code${card.kind === "plan" ? " msg-plan" : ""}`} id={`msg-${index}`}><CodeCard api={api} card={card} index={index} onCopy={onCopy} /></div>;
  }
  if (item.role === "system" || item.role === "error") {
    return <div className={`msg msg-system ${item.role === "error" ? "msg-error" : ""}`} id={`msg-${index}`}><span className="msg-mark">#</span><p className="plain">{item.text}</p>{attachments}</div>;
  }
  if (item.role === "user" || item.role === "computer") {
    return (
      <div className="msg msg-user" id={`msg-${index}`}>
        {item.role === "computer" && <div className="msg-label"><Icon name="volume" size={13} /> звук компьютера</div>}
        {attachments}
        {editing
          ? <EditBox text={item.text} onCancel={() => setEditing(false)} onSend={(text) => { setEditing(false); onEdit(index, text); }} />
          : item.text && <p className="plain" data-i18n-skip>{item.text}</p>}
        {!editing && <div className="msg-actions">
          {item.role === "user" && canEdit && <IconButton icon="edit" label="Изменить" size={14} className="msg-action" onClick={() => setEditing(true)} />}
          <IconButton icon="copy" label="Копировать" size={14} className="msg-action" onClick={() => onCopy(item.text)} />
          {fork}
        </div>}
        <MessageTime created={item.created} />
      </div>
    );
  }
  return (
    <div className="msg msg-assistant" id={`msg-${index}`}>
      {item.text && (PROGRAM_NOTE.test(item.text) ? <p className="plain">{item.text}</p> : <Markdown text={item.text} onCopy={onCopy}
        citations={item.sources?.length ? { count: item.sources.length, open: setSourceNumber } : null} />)}
      {attachments}
      {Boolean(item.sources?.length) && <div className="knowledge-sources" aria-label="Фрагменты из базы знаний">
        {item.sources?.map((entry, i) => (
          <button key={i} type="button" className="chip-btn" title={[entry.path, entry.section].filter(Boolean).join(" · ")}
            onClick={() => setSourceNumber(i + 1)}><Icon name="file" size={13} /><span data-i18n-skip>{`[${i + 1}] ${entry.path}`}</span></button>
        ))}
      </div>}
      {item.sources?.length ? createPortal(<MotionPresence>{source && <KnowledgeExcerpt key={sourceNumber} source={source} api={api} chatId={chatId}
        index={index} number={sourceNumber} onClose={() => setSourceNumber(0)} />}</MotionPresence>, document.body) : null}
      <div className="msg-actions">
        <IconButton icon="copy" label="Копировать ответ" size={14} className="msg-action" onClick={() => onCopy(item.text)} />
        <IconButton icon="volume" label="Озвучить" size={14} className="msg-action" onClick={() => { void api.speak(item.text); }} />
        {canRetry && <IconButton icon="retry" label="Ответить заново" size={14} className="msg-action" onClick={onRetry} />}
        {fork}
        <MessageTime created={item.created} />
      </div>
      {Boolean(item.undo) && <UndoFiles api={api} index={index} count={item.undo ?? 0} />}
    </div>
  );
}

const STEP_KINDS = new Set(["read", "write", "edit", "command", "page", "note"]);
const STALLED = /^(Модель перестала отвечать|Работа остановлена после)/;

const STEP_CATEGORIES = {
  command: { icon: "keyboard", label: (count: number) => `Команд: ${count}` },
  file: { icon: "file", label: (count: number) => `Операций с файлами: ${count}` },
  page: { icon: "globe", label: (count: number) => `Проверок: ${count}` },
  failed: { icon: "alert", label: (count: number) => `Ошибок: ${count}` },
} as const;

type StepCategory = keyof typeof STEP_CATEGORIES;
type CodeStep = { index: number; category?: StepCategory };
type StepRunData = { category: StepCategory; indexes: number[] };

function StepRun({ run, focusIndex, render }: { run: StepRunData; focusIndex?: number; render: (index: number) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const { icon, label } = STEP_CATEGORIES[run.category];
  const count = run.indexes.length;
  const focused = focusIndex !== undefined && run.indexes.includes(focusIndex) ? focusIndex : undefined;
  return (
    <div className="step-run">
      {count > 1 && <button type="button" className={`step-toggle step-run-toggle${run.category === "failed" ? " failed" : ""}`} aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <Icon name="chevronRight" size={13} className="disclosure-chevron" /><Icon name={icon} size={13} /><span>{label(count)}</span>
      </button>}
      {count === 1 ? render(run.indexes[0]) : <MotionPresence kind="collapse" instant={focused !== undefined}>{(open || focused !== undefined) && <div className="step-run-list">
        {open ? run.indexes.map(render) : focused !== undefined && render(focused)}
      </div>}</MotionPresence>}
    </div>
  );
}

function StepGroup({ steps, focusIndex, render }: { steps: CodeStep[]; focusIndex?: number; render: (index: number) => ReactNode }) {
  const [open, setOpen] = useState(false);
  let count = 0;
  const rows: (number | StepRunData)[] = [];
  for (const { index, category } of steps) {
    if (!category) rows.push(index);
    else {
      if (category !== "failed") count++;
      const last = rows[rows.length - 1];
      if (typeof last === "object" && last.category === category) last.indexes.push(index);
      else rows.push({ category, indexes: [index] });
    }
  }
  return (
    <div className="step-group">
      {count > 0 && <button type="button" className="step-toggle" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <Icon name="chevronRight" size={13} className="disclosure-chevron" /><span>{open ? "Скрыть шаги" : `Шагов: ${count}`}</span>
      </button>}
      {rows.map((row) => {
        if (typeof row === "number") return render(row);
        if (row.category === "failed") return <StepRun key={row.indexes[0]} run={row} focusIndex={focusIndex} render={render} />;
        const focused = focusIndex !== undefined && row.indexes.includes(focusIndex);
        return <MotionPresence key={row.indexes[0]} kind="collapse" instant={focused}>
          {open ? <StepRun run={row} focusIndex={focusIndex} render={render} /> : focused && render(focusIndex)}
        </MotionPresence>;
      })}
    </div>
  );
}

function Queue({ api, state }: { api: WebApi; state: EngineState }) {
  return (
    <>
      {state.queue.map((entry, index) => (
        <div className="msg msg-queued" key={`${index}-${entry.text}`}>
          <span className="queued-label">В очереди</span>
          <span className="queued-text" data-i18n-skip>{entry.text || (entry.files?.length ? entry.files.join(", ") : `Картинок: ${entry.images}`)}</span>
          <IconButton icon="close" label="Убрать из очереди" onClick={() => { void api.cancel_queued(index); }} />
        </div>
      ))}
    </>
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
        <span className="activity"><span className="shimmer">{state.activity || "Думает"}</span></span>
        <span className="elapsed">{formatElapsed(elapsed)}</span>
        <button type="button" className="text-btn" onClick={onStop}>стоп <kbd>esc</kbd></button>
      </div>
      {state.reasoning && (
        <>
          <button type="button" className="text-btn" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
            <Icon name="chevronRight" size={13} className="disclosure-chevron" /> рассуждения
          </button>
          <MotionPresence kind="collapse">{expanded && <pre className="reasoning">{state.reasoning.slice(-4000)}</pre>}</MotionPresence>
        </>
      )}
    </div>
  );
}

export function Transcript({ api, state, focusIndex, onCopy, onView, onRetry, onEdit, onFork, onStop, onPrefill, onNotice }:
  { api: WebApi; state: EngineState; focusIndex: { index: number; nonce: number } | null;
    onCopy: (text: string) => void; onView: (path: string) => void; onRetry: () => void; onStop: () => void;
    onEdit: (index: number, text: string) => void; onFork: (index: number) => void; onPrefill: (text: string) => void; onNotice: (error?: string) => void }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const [awayFromEnd, setAwayFromEnd] = useState(false);
  const lastAssistant = state.items.map((item) => item.role).lastIndexOf("assistant");
  const lastUser = state.items.map((item) => item.role).lastIndexOf("user");
  const polls = useMemo(() => pollReplies(state.items), [state.items]);
  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (element && stickToBottom.current) element.scrollTop = element.scrollHeight;
  }, [state.items.length, state.busy, state.activity, state.reasoning, state.activePlan]);
  useLayoutEffect(() => {
    stickToBottom.current = true;
    setAwayFromEnd(false);
    const element = scrollRef.current;
    if (!element) return;
    element.scrollTop = element.scrollHeight;
    // An opened chat fades in as a whole; only messages that arrive after that rise one by one.
    element.querySelectorAll(".msg").forEach((message) => message.classList.add("settled"));
  }, [state.activeChatId]);
  useEffect(() => {
    if (!focusIndex) return;
    const element = document.getElementById(`msg-${focusIndex.index}`);
    if (!element) return;
    element.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    element.classList.remove("flash");
    void element.offsetWidth;
    element.classList.add("flash");
  }, [focusIndex]);

  let body: ReactNode;
  if (!state.models.length && !state.busy) {
    body = <Welcome api={api} state={state} />;
  } else if (!state.items.length && !state.busy && state.code.on) {
    body = <ProjectStart state={state} api={api} onDone={onNotice} />;
  } else if (!state.items.length && !state.busy) {
    body = (
      <div className="intro">
        <Decor corner="tr" />
        <div className="intro-brand"><Logo size={64} /><div><strong>PIVEN</strong></div></div>
        {!state.code.on && <Suggestions onPrefill={onPrefill} />}
      </div>
    );
  } else {
    const render = (index: number) => {
      const item = state.items[index];
      return (
        <Message key={`${state.activeChatId}-${index}`} api={api} item={item} index={index} chatId={state.activeChatId} answered={index < lastUser} pollAnswers={polls.answers.get(index)}
          canRetry={index === lastAssistant && !state.busy} canEdit={!state.busy}
          onCopy={onCopy} onView={onView} onRetry={onRetry} onEdit={onEdit} onFork={!state.busy && !state.listening.running ? onFork : undefined} />
      );
    };
    const segments: (number | CodeStep[])[] = [];
    let pendingPlan: number | undefined;
    const flushPlan = () => {
      if (pendingPlan !== undefined) segments.push(pendingPlan);
      pendingPlan = undefined;
    };
    state.items.forEach((item, index) => {
      if (polls.replies.has(index)) return;
      const card = item.role === "code" ? parseCard(item.text) : null;
      if (card?.kind === "plan") {
        if (!card.planId || card.planId !== state.activePlan?.planId) pendingPlan = index;
        return;
      }
      if (!card || !STEP_KINDS.has(card.kind)) {
        if (item.role === "user") flushPlan();
        segments.push(index);
        if (item.role === "assistant") flushPlan();
        return;
      }
      let category: StepCategory | undefined;
      if (isFailedCheck(card)) category = "failed";
      else if (card.kind === "command" || card.kind === "page") {
        if (card.exit === 0 && !card.denied && !card.stopped && !card.background) category = card.kind;
      } else if (card.kind !== "note") category = "file";
      const step = { index, category };
      const last = segments[segments.length - 1];
      if (Array.isArray(last)) last.push(step); else segments.push([step]);
    });
    flushPlan();
    const stalled = !state.busy && lastAssistant > lastUser && STALLED.test(state.items[lastAssistant]?.text ?? "");
    body = (
      <>
        {segments.map((segment) => (Array.isArray(segment)
          ? <StepGroup key={`steps-${segment[0].index}`} steps={segment} focusIndex={focusIndex?.index} render={render} />
          : render(segment)))}
        {state.busy && <Working state={state} onStop={onStop} />}
        {state.activePlan && <div className="msg msg-code msg-plan" key={state.activePlan.planId}><CodePlan items={state.activePlan.items} live /></div>}
        <Queue api={api} state={state} />
        {stalled && <div className="msg msg-continue"><button type="button" className="btn btn-primary" onClick={() => { void api.send_message("Продолжай", []).then((result) => onNotice(result.ok ? undefined : result.error)); }}><Icon name="play" size={14} /> Продолжить</button></div>}
      </>
    );
  }
  return <>
    <div className="transcript" ref={scrollRef} onScroll={(event) => {
      const el = event.currentTarget;
      const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      stickToBottom.current = atEnd;
      setAwayFromEnd(!atEnd);
    }}>
      <div className="transcript-inner tab-view" key={state.activeChatId}>{body}</div>
    </div>
    {awayFromEnd && <button type="button" className="btn btn-secondary transcript-latest" onClick={() => {
      const el = scrollRef.current;
      if (!el) return;
      el.scrollTop = el.scrollHeight;
      stickToBottom.current = true;
      setAwayFromEnd(false);
    }}><Icon name="arrowDown" size={15} /><span>К последнему сообщению</span></button>}
  </>;
}
