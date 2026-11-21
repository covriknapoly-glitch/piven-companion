import { useCallback, useEffect, useRef, useState } from "react";
import type { VoiceDetails, VoiceFileCheck, VoiceKind, VoiceSearchHit, VoiceStatus, WebApi } from "./bridge";
import { Icon } from "./icons";
import { currentLanguage } from "./i18n";
import { Button, Field, gigabytes, MemoryBar, Modal, ModelDescription, ModelLogo, SelectionMarker } from "./ui";

const KINDS: { kind: VoiceKind; title: string }[] = [
  { kind: "asr", title: "Распознавание речи" },
  { kind: "tts", title: "Озвучка" },
];
const sizeText = (bytes: number) => `${(bytes / 1e9).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ГБ`;
function languageCode(value: string) {
  try {
    const code = new Intl.Locale(value.trim().replaceAll("_", "-")).language;
    return /^[a-z]{2,3}$/.test(code) && !["mul", "und", "zxx"].includes(code) ? code : "";
  } catch {
    return "";
  }
}

function VoiceModelLanguages({ languages }: { languages: string[] }) {
  const locale = currentLanguage();
  const names = new Intl.DisplayNames(locale, { type: "language", fallback: "none" });
  const codes = new Set(languages.map(languageCode).filter(Boolean));
  const supported = [...codes].map((code) => names.of(code)).filter((name): name is string => Boolean(name))
    .sort((a, b) => a.localeCompare(b, locale));
  const supportedNames = new Intl.ListFormat(locale).format(supported);

  return (
    <p className="pane-note voice-model-languages">
      {supportedNames ? <>Поддерживаемые языки<span aria-hidden="true"> · </span><span data-i18n-skip>{supportedNames}</span></>
        : "Языки модели не указаны"}
    </p>
  );
}

export function VoiceHubDialog({ api, initialKind, onClose, onDone }: { api: WebApi; initialKind: VoiceKind; onClose: () => void; onDone: () => void }) {
  const [kind, setKind] = useState<VoiceKind>(initialKind);
  const [recent, setRecent] = useState(false);
  const [query, setQuery] = useState("");
  const [token, setToken] = useState("");
  const [hits, setHits] = useState<VoiceSearchHit[] | null>(null);
  const [note, setNote] = useState("Поиск GGUF-моделей…");
  const [nextCursor, setNextCursor] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  const searchVersion = useRef(0);
  const [hit, setHit] = useState<VoiceSearchHit | null>(null);
  const [file, setFile] = useState<NonNullable<VoiceDetails["files"]>[number] | null>(null);
  const [selection, setSelection] = useState<{ model: VoiceSearchHit; token: string; details: VoiceDetails } | null>(null);
  const [checked, setChecked] = useState<{ model: VoiceSearchHit; path: string; token: string; attempt: number; result: VoiceFileCheck } | null>(null);
  const [checkAttempt, retryCheck] = useState(0);
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const details = selection?.model === hit && selection?.token === token ? selection.details : null;
  const description = details?.note || (details && hit?.note);

  useEffect(() => {
    const text = query.trim();
    const version = ++searchVersion.current;
    setHits(null);
    setHit(null);
    setNextCursor("");
    setLoadingMore(false);
    setNote("Поиск GGUF-моделей…");
    const timer = window.setTimeout(() => {
      void api.voice_search(kind, text, token, recent).then((reply) => {
        if (version !== searchVersion.current) return;
        setHits(reply.models);
        setNextCursor(reply.nextCursor ?? "");
        const direct = reply.models[0];
        if (reply.ok && direct?.direct) {
          setHit(direct);
          setNote("");
          return;
        }
        setNote(!reply.ok ? reply.error ?? "Поиск не удался."
          : reply.warning || (reply.models.length ? `Моделей GGUF: ${reply.models.length}.`
          : "Подходящих моделей не нашлось, попробуй другое название."));
      }).catch(() => {
        if (version === searchVersion.current) setNote("Поиск не удался.");
      });
    }, text ? 450 : 0);
    return () => { searchVersion.current++; window.clearTimeout(timer); };
  }, [api, kind, query, token, recent]);

  useEffect(() => {
    setFile(null);
    if (!hit || hit.problem) return;
    let live = true;
    void api.voice_details(kind, hit.id, hit.engine, token).then((reply) => {
      if (live) {
        setSelection({ model: hit, token, details: reply });
        setFile(reply.files?.[0] ?? null);
      }
    });
    return () => { live = false; };
  }, [api, kind, hit, token]);

  const filePath = file?.path;
  const checkRequired = Boolean(hit && !hit.id.startsWith("audiocpp:"));
  const fileCheck = checked && checked.model === hit && checked.path === filePath && checked.token === token && checked.attempt === checkAttempt
    ? checked.result : null;
  useEffect(() => {
    if (!checkRequired || !hit || !filePath || !details?.ok || !details.supported) return;
    let live = true;
    void api.voice_check_file(kind, hit.id, filePath, token).then((result) => {
      if (live) setChecked({ model: hit, path: filePath, token, attempt: checkAttempt, result });
    }).catch(() => {
      if (live) setChecked({ model: hit, path: filePath, token, attempt: checkAttempt,
        result: { ok: false, retryable: true, error: "Не удалось проверить совместимость GGUF." } });
    });
    return () => { live = false; };
  }, [api, kind, hit, filePath, checkRequired, details, token, checkAttempt]);

  const poll = useCallback(() => api.voice_status().then((next) => { setStatus(next); return next; }), [api]);
  useEffect(() => { void poll(); }, [poll]);
  const job = status?.job;
  const running = job?.state === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => { void poll().then((next) => { if (next.job.state === "done") onDone(); }); }, 800);
    return () => window.clearInterval(timer);
  }, [poll, running, onDone]);

  const switchKind = (next: VoiceKind) => { if (next !== kind) { setKind(next); setHit(null); setHits(null); } };
  const loadMore = async () => {
    const version = searchVersion.current;
    setLoadingMore(true);
    try {
      const reply = await api.voice_search(kind, query.trim(), token, recent, nextCursor);
      if (version !== searchVersion.current) return;
      if (!reply.ok || reply.warning) {
        setNote(reply.error || reply.warning || "Поиск не удался.");
        return;
      }
      const merged = new Map([...(hits ?? []), ...reply.models].map((model) => [model.id, model]));
      setHits([...merged.values()]);
      setNextCursor(reply.nextCursor === nextCursor ? "" : reply.nextCursor ?? "");
      setNote(`Моделей GGUF: ${merged.size}.`);
    } catch {
      if (version === searchVersion.current) setNote("Поиск не удался.");
    } finally {
      if (version === searchVersion.current) setLoadingMore(false);
    }
  };
  const repo = hit?.id ?? "";
  const engine = checkRequired ? fileCheck?.engine : details?.engine;
  const bytes = file?.size ?? details?.bytes ?? 0;
  const canInstall = Boolean(hit && !hit.problem && details?.ok && details.supported && file &&
    (!checkRequired || fileCheck?.supported || fileCheck?.retryable && fileCheck.ok));
  const engineName = checkRequired ? fileCheck?.engineName : hit?.engineLabel;
  const memory = bytes + (engine === "nemo" ? 400 * 2 ** 20 : 0);
  const installed = new Set((status?.[kind].models ?? []).map((model) =>
    model.id.startsWith("audiocpp:") && model.id.split("/").length === 2
      ? model.id.split("/")[0] : model.source.replace("huggingface.co/", "")));
  const start = () => {
    if (!canInstall || !file) return;
    void api.voice_install(kind, repo, { engine: checkRequired ? "auto" : "audiocpp", file }, token)
      .then((reply) => { if (!reply.ok) setNote(reply.error || "Не удалось начать загрузку."); void poll(); });
  };

  return (
    <Modal title="Модели озвучки и распознавания" subtitle="GGUF-модели для NeMo-Speech, audio.cpp и transcribe.cpp. Нужный движок ставится вместе с первой моделью."
      onClose={onClose} width={720} className="hub-modal" footer={<>
        <span className="foot-note">{running ? "Окно можно закрыть: загрузка продолжится, её видно в панели слева." : note}</span>
        {running && <Button kind="ghost" onClick={onClose}>Скрыть</Button>}
        {running
          ? <Button kind="ghost" onClick={() => { void api.voice_cancel(); }}>Отменить</Button>
          : <Button kind="primary" icon="download" disabled={!canInstall} onClick={start}>
            {fileCheck?.retryable && fileCheck.ok ? "Скачать и проверить" : "Скачать"}
          </Button>}
      </>}>
      {job && job.state !== "idle" && (
        <div className={`progress-card ${job.state}`}>
          <div className="progress-head"><strong>{job.id.split("/").pop()}</strong><span>{job.state === "error" ? "Ошибка" : job.state === "cancelled" ? "Отменено" : job.state === "done" ? "Готово" : `${job.percent}%`}</span></div>
          <div className="progress-track"><i style={{ width: `${job.state === "done" ? 100 : job.percent}%` }} /></div>
          <small>{job.state === "error" || job.state === "cancelled" ? job.error : job.state === "done" ? "Скачано. Выбери её в Настройки → Голос и микрофон." : job.message}</small>
        </div>
      )}
      <div className="voice-hub-toolbar">
        <div className="segmented voice-hub-kinds sliding-selection" role="tablist" aria-label="Тип голосовой модели">
          <SelectionMarker selected={kind} />
          {KINDS.map((item) => <button key={item.kind} type="button" role="tab" aria-selected={kind === item.kind}
            aria-controls="voice-model-results" className={kind === item.kind ? "on" : ""} disabled={running} onClick={() => switchKind(item.kind)}>{item.title}</button>)}
        </div>
        <select className="select" aria-label="Сортировка моделей" value={recent ? "recent" : "popular"} disabled={running}
          onChange={(event) => setRecent(event.target.value === "recent")}>
          <option value="popular">По загрузкам</option>
          <option value="recent">Новые</option>
        </select>
      </div>
      <div className="hub-search">
        <label className="search-field"><Icon name="search" size={16} /><input autoFocus placeholder="Название, автор/модель или ссылка Hugging Face" value={query} disabled={running} onChange={(event) => setQuery(event.target.value)} /></label>
        <input className="input mono hub-token" type="password" placeholder="Токен HF (для закрытых моделей)" value={token} autoComplete="off" onChange={(event) => setToken(event.target.value)} />
      </div>
      <div key={kind} id="voice-model-results" role="tabpanel" className="tab-view">
        {hits && hits.length > 0 && (
          <div className="hub-list" data-smooth-wheel>
            {hits.map((item) => (
              <button key={item.id} type="button" className={item.id === repo ? "selected" : ""} disabled={running}
                title={item.problem || (item.engineLabel === "GGUF" ? "Совместимость зависит от выбранного GGUF-файла." : `Запустится через ${item.engineLabel}`)} onClick={() => setHit(item)}>
                <span className="hub-name"><ModelLogo api={api} name={item.title ?? item.id} author={item.engine === "audiocpp" ? "audio-cpp" : item.id.split("/")[0]} size={20} />
                  <span className="hub-title">{item.title ?? item.id}</span>
                  {installed.has(item.id) && <small className="hub-tag">скачана</small>}
                  {item.nonCommercial && <small className="hub-tag off" title={item.license}>некоммерческая</small>}{item.gated && <Icon name="pin" size={13} />}</span>
                <span className="hub-stats"><small className="hub-tag engine">{item.problem ? "Несовместима" : item.engineLabel}</small>
                  {item.engine !== "audiocpp" && <><Icon name="download" size={13} />{formatCount(item.downloads)}</>}</span>
              </button>
            ))}
          </div>
        )}
        {nextCursor && <Button kind="ghost" disabled={loadingMore || running} onClick={() => { void loadMore(); }}>
          {loadingMore ? "Поиск GGUF-моделей…" : "Показать ещё"}
        </Button>}
        {description ? <p className="model-desc voice-model-description">{description}</p>
          : hit && hit.engine !== "audiocpp" && <ModelDescription api={api} repo={hit.id} token={token} />}
        {hit && (
          <div className="hub-form">
            {hit.problem ? <p className="pane-note error-text">{hit.problem}</p>
              : !details ? <p className="pane-note">Загружаю список GGUF-файлов…</p>
              : !details.ok ? <p className="pane-note">{details.error}</p>
              : !details.supported ? <p className="pane-note">{details.reason}</p>
              : <>
                {details.files && details.files.length > 0 && (
                  <Field label={checkRequired ? "GGUF-файл" : "GGUF-пакет"}>
                    <select className="select" value={file?.path ?? ""} disabled={running} onChange={(event) => setFile(details.files?.find((item) => item.path === event.target.value) ?? null)}>
                      {details.files.map((item) => <option key={item.path} value={item.path}>{item.label ?? item.path} ({sizeText(item.size ?? 0)})</option>)}
                    </select>
                  </Field>
                )}
                <VoiceModelLanguages languages={file?.languages ?? details.languages ?? []} />
                {checkRequired && <div role="status">
                  {!fileCheck ? <p className="pane-note">Определяю движок по заголовку GGUF…</p>
                    : !fileCheck.supported && <>
                      <p className={fileCheck.retryable && fileCheck.ok ? "pane-note" : "pane-note error-text"}>
                        {fileCheck.retryable && fileCheck.ok
                          ? "Заголовок недоступен. PIVEN определит движок после скачивания файла."
                          : fileCheck.error || fileCheck.reason}
                      </p>
                      {(!fileCheck.ok || fileCheck.retryable) && <Button kind="ghost" onClick={() => retryCheck((attempt) => attempt + 1)}>Повторить проверку</Button>}
                    </>}
                </div>}
                {status && engineName && <MemoryBar gpu={status.gpu} label={`При запуске через ${engineName}`}
                  parts={{ weights: bytes, other: memory - bytes }} />}
                {details.voices && details.voices.length > 0 && <p className="pane-note">Голоса: {details.voices.slice(0, 12).join(", ")}{details.voices.length > 12 ? ` и ещё ${details.voices.length - 12}` : ""}.</p>}
                <p className="pane-note">Лицензия: {details.license || hit.license || "не удалось узнать, см. страницу модели"}.</p>
                {engineName && <p className="pane-note">Движок: {engineName}. Скачается {sizeText(bytes)}, в памяти ≈ {gigabytes(memory)}.</p>}
                {(checkRequired ? fileCheck?.engineNote : details.engineNote) &&
                  <p className="pane-note">{checkRequired ? fileCheck?.engineNote : details.engineNote}</p>}
              </>}
          </div>
        )}
      </div>
    </Modal>
  );
}

function formatCount(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}K`;
  return String(value);
}
