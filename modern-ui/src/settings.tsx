import { useCallback, useEffect, useState } from "react";
import type { DiskUsage, EngineState, ModelMemory, SettingsDetails, ThinkingOptions, ThinkingValue, VoiceKind, VoiceModel, VoiceStatus, WebApi } from "./bridge";
import { Icon, type IconName } from "./icons";
import { ConfirmDialog } from "./dialogs";
import { LANGUAGES, type Language } from "./i18n";
import { ModelParamsPane } from "./params";
import { ProvidersPane } from "./providers";
import { ToolsPane } from "./tools";
import { MemoryPane } from "./memory";
import { Button, Field, gigabytes, IconButton, MemoryBar, ModelLogo, Switch, TextSetting, thinkingFixed, thinkingName, Toggle, useOutsideClose } from "./ui";

export type ThemeChoice = "system" | "light" | "dark";
type SectionId = "look" | "model" | "tools" | "memory" | "voice" | "images" | "code" | "integrations" | "data";
const SECTIONS: { id: SectionId; title: string; icon: IconName }[] = [
  { id: "look", title: "Оформление", icon: "sun" },
  { id: "model", title: "Модель", icon: "box" },
  { id: "tools", title: "Инструменты и навыки", icon: "code" },
  { id: "memory", title: "Память", icon: "chat" },
  { id: "voice", title: "Голос и микрофон", icon: "mic" },
  { id: "images", title: "Картинки и видео", icon: "image" },
  { id: "integrations", title: "Интеграции", icon: "extension" },
  { id: "data", title: "Данные", icon: "folder" },
];


let lastSection: SectionId = "look";  // reopening settings (after a hub dialog) returns to the same section

export type FontChoice = "mono" | "sans" | "huninn" | "martian" | "playfair" | "roboto";
export const FONT_CHOICES: readonly (readonly [FontChoice, string, string])[] = [
  ["mono", "IBM Plex Mono", "var(--mono)"], ["sans", "LINE Seed JP", "\"LINE Seed JP\", sans-serif"],
  ["huninn", "Huninn", "Huninn, sans-serif"], ["martian", "Martian Mono", "\"Martian Mono\", monospace"],
  ["playfair", "Playfair Display", "\"Playfair Display\", serif"], ["roboto", "Roboto Condensed", "\"Roboto Condensed\", sans-serif"],
];

export function SettingsDialog({ state, api, theme, setTheme, language, setLanguage, fontChoice, setFontChoice, onClose, onOpenHub, onOpenVoiceHub, onOpenTwitch }:
  { state: EngineState; api: WebApi; theme: ThemeChoice; setTheme: (value: ThemeChoice) => void; language: Language; setLanguage: (value: Language) => void;
    fontChoice: FontChoice; setFontChoice: (value: FontChoice) => void;
    onClose: () => void; onOpenHub: () => void; onOpenVoiceHub: (kind: VoiceKind) => void; onOpenTwitch: () => void }) {
  const ref = useOutsideClose(true, onClose);
  const [section, setSection] = useState<SectionId>(lastSection);
  useEffect(() => { lastSection = section; }, [section]);
  const [details, setDetails] = useState<SettingsDetails | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [savedAt, setSavedAt] = useState(0);
  const [showSaved, setShowSaved] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [thinking, setThinking] = useState<ThinkingOptions | null>(null);
  const model = state.settings.model;
  const [memory, setMemory] = useState<ModelMemory | null>(null);
  useEffect(() => { void api.model_memory(model ? [model] : []).then(setMemory); }, [api, model]);
  const modelEstimate = memory?.models[model];

  const reload = useCallback(() => api.settings_details().then((next) => { setDetails(next); setPrompt(next.systemPrompt); }), [api]);
  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => { if (model) void api.thinking_options(model).then(setThinking); }, [api, model]);
  useEffect(() => {
    if (!savedAt) return;
    setShowSaved(true);
    const timer = window.setTimeout(() => setShowSaved(false), 1800);
    return () => window.clearTimeout(timer);
  }, [savedAt]);

  const save = (patch: Record<string, unknown>) => api.update_settings(patch).then((result) => {
    setErrors((current) => {
      const next = { ...current };
      Object.keys(patch).forEach((key) => { delete next[key]; });
      return { ...next, ...result.errors };
    });
    if (result.saved.length) { setSavedAt(Date.now()); void reload(); }
    return result;
  });

  const d = details;
  const promptDirty = d !== null && prompt.trim() !== d.systemPrompt.trim();
  const current = SECTIONS.find((item) => item.id === section)!;
  return (
    <div className="modal-backdrop">
      <div className="modal settings" role="dialog" aria-modal="true" aria-label="Настройки" ref={ref}>
        <nav className="settings-nav">
          <h3>Настройки</h3>
          {SECTIONS.map((item) => (
            <button key={item.id} type="button" className={section === item.id ? "on" : ""} onClick={() => setSection(item.id)}>
              <Icon name={item.icon} size={17} />{item.title}
            </button>
          ))}
          <span className="settings-nav-spacer" />
          <span className={`saved-note ${showSaved ? "visible" : ""}`}><Icon name="check" size={14} /> Сохранено</span>
        </nav>
        <div className="settings-pane">
          <header className="settings-pane-head"><h4>{current.title}</h4><IconButton icon="close" label="Закрыть (Esc)" onClick={onClose} /></header>
          {!d ? <p className="pane-note">Загрузка…</p> : <div className="settings-fields">
            {section === "look" && <>
              <Field label="Язык / Language" hint="Язык интерфейса. Модель тоже будет отвечать на нём.">
                <div className="segmented wrap">
                  {LANGUAGES.map(([value, label]) => (
                    <button key={value} type="button" className={language === value ? "on" : ""} onClick={() => setLanguage(value)} data-i18n-skip>{label}</button>
                  ))}
                </div>
              </Field>
              <Field label="Шрифт" hint="Код, названия моделей и цифры всегда остаются моноширинными.">
                <div className="segmented wrap">
                  {FONT_CHOICES.map(([value, label, family]) => (
                    <button key={value} type="button" className={fontChoice === value ? "on" : ""} style={{ fontFamily: family }} onClick={() => setFontChoice(value)}>{label}</button>
                  ))}
                </div>
              </Field>
              <Field label="Тема" hint="Только для этого окна, обычное окно Компаньона не меняется.">
                <div className="segmented">
                  {([["system", "Как в Windows", "monitor"], ["light", "Светлая", "sun"], ["dark", "Тёмная", "moon"]] as const).map(([value, label, icon]) => (
                    <button key={value} type="button" className={theme === value ? "on" : ""} onClick={() => setTheme(value)}><Icon name={icon} size={15} />{label}</button>
                  ))}
                </div>
              </Field>
            </>}

            {section === "tools" && <>
              <ToolsPane api={api} />
              <Field label="Папка проекта" error={errors.projectRoot} hint="Здесь компаньон читает и правит файлы, когда просишь что-то сделать с кодом.">
                <div className="row grow">
                  <TextSetting mono value={d.projectRoot} onCommit={(value) => { void save({ projectRoot: value }); }} />
                  <Button onClick={() => { void api.pick_path("folder").then((path) => { if (path) void save({ projectRoot: path }); }); }}>Выбрать…</Button>
                </div>
              </Field>
            </>}
            {section === "memory" && <MemoryPane api={api} />}
            {section === "model" && <>
              <Field label="Модель" hint={state.status || "GGUF-файлы из папки моделей."}>
                <div className="row">
                  <ModelLogo api={api} name={model} size={28} />
                  <select className="select" value={model} disabled={!state.models.length}
                    onChange={(event) => { void api.set_model(event.target.value).then(() => setSavedAt(Date.now())); }}>
                    {state.models.map((name) => <option key={name} value={name}>{name}</option>)}
                  </select>
                  <Button icon="download" onClick={onOpenHub}>Скачать с Hugging Face…</Button>
                </div>
                {modelEstimate && memory && <MemoryBar gpu={memory.gpu} speed={modelEstimate} label={`При запуске (контекст ${Math.round(memory.context / 1024)}K)`}
                  parts={[{ label: "Веса", bytes: modelEstimate.weights }, { label: "Контекст", bytes: modelEstimate.kv }, { label: "Прочее", bytes: modelEstimate.other }, { label: "Голос", bytes: memory.voiceReserved ?? 0 }].filter((part) => part.bytes > 0)} />}
              </Field>
              <Field label="Моделей в памяти одновременно" hint="У каждого чата своя модель. Несколько моделей держатся загруженными и могут отвечать в разных чатах одновременно; модель без дела выгружается, если следующая не помещается рядом с ней в видеопамять.">
                <div className="segmented">
                  {[1, 2, 3, 4].map((count) => (
                    <button key={count} type="button" className={d.maxLoadedModels === count ? "on" : ""} onClick={() => { void save({ maxLoadedModels: count }); }}>{count}</button>
                  ))}
                </div>
              </Field>
              <LocalModels api={api} current={model} count={state.models.length} />
              <Field label="Размышление" hint={thinking?.error ? `Не удалось узнать у модели: ${thinking.error}` : thinking && !thinking.values.length ? thinkingFixed(thinking) : `По умолчанию у модели: ${thinkingName(thinking?.default ?? null) || "не указано"}.`}>
                {thinking && thinking.values.length > 0 && (
                  <div className="segmented wrap">
                    {thinking.values.map((value) => {
                      const effective = thinking.current === "__auto__" ? thinking.default ?? thinking.values[0] : thinking.current;
                      return (
                        <button key={String(value)} type="button" className={String(value) === String(effective) ? "on" : ""} onClick={() => {
                          const next: ThinkingValue | "__auto__" = String(value) === String(thinking.default) ? "__auto__" : value;
                          void api.set_thinking(model, next).then(() => { setSavedAt(Date.now()); void api.thinking_options(model).then(setThinking); });
                        }}>{thinkingName(value)}</button>
                      );
                    })}
                  </div>
                )}
              </Field>
              <Field label="Системный промпт" hint="Как компаньон должен себя вести. Применяется к следующим сообщениям." error={errors.systemPrompt}>
                <textarea className="textarea prompt-input" value={prompt} onChange={(event) => setPrompt(event.target.value)} spellCheck={false} />
                <div className="prompt-actions">
                  <span>{prompt.length.toLocaleString("ru-RU")} симв.</span>
                  <Button kind="ghost" disabled={prompt.trim() === d.defaultSystemPrompt.trim()} onClick={() => setPrompt(d.defaultSystemPrompt)}>Вернуть стандартный</Button>
                  <Button kind="ghost" disabled={!promptDirty} onClick={() => setPrompt(d.systemPrompt)}>Отменить</Button>
                  <Button kind="primary" disabled={!promptDirty} onClick={() => { void save({ systemPrompt: prompt }); }}>Сохранить</Button>
                </div>
              </Field>
              <ModelParamsPane api={api} model={model} onSaved={() => setSavedAt(Date.now())} />
            </>}

            {section === "voice" && <>
              <VoiceModels api={api} onOpenHub={onOpenVoiceHub} chatModel={model} chatMemory={modelEstimate?.total ?? 0} onChanged={() => { setSavedAt(Date.now()); void reload(); }} />
              <Field label="Озвучивать ответы" hint="Компаньон читает ответ вслух по предложениям, пока модель ещё его пишет.">
                <Switch label="Озвучивать ответы" checked={d.speechEnabled} onChange={(value) => { void save({ speechEnabled: value }); }} />
              </Field>
              <Field label="Перебивать голосом" hint="Если заговорить, пока компаньон отвечает, он замолчит и выслушает. С колонками вместо наушников может срабатывать от его собственного голоса — тогда выключи.">
                <Switch label="Перебивать голосом" checked={d.bargeIn} onChange={(value) => { void save({ bargeIn: value }); }} />
              </Field>
              <Field label="Голос">
                <select className="select" value={d.voice} onChange={(event) => { void save({ voice: event.target.value }); }}>
                  {d.voices.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </Field>
              <Field label="Образец голоса" error={errors.voiceSample}
                hint="Запись WAV на 5–15 секунд. Модели с клонированием (XTTS, Chatterbox, F5-TTS, VoxCPM, OmniVoice, IndexTTS2 и другие) будут говорить этим голосом, если в поле «Голос» выбрать «Мой образец голоса».">
                <div className="row grow">
                  <TextSetting mono value={d.voiceSample} placeholder="Файл не выбран" onCommit={(value) => { void save({ voiceSample: value }); }} />
                  <Button onClick={() => { void api.pick_path("audio").then((path) => { if (path) void save({ voiceSample: path }); }); }}>Выбрать…</Button>
                </div>
              </Field>
              <Field label="Что сказано в образце" hint="Точный текст записи. Части моделей он нужен, чтобы лучше скопировать голос.">
                <TextSetting value={d.voiceSampleText} placeholder="Например: Привет, это мой голос для компаньона." onCommit={(value) => { void save({ voiceSampleText: value }); }} />
              </Field>
              <Field label="Микрофон" hint={d.micError || "Используется, когда включено прослушивание."}>
                <select className="select" value={d.micDevice} onChange={(event) => { void save({ micDevice: event.target.value }); }}>
                  <option value="">Как в Windows</option>
                  {d.microphones.map((name) => <option key={name} value={name}>{name}</option>)}
                  {d.micDevice && !d.microphones.includes(d.micDevice) && <option value={d.micDevice}>{d.micDevice} (не подключён)</option>}
                </select>
              </Field>
              <Field label="Чувствительность микрофона" hint="Чем выше, тем тише голос он услышит, но и шум тоже.">
                <div className="range-row">
                  <input type="range" min={1} max={100} defaultValue={d.micSensitivity} key={`mic-${d.micSensitivity}`}
                    onMouseUp={(event) => { void save({ micSensitivity: Number((event.target as HTMLInputElement).value) }); }}
                    onKeyUp={(event) => { void save({ micSensitivity: Number((event.target as HTMLInputElement).value) }); }}
                    onInput={(event) => { const label = (event.target as HTMLInputElement).nextElementSibling; if (label) label.textContent = (event.target as HTMLInputElement).value; }} />
                  <span className="range-value">{d.micSensitivity}</span>
                </div>
              </Field>
              <Field label="Смотреть на экран раз в" hint="Интервал снимков экрана для комментариев, от 10 до 600 секунд.">
                <div className="row"><div className="narrow"><TextSetting value={String(d.screenInterval)} onCommit={(value) => { void save({ screenInterval: Number(value) }); }} /></div><span className="unit">сек.</span></div>
              </Field>
            </>}

            {section === "images" && <>
              <Field label="Адрес ComfyUI" error={errors.comfyUrl} hint="Если ComfyUI запущен на этом компьютере, обычно это http://127.0.0.1:8188.">
                <TextSetting mono value={d.comfyUrl} placeholder="http://127.0.0.1:8188" onCommit={(value) => { void save({ comfyUrl: value }); }} />
              </Field>
              <Field label="Workflow для картинок" error={errors.comfyWorkflow} hint="JSON-файл ComfyUI, через который рисуются картинки. Пустое поле вернёт стандартный.">
                <div className="row grow">
                  <TextSetting mono value={d.comfyWorkflow} onCommit={(value) => { void save({ comfyWorkflow: value }); }} />
                  <Button onClick={() => { void api.pick_path("workflow").then((path) => { if (path) void save({ comfyWorkflow: path }); }); }}>Выбрать…</Button>
                </div>
              </Field>
              <Field label="Workflow для видео" error={errors.comfyVideoWorkflow} hint="JSON-файл ComfyUI для видео (экспорт API или обычный). Текст запроса подставится в него; приложенная картинка — в узел LoadImage.">
                <div className="row grow">
                  <TextSetting mono value={d.comfyVideoWorkflow} placeholder="не выбран" onCommit={(value) => { void save({ comfyVideoWorkflow: value }); }} />
                  <Button onClick={() => { void api.pick_path("workflow").then((path) => { if (path) void save({ comfyVideoWorkflow: path }); }); }}>Выбрать…</Button>
                </div>
              </Field>
            </>}

            {section === "integrations" && <>
              {([["ollama", "Модели (llama.cpp и подключённые сервисы)", "Ответы, код и презентации. Если выключить, текущий ответ остановится."],
                 ["comfyui", "ComfyUI", "Рисование картинок."],
                 ["twitch", "Twitch", "Отправка сообщений в чат канала."]] as const).map(([key, label, hint]) => (
                <Field key={key} label={label} hint={hint}>
                  <Switch label={label} checked={d.integrations[key] !== false} onChange={(value) => { void save({ integrations: { [key]: value } }); }} />
                </Field>
              ))}
              <Field label="Twitch-канал" error={errors.twitchChannel} hint="Без решётки, например twitchdev.">
                <div className="row grow">
                  <TextSetting mono value={d.twitchChannel} placeholder="канал" onCommit={(value) => { void save({ twitchChannel: value }); }} />
                  <Button icon="twitch" onClick={onOpenTwitch}>Написать в чат…</Button>
                </div>
              </Field>
              <ProvidersPane api={api} onChanged={() => setSavedAt(Date.now())} />
            </>}

            {section === "data" && <>
              <Field label="Сброс настроек" hint="Вернёт рекомендуемые настройки: промпт, голос, микрофон, параметры модели, интеграции, оформление. Чаты, скачанные модели и выбранные модели останутся.">
                <ResetButton api={api} onReset={() => { setTheme("system"); setFontChoice(FONT_CHOICES[0][0]); void reload(); setSavedAt(Date.now()); }} />
              </Field>
              <Field label="Работа в фоне" hint="Крестик прячет окно в трей (значок у часов), ответы и вопросы модели приходят уведомлениями. Выйти совсем — правой кнопкой по значку → «Выйти».">
                <Toggle label="Сворачивать в трей при закрытии" checked={d.closeToTray} onChange={(value) => { void save({ closeToTray: value }); }} />
                <Toggle label="Уведомления, когда окно скрыто или в другом окне" checked={d.notifications} onChange={(value) => { void save({ notifications: value }); }} />
              </Field>
              <Field label="Папка с данными" hint={<span className="mono">{d.dataDir}</span>}>
                <div className="row">
                  <Button icon="folder" onClick={() => { void api.open_data_folder("folder"); }}>Открыть папку</Button>
                  <Button icon="file" onClick={() => { void api.open_data_folder("log"); }}>Открыть журнал</Button>
                </div>
              </Field>
              <p className="pane-note">Тут лежат настройки, все чаты, журналы и нарисованные картинки. Настройки общие с обычным окном Компаньона.</p>
            </>}
          </div>}
        </div>
      </div>
    </div>
  );
}

const VOICE_KINDS: { kind: VoiceKind; title: string; hint: string }[] = [
  { kind: "asr", title: "Распознавание речи", hint: "Переводит твой голос в текст во время звонка." },
  { kind: "tts", title: "Озвучка", hint: "Читает ответы вслух." },
];

function ResetButton({ api, onReset }: { api: WebApi; onReset: () => void }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  return <>
    <Button kind="danger" icon="refresh" onClick={() => setAsking(true)}>Сбросить все настройки</Button>
    {error && <p className="pane-note">{error}</p>}
    {asking && <ConfirmDialog title="Сбросить настройки?" text="Все настройки вернутся к рекомендуемым. Чаты и скачанные модели не пострадают." confirmLabel="Сбросить" danger
      onClose={() => setAsking(false)} onConfirm={() => { void api.reset_settings().then((result) => { setError(result.ok ? "" : result.error ?? ""); if (result.ok) onReset(); }); }} />}
  </>;
}

/** A delete button that asks once more before acting. */
function DeleteButton({ onDelete, disabled = false }: { onDelete: () => Promise<void>; disabled?: boolean }) {
  const [armed, setArmed] = useState(false);
  const [working, setWorking] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(timer);
  }, [armed]);
  return armed
    ? <Button kind="danger" icon="trash" disabled={working} onClick={() => { setWorking(true); void onDelete().finally(() => { setWorking(false); setArmed(false); }); }}>Точно удалить?</Button>
    : <Button kind="ghost" icon="trash" disabled={disabled} title="Удалить с диска" onClick={() => setArmed(true)}>Удалить</Button>;
}

function useDiskUsage(api: WebApi, revision: unknown) {
  const [usage, setUsage] = useState<DiskUsage | null>(null);
  useEffect(() => {
    let live = true;
    void api.disk_usage().then((reply) => { if (live) setUsage(reply); });
    return () => { live = false; };
  }, [api, revision]);
  return usage;
}

/** Chat models on disk, each with its size and a delete button. */
function LocalModels({ api, current, count }: { api: WebApi; current: string; count: number }) {
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const usage = useDiskUsage(api, `${revision}-${count}`);
  if (!usage || !usage.models.length) return null;
  const total = usage.models.reduce((sum, item) => sum + item.bytes, 0);
  return (
    <Field label="Модели на диске" hint={`Всего ${gigabytes(total)}. Удалённую модель можно скачать снова.`}>
      <div className="disk-list">
        {usage.models.map((item) => (
          <div key={item.name} className="disk-row">
            <ModelLogo api={api} name={item.name} size={20} />
            <span className="disk-name">{item.name}{item.name === current && <small className="hub-tag">выбрана</small>}</span>
            <span className="disk-size">{gigabytes(item.bytes)}</span>
            <DeleteButton onDelete={() => api.delete_model(item.name).then((reply) => { setError(reply.ok ? "" : reply.error ?? "Не удалось удалить."); setRevision((value) => value + 1); })} />
          </div>
        ))}
      </div>
      {error && <p className="pane-note">{error}</p>}
    </Field>
  );
}

function VoiceModels({ api, onOpenHub, chatModel, chatMemory, onChanged }: { api: WebApi; onOpenHub: (kind: VoiceKind) => void; chatModel: string; chatMemory: number; onChanged: () => void }) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [error, setError] = useState("");
  const [restartFor, setRestartFor] = useState<VoiceKind | null>(null);
  const [revision, setRevision] = useState(0);
  const usage = useDiskUsage(api, `${revision}-${status?.job.state}`);
  const load = useCallback(() => api.voice_status().then(setStatus), [api]);
  useEffect(() => { void load(); }, [load]);
  const running = status?.job.state === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => { void load(); }, 1000);
    return () => window.clearInterval(timer);
  }, [running, load]);
  if (!status) return null;

  const install = (kind: VoiceKind, id: string) => {
    setError("");
    void api.voice_install(kind, id).then((result) => { if (!result.ok) setError(result.error || "Не удалось начать загрузку."); void load(); });
  };
  const select = (kind: VoiceKind, id: string) => {
    setError("");
    void api.voice_select(kind, id).then((result) => {
      if (result.error) setError(result.error);
      if (result.ok && result.restart) setRestartFor(kind);
      void load(); onChanged();
    });
  };
  const job = status.job;
  const row = (kind: VoiceKind, model: VoiceModel) => {
    const selected = status[kind].selected === model.id;
    const mine = job.kind === kind && job.id === model.id && job.state !== "idle" && !(job.state === "done" && model.installed);
    return (
      <div key={model.id} className={`voice-model ${selected && model.installed ? "selected" : ""}`}>
        <ModelLogo api={api} name={model.title} size={32} />
        <div className="voice-model-copy">
          <strong>{model.title}</strong>
          <small>{model.note}</small>
          <small className="voice-model-meta">{model.engine} · {model.size} · {model.memory ? `в памяти ≈ ${gigabytes(model.memory)}` : "на процессоре"} · {model.license} · {model.source}</small>
          {mine && (
            <div className={`progress-card ${job.state}`}>
              <div className="progress-head"><strong>Установка</strong><span>{job.state === "error" ? "Ошибка" : job.state === "cancelled" ? "Отменено" : `${job.percent}%`}</span></div>
              <div className="progress-track"><i style={{ width: `${job.percent}%` }} /></div>
              <small>{job.state === "error" || job.state === "cancelled" ? job.error : job.message}</small>
            </div>
          )}
        </div>
        <div className="voice-model-action">
          {selected && model.installed ? <span className="unit"><Icon name="check" size={14} /> Используется</span>
            : model.installed ? <Button onClick={() => select(kind, model.id)}>Использовать</Button>
            : mine && running ? <Button kind="ghost" onClick={() => { void api.voice_cancel(); }}>Отменить</Button>
            : <Button icon="download" disabled={running} onClick={() => install(kind, model.id)}>{mine ? "Повторить" : "Скачать"}</Button>}
          {model.installed && !(mine && running) && <DeleteButton onDelete={() => api.voice_delete(kind, model.id).then((reply) => {
            setError(reply.ok ? "" : reply.error ?? "Не удалось удалить."); setRevision((value) => value + 1); void load(); onChanged();
          })} />}
        </div>
      </div>
    );
  };
  const inUse = (kind: VoiceKind) => status[kind].models.find((model) => model.id === status[kind].selected);
  const callParts = [
    ...(chatMemory ? [{ label: chatModel, bytes: chatMemory }] : []),
    ...(["asr", "tts"] as VoiceKind[]).map((kind) => inUse(kind)).filter((model): model is VoiceModel => Boolean(model)).map((model) => ({ label: model.title, bytes: model.memory })),
  ];
  return <>
    <MemoryBar gpu={status.gpu} label="Во время звонка с озвучкой" parts={callParts} />
    {VOICE_KINDS.map(({ kind, title, hint }) => (
      <Field key={kind} label={title} hint={status[kind].engine ? hint : <>{hint} {status[kind].engineNote}</>}>
        <div className="voice-models">{status[kind].models.map((model) => row(kind, model))}</div>
        <div className="voice-search-open"><Button icon="search" onClick={() => onOpenHub(kind)}>Найти другие на Hugging Face…</Button></div>
      </Field>
    ))}
    {error && <p className="pane-note">{error}</p>}
    {restartFor && <ConfirmDialog title="Нужен перезапуск"
      text={`Модель ${restartFor === "tts" ? "озвучки" : "распознавания"} сменена. Чтобы она заработала, программу нужно перезапустить. Чаты и настройки сохранятся.`}
      confirmLabel="Перезапустить сейчас" cancelLabel="Позже" onClose={() => setRestartFor(null)}
      onConfirm={() => { void api.restart_app(); }} />}
    {usage && (usage.voiceModels > 0 || usage.engines.length > 0) && (
      <Field label="Место на диске" hint="Движки ставятся один раз и нужны всем своим моделям; модели удаляются кнопкой «Удалить» выше.">
        <div className="disk-list">
          <div className="disk-row"><span className="disk-name">Голосовые модели</span><span className="disk-size">{gigabytes(usage.voiceModels)}</span></div>
          {usage.engines.map((item) => <div key={item.label} className="disk-row"><span className="disk-name">Движок · {item.label}</span><span className="disk-size">{gigabytes(item.bytes)}</span></div>)}
          <div className="disk-row total"><span className="disk-name">Всего</span><span className="disk-size">{gigabytes(usage.voiceModels + usage.engines.reduce((sum, item) => sum + item.bytes, 0))}</span></div>
        </div>
      </Field>
    )}
  </>;
}
