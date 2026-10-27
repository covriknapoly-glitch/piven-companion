import { useCallback, useEffect, useState } from "react";
import type { HfFile, VoiceDetails, VoiceKind, VoiceSearchHit, VoiceStatus, WebApi } from "./bridge";
import { Icon } from "./icons";
import { Button, Field, MemoryBar, Modal, ModelLogo, gigabytes } from "./ui";

const KINDS: { kind: VoiceKind; title: string; placeholder: string }[] = [
  { kind: "asr", title: "Распознавание речи", placeholder: "Например, whisper russian, gigaam или parakeet" },
  { kind: "tts", title: "Озвучка", placeholder: "Например, piper ru, xtts, kokoro или qwen3-tts" },
];
const RUNTIME_EXTRA: Record<string, number> = { nemo: 400 * 2 ** 20, transformers: 700 * 2 ** 20, qwen: 1200 * 2 ** 20, piper: 0 };
export const ENGINE_NAMES: Record<string, string> = { nemo: "NeMo-Speech", qwen: "Qwen3-TTS", transformers: "Transformers", piper: "Piper",
  "faster-whisper": "faster-whisper", "qwen-asr": "Qwen3-ASR", kokoro: "Kokoro", chatterbox: "Chatterbox", "f5-tts": "F5-TTS",
  coqui: "Coqui TTS", voxcpm: "VoxCPM", parler: "Parler-TTS", omnivoice: "OmniVoice", audiocpp: "audio.cpp" };
const sizeText = (bytes: number) => `${(bytes / 1e9).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ГБ`;

/** The Hugging Face search for speech models, laid out like the chat-model hub: every speech model is listed,
 *  each with the engine that runs it or why none can. */
export function VoiceHubDialog({ api, initialKind, onClose, onDone }: { api: WebApi; initialKind: VoiceKind; onClose: () => void; onDone: () => void }) {
  const [kind, setKind] = useState<VoiceKind>(initialKind);
  const [query, setQuery] = useState("");
  const [token, setToken] = useState("");
  const [hits, setHits] = useState<VoiceSearchHit[] | null>(null);
  const [note, setNote] = useState("Загружаю популярные модели…");
  const [hit, setHit] = useState<VoiceSearchHit | null>(null);
  const [file, setFile] = useState<HfFile | null>(null);
  const [details, setDetails] = useState<VoiceDetails | null>(null);
  const [status, setStatus] = useState<VoiceStatus | null>(null);

  useEffect(() => {
    const text = query.trim();
    setNote(text ? "Ищу на Hugging Face…" : "Загружаю популярные модели…");
    let live = true;
    const timer = window.setTimeout(() => {
      void api.voice_search(kind, text, token).then((reply) => {
        if (!live) return;
        setHits(reply.models);
        const runnable = reply.models.filter((item) => item.engine).length;
        setNote(!reply.ok ? reply.error ?? "Поиск не удался."
          : reply.models.length ? `${text ? "Нашлось" : "Популярные"}: ${reply.models.length}, из них запустятся ${runnable}. Выбери модель.`
          : "Ничего не нашлось, попробуй другое название.");
      });
    }, text ? 450 : 0);
    return () => { live = false; window.clearTimeout(timer); };
  }, [api, kind, query, token]);

  useEffect(() => {
    setDetails(null); setFile(null);
    if (!hit?.engine) return;
    let live = true;
    void api.voice_details(kind, hit.id, hit.engine, token).then((reply) => { if (live) { setDetails(reply); setFile(reply.files?.[0] ?? null); } });
    return () => { live = false; };
  }, [api, kind, hit, token]);

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
  const repo = hit?.id ?? "";
  const engine = details?.engine ?? hit?.engine ?? "";
  const bytes = file?.size ?? details?.bytes ?? 0;
  const canInstall = Boolean(hit?.engine && details?.ok && details.supported && (!details.files || file));
  const memory = engine === "piper" ? 0 : bytes + (RUNTIME_EXTRA[engine] ?? 0);
  const installed = new Set((status?.[kind].models ?? []).map((model) => model.source.replace("huggingface.co/", "")));
  const start = () => {
    if (!canInstall) return;
    const extra = engine === "nemo" || engine === "piper" || engine === "audiocpp" ? { engine, file: file ?? undefined }
      : engine === "qwen" ? { repo, size: bytes } : { engine, size: bytes, voices: details?.voices };
    void api.voice_install(kind, repo, extra, token).then((reply) => { if (!reply.ok) setNote(reply.error || "Не удалось начать загрузку."); void poll(); });
  };

  return (
    <Modal title="Модели озвучки и распознавания" subtitle="Ищет на Hugging Face и в каталоге audio.cpp. У каждой модели видно, каким движком она запустится; движок ставится сам при первой загрузке."
      onClose={() => { if (!running) onClose(); }} width={720} className="hub-modal" footer={<>
        <span className="foot-note">{note}</span>
        {running
          ? <Button kind="ghost" onClick={() => { void api.voice_cancel(); }}>Отменить</Button>
          : <Button kind="primary" icon="download" disabled={!canInstall} onClick={start}>Скачать</Button>}
      </>}>
      {job && job.state !== "idle" && (
        <div className={`progress-card ${job.state}`}>
          <div className="progress-head"><strong>{job.id.split("/").pop()}</strong><span>{job.state === "error" ? "Ошибка" : job.state === "cancelled" ? "Отменено" : job.state === "done" ? "Готово" : `${job.percent}%`}</span></div>
          <div className="progress-track"><i style={{ width: `${job.state === "done" ? 100 : job.percent}%` }} /></div>
          <small>{job.state === "error" || job.state === "cancelled" ? job.error : job.state === "done" ? "Скачано. Выбери её в Настройки → Голос и микрофон." : job.message}</small>
        </div>
      )}
      <div className="segmented voice-hub-kinds">
        {KINDS.map((item) => <button key={item.kind} type="button" className={kind === item.kind ? "on" : ""} disabled={running} onClick={() => switchKind(item.kind)}>{item.title}</button>)}
      </div>
      <div className="hub-search">
        <label className="search-field"><Icon name="search" size={16} /><input autoFocus placeholder={KINDS.find((item) => item.kind === kind)?.placeholder} value={query} disabled={running} onChange={(event) => setQuery(event.target.value)} /></label>
        <input className="input mono hub-token" type="password" placeholder="Токен HF (для закрытых моделей)" value={token} autoComplete="off" onChange={(event) => setToken(event.target.value)} />
      </div>
      {hits && hits.length > 0 && (
        <div className="hub-list">
          {hits.map((item) => (
            <button key={item.id} type="button" className={`${item.id === repo ? "selected" : ""} ${item.engine ? "" : "unsupported"}`} disabled={running}
              title={item.engine ? `Запустится через ${item.engineLabel}` : `Не запустится: ${item.reason}`} onClick={() => setHit(item)}>
              <span className="hub-name"><ModelLogo api={api} name={item.title ?? item.id} author={item.engine === "audiocpp" ? "audio-cpp" : item.id.split("/")[0]} size={20} />
                <span className="hub-title">{item.title ?? item.id}{item.note && <small>{item.note}</small>}</span>
                {installed.has(item.id) && <small className="hub-tag">скачана</small>}
                {item.nonCommercial && <small className="hub-tag off" title={item.license}>некоммерческая</small>}{item.gated && <Icon name="pin" size={13} />}</span>
              <span className="hub-stats">{item.engine ? <small className="hub-tag engine">{item.engineLabel}</small> : <small className="hub-tag off">не запустится</small>}
                {item.engine !== "audiocpp" && <><Icon name="download" size={13} />{formatCount(item.downloads)}</>}</span>
            </button>
          ))}
        </div>
      )}
      {hit && (
        <div className="hub-form">
          {!hit.engine ? <p className="pane-note">Эту модель программа не запустит: {hit.reason}.</p>
            : !details ? <p className="pane-note">{engine === "nemo" ? "Проверяю, подойдёт ли этот GGUF для NeMo-Speech…" : "Смотрю, что это за модель…"}</p>
            : !details.ok ? <p className="pane-note">{details.error}</p>
            : !details.supported ? <p className="pane-note">{details.reason}</p>
            : <>
              {details.files && details.files.length > 0 && (
                <Field label={engine === "piper" ? "Голос" : "Файл"}>
                  <select className="select" value={file?.path ?? ""} disabled={running} onChange={(event) => setFile(details.files?.find((item) => item.path === event.target.value) ?? null)}>
                    {details.files.map((item) => <option key={item.path} value={item.path}>{item.label ?? item.path} ({sizeText(item.size ?? 0)})</option>)}
                  </select>
                </Field>
              )}
              {engine === "piper"
                ? <p className="pane-note">Работает на процессоре, видеопамять не нужна. Скачается {sizeText(bytes)}.</p>
                : status && <MemoryBar gpu={status.gpu} label={`При запуске через ${ENGINE_NAMES[engine] ?? engine}`}
                    parts={[{ label: "Веса", bytes }, { label: "Движок", bytes: memory - bytes }].filter((part) => part.bytes > 0)} />}
              {details.note && <p className="pane-note">{details.note}</p>}
              {engine !== "qwen" && details.voices && details.voices.length > 0 && <p className="pane-note">Голоса: {details.voices.slice(0, 12).join(", ")}{details.voices.length > 12 ? ` и ещё ${details.voices.length - 12}` : ""}.</p>}
              {engine === "qwen" && <p className="pane-note">{details.mode === "custom" ? `Готовые голоса: ${details.voices?.join(", ") || "—"}.` : "Голос по описанию."}</p>}
              <p className="pane-note">Лицензия: {details.license || hit.license || "не удалось узнать, см. страницу модели"}.</p>
              <p className="pane-note">Движок: {ENGINE_NAMES[engine] ?? engine}. Скачается {sizeText(bytes)}{engine === "piper" ? "." : `, в памяти ≈ ${gigabytes(memory)}.`}</p>
            </>}
        </div>
      )}
    </Modal>
  );
}

function formatCount(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}K`;
  return String(value);
}
