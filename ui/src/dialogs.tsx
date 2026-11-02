import { useCallback, useEffect, useState } from "react";
import type { DownloadConfirm, EngineState, HfFile, HfModel, HfStatus, ListenOptions, SearchHit, TwitchStatus, WebApi, MemoryEstimate } from "./bridge";
import { Icon, type IconName } from "./icons";
import { Button, Field, IconButton, MemoryBar, Modal, ModelDescription, ModelLogo, Switch, useOutsideClose } from "./ui";

export function ConfirmDialog({ title, text, confirmLabel, cancelLabel = "Отмена", danger = false, onConfirm, onClose }:
  { title: string; text: string; confirmLabel: string; cancelLabel?: string; danger?: boolean; onConfirm: () => void; onClose: () => void }) {
  return (
    <Modal title={title} onClose={onClose} width={440} footer={<>
      <Button kind="ghost" onClick={onClose}>{cancelLabel}</Button>
      <Button kind={danger ? "danger" : "primary"} onClick={() => { onConfirm(); onClose(); }}>{confirmLabel}</Button>
    </>}>
      <p className="dialog-text">{text}</p>
    </Modal>
  );
}

export function DownloadDialog({ confirm, api }: { confirm: DownloadConfirm; api: WebApi }) {
  const answer = (approved: boolean) => { void api.answer_confirmation(confirm.id, approved); };
  return (
    <Modal title="Скачать файл?" subtitle="Компаньон просит разрешения на скачивание." onClose={() => answer(false)} width={520} footer={<>
      <Button kind="ghost" onClick={() => answer(false)}>Не скачивать</Button>
      <Button kind="primary" icon="download" onClick={() => answer(true)}>Скачать</Button>
    </>}>
      <dl className="kv">
        <dt>Адрес</dt><dd className="mono">{confirm.url}</dd>
        <dt>Куда</dt><dd className="mono">{confirm.destination}</dd>
      </dl>
      <p className="dialog-note">Существующий файл не будет перезаписан. Скачанное ничего не запускает.</p>
    </Modal>
  );
}

const ROLE_NAMES: Record<string, string> = { user: "Вы", assistant: "PIVEN", system: "Система", computer: "Звук ПК" };

export function SearchDialog({ api, onOpen, onClose }: { api: WebApi; onOpen: (hit: SearchHit) => void; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) { setHits(null); return; }
    const timer = window.setTimeout(() => { void api.search_messages(text).then(setHits); }, 180);
    return () => window.clearTimeout(timer);
  }, [api, query]);
  return (
    <Modal title="Поиск по сообщениям" subtitle="Ищет во всех чатах, по тексту ответов и вопросов." onClose={onClose} width={640} className="search-modal">
      <label className="search-field big"><Icon name="search" size={17} /><input autoFocus placeholder="Что найти?" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <div className="search-results">
        {hits === null && <p className="dialog-note">Введи хотя бы два символа.</p>}
        {hits?.length === 0 && <p className="dialog-note">Ничего не нашлось.</p>}
        {hits?.map((hit) => (
          <button key={`${hit.chatId}-${hit.index}`} type="button" className="search-hit" onClick={() => { onOpen(hit); onClose(); }}>
            <span className="search-hit-head"><strong>{hit.chatTitle}</strong><span>{ROLE_NAMES[hit.role] ?? hit.role}</span></span>
            <span className="search-hit-text">{hit.excerpt}</span>
          </button>
        ))}
      </div>
    </Modal>
  );
}

export function TwitchDialog({ api, onClose, poll = null }: { api: WebApi; onClose: () => void; poll?: { question: string; options: string[] } | null }) {
  const [mode, setMode] = useState<"message" | "poll">(poll ? "poll" : "message");
  const [question, setQuestion] = useState(poll?.question.slice(0, 60) ?? "");
  const [choices, setChoices] = useState<string[]>(poll ? poll.options.slice(0, 5).map((item) => item.slice(0, 25)) : ["", ""]);
  const [seconds, setSeconds] = useState(120);
  const [status, setStatus] = useState<TwitchStatus | null>(null);
  const [channel, setChannel] = useState("");
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirming, setConfirming] = useState(false);
  useEffect(() => { void api.twitch_status().then((next) => { setStatus(next); setChannel(next.channel); }); }, [api]);
  const max = status?.maxChars ?? 300;
  const filled = choices.filter((item) => item.trim());
  const ready = Boolean(channel.trim() && token.trim() && !sending && status?.enabled
    && (mode === "message" ? message.trim() && message.length <= max : question.trim() && filled.length >= 2));
  const send = () => {
    setSending(true); setResult(null); setConfirming(false);
    if (mode === "poll") {
      void api.twitch_poll(channel, question, filled, seconds, token).then((reply) => {
        setSending(false);
        setResult({ ok: reply.ok, text: reply.ok ? reply.message ?? "Опрос запущен." : reply.error ?? "Опрос не запущен." });
      });
      return;
    }
    void api.twitch_send(channel, message, token).then((reply) => {
      setSending(false);
      setResult({ ok: reply.ok, text: reply.ok ? reply.message ?? "Отправлено." : reply.error ?? "Не отправлено." });
      if (reply.status && status) setStatus({ ...status, status: reply.status });
      if (reply.ok) setMessage("");
    });
  };
  return (
    <Modal title={mode === "poll" ? "Опрос в Twitch" : "Сообщение в Twitch"} subtitle={mode === "poll" ? "Опрос для зрителей запускается на твоём канале после подтверждения." : "Отправляется ровно одно сообщение после твоего подтверждения."} onClose={() => { if (!sending) onClose(); }} width={560} footer={<>
      <span className="foot-note">{status?.status}</span>
      {confirming
        ? <><Button kind="ghost" onClick={() => setConfirming(false)}>Назад</Button><Button kind="primary" icon="send" onClick={send}>{mode === "poll" ? `Да, запустить на #${channel.replace(/^#/, "")}` : `Да, отправить в #${channel.replace(/^#/, "")}`}</Button></>
        : <Button kind="primary" icon="send" disabled={!ready} onClick={() => setConfirming(true)}>{sending ? "Отправка…" : mode === "poll" ? "Запустить опрос" : "Отправить"}</Button>}
    </>}>
      {status && !status.enabled && <div className="inline-alert"><Icon name="alert" size={15} /> Интеграция Twitch выключена в настройках.</div>}
      <div className="segmented dialog-mode">
        <button type="button" className={mode === "message" ? "on" : ""} onClick={() => setMode("message")}>Сообщение</button>
        <button type="button" className={mode === "poll" ? "on" : ""} onClick={() => setMode("poll")}>Опрос</button>
      </div>
      <Field label="Канал" hint="Без решётки, например twitchdev.">
        <input className="input mono" value={channel} placeholder="канал" onChange={(event) => setChannel(event.target.value)} />
      </Field>
      <Field label="OAuth-токен" hint={<>Нужно разрешение {mode === "poll" ? "channel:manage:polls (токен твоего канала; опросы есть у партнёров и компаньонов Twitch)" : "user:write:chat"}. Хранится только до закрытия окна.{" "}
        <button type="button" className="inline-link" onClick={() => { void api.open_twitch_help(); }}>Как получить токен</button></>}>
        <input className="input mono" type="password" value={token} placeholder="токен" autoComplete="off" onChange={(event) => setToken(event.target.value)} />
      </Field>
      {mode === "message" ? (
        <Field label="Сообщение" hint={`${message.length} из ${max} символов`}>
          <textarea className="textarea" rows={3} value={message} maxLength={max} onChange={(event) => setMessage(event.target.value)} />
        </Field>
      ) : <>
        <Field label="Вопрос" hint={`${question.length} из 60 символов`}>
          <input className="input" value={question} maxLength={60} onChange={(event) => setQuestion(event.target.value)} />
        </Field>
        <Field label="Варианты" hint="От 2 до 5, каждый до 25 символов.">
          {choices.map((choice, index) => (
            <div key={index} className="row grow poll-choice">
              <input className="input" value={choice} maxLength={25} placeholder={`Вариант ${index + 1}`}
                onChange={(event) => setChoices(choices.map((item, key) => (key === index ? event.target.value : item)))} />
              {choices.length > 2 && <IconButton icon="close" label="Убрать вариант" size={13} onClick={() => setChoices(choices.filter((_, key) => key !== index))} />}
            </div>
          ))}
          {choices.length < 5 && <Button kind="ghost" icon="plus" onClick={() => setChoices([...choices, ""])}>Добавить вариант</Button>}
        </Field>
        <Field label="Длительность">
          <select className="select" value={seconds} onChange={(event) => setSeconds(Number(event.target.value))}>
            {[[60, "1 минута"], [120, "2 минуты"], [300, "5 минут"], [600, "10 минут"], [1800, "30 минут"]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
      </>}
      {result && <div className={`inline-alert ${result.ok ? "ok" : ""}`}><Icon name={result.ok ? "check" : "alert"} size={15} /> {result.text}</div>}
    </Modal>
  );
}

const formatSize = (size?: number) => (size ? `${(size / 1024 ** 3).toFixed(2)} ГБ` : "");
const formatCount = (value?: number) => (typeof value === "number" ? value.toLocaleString("ru-RU") : "");

export function HubDialog({ api, onClose, onDone }: { api: WebApi; onClose: () => void; onDone: () => void }) {
  const [query, setQuery] = useState("");
  const [token, setToken] = useState("");
  const [models, setModels] = useState<HfModel[] | null>(null);
  const [repo, setRepo] = useState("");
  const [files, setFiles] = useState<HfFile[]>([]);
  const [file, setFile] = useState<HfFile | null>(null);
  const [tag, setTag] = useState("");
  const [note, setNote] = useState("Начни вводить название модели, например Qwen3 или Gemma.");
  const [progress, setProgress] = useState<HfStatus | null>(null);
  const [memory, setMemory] = useState<{ gpu: number; context: number; estimate: MemoryEstimate | null; known: boolean } | null>(null);
  useEffect(() => {
    setMemory(null);
    if (!repo || !file) return;
    let live = true;
    void api.hf_memory(repo, file.path, file.size ?? 0, token).then((reply) => { if (live) setMemory(reply); });
    return () => { live = false; };
  }, [api, repo, file, token]);

  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) { setModels(null); return; }
    setNote("Поиск на Hugging Face…");
    const timer = window.setTimeout(() => {
      void api.hf_search(text, token).then((reply) => {
        setModels(reply.models);
        setNote(reply.ok ? (reply.models.length ? `Нашлось репозиториев: ${reply.models.length}. Выбери один.` : "GGUF-моделей не нашлось, попробуй другое название.") : reply.error ?? "Поиск не удался.");
      });
    }, 450);
    return () => window.clearTimeout(timer);
  }, [api, query, token]);

  const chooseRepo = (id: string) => {
    setRepo(id); setFiles([]); setFile(null); setNote("Загрузка списка файлов…");
    void api.hf_files(id, token).then((reply) => {
      setFiles(reply.files); setFile(reply.files[0] ?? null); setTag(reply.tag ?? "");
      setNote(reply.ok ? (reply.files.length ? "Рекомендуемый файл (Q4_K_M) выбран сразу; можно выбрать другую квантизацию." : "В этом репозитории нет GGUF-файлов.") : reply.error ?? "Не удалось получить файлы.");
    });
  };

  const poll = useCallback(() => api.hf_status().then((next) => { setProgress(next); return next; }), [api]);
  useEffect(() => {
    if (progress?.state !== "running") return;
    const timer = window.setInterval(() => { void poll().then((next) => { if (next.state === "done") onDone(); }); }, 700);
    return () => window.clearInterval(timer);
  }, [poll, progress?.state, onDone]);
  useEffect(() => { void poll(); }, [poll]);

  const running = progress?.state === "running";
  const start = () => {
    if (!file) return;
    void api.hf_start(repo, file, tag, token).then((reply) => { if (!reply.ok) setNote(reply.error ?? "Не удалось начать загрузку."); void poll(); });
  };
  return (
    <Modal title="Модели с Hugging Face" subtitle="Скачивает GGUF-файл в папку моделей. Если в репозитории есть mmproj, модель сможет смотреть на картинки." onClose={onClose} width={680} className="hub-modal" footer={<>
      <span className="foot-note">{running ? "Окно можно закрыть: загрузка продолжится, её видно в панели слева." : note}</span>
      {running && <Button kind="ghost" onClick={onClose}>Скрыть</Button>}
      {running
        ? <Button kind="ghost" onClick={() => { void api.hf_cancel(); }}>Отменить</Button>
        : <Button kind="primary" icon="download" disabled={!file} onClick={start}>Скачать</Button>}
    </>}>
      {progress && progress.state !== "idle" && (
        <div className={`progress-card ${progress.state}`}>
          <div className="progress-head"><strong>{progress.tag}</strong><span>{progress.state === "error" ? "Ошибка" : progress.state === "cancelled" ? "Отменено" : `${progress.percent}%`}</span></div>
          <div className="progress-track"><i style={{ width: `${progress.percent}%` }} /></div>
          <small>{progress.state === "error" || progress.state === "cancelled" ? progress.error : progress.message}</small>
        </div>
      )}
      <div className="hub-search">
        <label className="search-field"><Icon name="search" size={16} /><input autoFocus placeholder="Название модели" value={query} disabled={running} onChange={(event) => setQuery(event.target.value)} /></label>
        <input className="input mono hub-token" type="password" placeholder="Токен HF (для закрытых моделей)" value={token} autoComplete="off" onChange={(event) => setToken(event.target.value)} />
      </div>
      {models && models.length > 0 && (
        <div className="hub-list">
          {models.map((model) => (
            <button key={model.id} type="button" className={model.id === repo ? "selected" : ""} disabled={running} onClick={() => chooseRepo(model.id)}>
              <span className="hub-name"><ModelLogo api={api} name={model.id} author={model.id.split("/")[0]} arch={model.arch ?? ""} size={20} />{model.id}{model.gated && <Icon name="pin" size={13} />}</span>
              <span className="hub-stats"><Icon name="download" size={13} />{formatCount(model.downloads)}</span>
            </button>
          ))}
        </div>
      )}
      {repo && <ModelDescription api={api} repo={repo} token={token} />}
      {files.length > 0 && (
        <div className="hub-form">
          <Field label="Файл">
            <select className="select" value={file?.path ?? ""} disabled={running} onChange={(event) => {
              const next = files.find((item) => item.path === event.target.value) ?? null;
              setFile(next); if (next) void api.hf_suggest_tag(repo, next.path).then(setTag);
            }}>
              {files.map((item) => <option key={item.path} value={item.path}>{item.path}{item.size ? ` (${formatSize(item.size)})` : ""}</option>)}
            </select>
          </Field>
          {file && (memory?.estimate
            ? <MemoryBar gpu={memory.gpu} speed={memory.estimate} label={memory.known ? `При запуске (контекст ${Math.round(memory.context / 1024)}K)` : "При запуске, без учёта контекста"}
                parts={[{ label: "Веса", bytes: memory.estimate.weights }, { label: "Контекст", bytes: memory.estimate.kv }, { label: "Прочее", bytes: memory.estimate.other }].filter((part) => part.bytes > 0)} />
            : <p className="pane-note">Расчёт памяти…</p>)}
          {tag && <p className="pane-note">В списке моделей она будет называться «{tag}».</p>}
        </div>
      )}
    </Modal>
  );
}

const SOURCES: { key: keyof ListenOptions; icon: IconName; label: string; hint: string }[] = [
  { key: "mic", icon: "mic", label: "Микрофон", hint: "Слышит, что ты говоришь" },
  { key: "loopback", icon: "volume", label: "Звук компьютера", hint: "Слышит видео и игры" },
  { key: "screen", icon: "monitor", label: "Экран", hint: "Видит экран в паузах" },
  { key: "proactive", icon: "spark", label: "Редкие комментарии", hint: "Иногда сам замечает важное" },
];
const LISTEN_KEY = "piven-listen-options";

function readListenOptions(fallback: ListenOptions): ListenOptions {
  try { return { ...fallback, ...JSON.parse(localStorage.getItem(LISTEN_KEY) || "{}") }; } catch { return fallback; }
}

const CALL_ASKED_KEY = "piven-call-asked";

function ListenOptionList({ options, disabled, onChange }: { options: ListenOptions; disabled?: boolean; onChange: (next: ListenOptions) => void }) {
  return <>{SOURCES.map((source) => (
    <label key={source.key} className="listen-option">
      <span className="listen-icon"><Icon name={source.icon} size={16} /></span>
      <span className="listen-copy"><strong>{source.label}</strong><small>{source.hint}</small></span>
      <Switch label={source.label} checked={options[source.key]} disabled={disabled} onChange={(value) => onChange({ ...options, [source.key]: value })} />
    </label>
  ))}</>;
}

export function ListenSettings({ state }: { state: EngineState }) {
  const [options, setOptions] = useState<ListenOptions>(() => readListenOptions(state.listening.options));
  const change = (next: ListenOptions) => { setOptions(next); try { localStorage.setItem(LISTEN_KEY, JSON.stringify(next)); } catch {  } };
  return (
    <div className="listen-settings">
      <ListenOptionList options={options} disabled={state.listening.running} onChange={change} />
      {state.listening.running && <div className="menu-note">Чтобы поменять источники, заверши звонок.</div>}
    </div>
  );
}

export function CallControl({ api, state, onError }: { api: WebApi; state: EngineState; onError: (message?: string) => void }) {
  const running = state.listening.running;
  const [asking, setAsking] = useState(false);
  const [options, setOptions] = useState<ListenOptions>(() => readListenOptions(state.listening.options));
  const close = useCallback(() => setAsking(false), []);
  const ref = useOutsideClose(asking, close);
  const active = SOURCES.filter((source) => state.listening.options[source.key] && source.key !== "proactive");
  const start = (chosen: ListenOptions) => {
    try { localStorage.setItem(LISTEN_KEY, JSON.stringify(chosen)); localStorage.setItem(CALL_ASKED_KEY, "1"); } catch {  }
    setAsking(false);
    void api.start_listening(chosen).then((reply) => onError(reply.ok ? undefined : reply.error));
  };
  const toggle = () => {
    if (running) { void api.stop_listening(); return; }
    let asked = false;
    try { asked = localStorage.getItem(CALL_ASKED_KEY) === "1"; } catch {  }
    const saved = readListenOptions(state.listening.options);
    if (asked) start(saved);
    else { setOptions(saved); setAsking((value) => !value); }
  };
  return (
    <div className={`call ${running ? "on" : ""}`} ref={ref}>
      {running && <span className="call-status" title={active.map((source) => source.label).join(", ")}><span className="live-dot" />Звонок</span>}
      <button type="button" className="call-btn" onClick={toggle} aria-label={running ? "Завершить звонок" : "Позвонить"} title={running ? "Завершить звонок" : "Позвонить"}>
        <Icon name="call" size={17} />
      </button>
      {asking && (
        <div className="menu menu-up-right listen-menu">
          <div className="menu-title">Что компаньон будет слышать и видеть</div>
          <ListenOptionList options={options} onChange={setOptions} />
          <div className="listen-foot">
            <small>Потом это можно поменять в настройках, в разделе «Голос и микрофон».</small>
            <Button kind="primary" icon="call" onClick={() => start(options)}>Позвонить</Button>
          </div>
        </div>
      )}
    </div>
  );
}
