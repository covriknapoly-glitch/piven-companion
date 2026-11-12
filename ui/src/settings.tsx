import { useCallback, useEffect, useState } from "react";
import { isPhone } from "./bridge";
import type { DiskUsage, EngineState, MemoryEstimate, ModelMemory, SettingsDetails, VoiceKind, VoiceModel, VoiceStatus, WebApi } from "./bridge";
import { Icon, type IconName } from "./icons";
import { ConfirmDialog, ListenSettings } from "./dialogs";
import { LANGUAGES, type Language } from "./i18n";
import { ModelParamsPane, ModelSettingsPage } from "./params";
import { PhonePane } from "./pairing";
import { IntegrationsPane } from "./providers";
import { ToolsPane } from "./tools";
import { MemoryPane } from "./memory";
import { AdvancedHead, Button, callMemoryLabel, Decor, Field, gigabytes, groupModels, IconButton, MemoryBar, ModelLogo, shortModel, Switch, TextSetting, Toggle, useOutsideClose } from "./ui";
import { THEMES, type ThemeId } from "./themes";
type SectionId = "look" | "model" | "tools" | "memory" | "voice" | "images" | "code" | "integrations" | "phone" | "data";
const SECTIONS: { id: SectionId; title: string; icon: IconName }[] = [
  { id: "model", title: "Модель", icon: "box" },
  { id: "look", title: "Оформление и окно", icon: "palette" },
  { id: "voice", title: "Голос и микрофон", icon: "mic" },
  { id: "memory", title: "Память", icon: "chat" },
  { id: "tools", title: "Инструменты и навыки", icon: "code" },
  { id: "integrations", title: "Интеграции", icon: "extension" },
  { id: "images", title: "Картинки и видео", icon: "image" },
  { id: "phone", title: "Телефон", icon: "plug" },
  { id: "data", title: "Данные", icon: "folder" },
];

let lastSection: SectionId = "model";

export type FontChoice = "lack";
export const FONT_CHOICES: readonly (readonly [FontChoice, string, string])[] = [["lack", "Lack", "Lack, sans-serif"]];

export function SettingsDialog({ state, api, theme, setTheme, language, setLanguage, fontChoice, setFontChoice, onClose, onOpenHub, onOpenVoiceHub }:
  { state: EngineState; api: WebApi; theme: ThemeId; setTheme: (value: ThemeId) => void; language: Language; setLanguage: (value: Language) => void;
    fontChoice: FontChoice; setFontChoice: (value: FontChoice) => void;
    onClose: () => void; onOpenHub: () => void; onOpenVoiceHub: (kind: VoiceKind) => void }) {
  const ref = useOutsideClose(true, onClose);
  const [section, setSection] = useState<SectionId>(lastSection);
  useEffect(() => { lastSection = section; }, [section]);
  const [modelPage, setModelPage] = useState<string | null>(null);
  const [details, setDetails] = useState<SettingsDetails | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [savedAt, setSavedAt] = useState(0);
  const [showSaved, setShowSaved] = useState(false);
  const [prompt, setPrompt] = useState("");
  const model = state.settings.model;
  const [memory, setMemory] = useState<ModelMemory | null>(null);
  useEffect(() => { void api.model_memory(model ? [model] : []).then(setMemory); }, [api, model]);
  const modelEstimate = memory?.models[model];

  const reload = useCallback(() => api.settings_details().then((next) => { setDetails(next); setPrompt(next.systemPrompt); }), [api]);
  useEffect(() => { void reload(); }, [reload]);
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
  return (
    <div className="modal-backdrop">
      <div className="modal settings" role="dialog" aria-modal="true" aria-label="Настройки" ref={ref}>
        <nav className="settings-nav">
          <h3>Настройки</h3>
          {SECTIONS.filter((item) => !(isPhone && item.id === "phone")).map((item) => (
            <button key={item.id} type="button" className={section === item.id ? "on" : ""} onClick={() => { setSection(item.id); setModelPage(null); }}>
              <Icon name={item.icon} size={17} />{item.title}
            </button>
          ))}
          <Decor corner="bl" className="settings-decor" />
          <span className={`saved-note ${showSaved ? "visible" : ""}`}><Icon name="check" size={14} /> Сохранено</span>
        </nav>
        <div className="settings-pane">
          <IconButton icon="close" label="Закрыть (Esc)" className="settings-close" onClick={onClose} />
          {!d ? <p className="pane-note">Загрузка…</p> : <div className="settings-fields">
            {section === "look" && <>
              <Field label="Язык / Language" hint="Модель тоже будет отвечать на нём.">
                <div className="segmented wrap">
                  {LANGUAGES.map(([value, label]) => (
                    <button key={value} type="button" className={language === value ? "on" : ""} onClick={() => setLanguage(value)} data-i18n-skip>{label}</button>
                  ))}
                </div>
              </Field>
              {FONT_CHOICES.length > 1 && <Field label="Шрифт">
                <div className="segmented wrap">
                  {FONT_CHOICES.map(([value, label, family]) => (
                    <button key={value} type="button" className={fontChoice === value ? "on" : ""} style={{ fontFamily: family }} onClick={() => setFontChoice(value)}>{label}</button>
                  ))}
                </div>
              </Field>}
              <Field label="Тема">
                <div className="theme-grid">
                  {THEMES.map(([value, label, , swatches]) => (
                    <button key={value} type="button" className={theme === value ? "on" : ""} onClick={() => setTheme(value)}>
                      <span className="theme-swatches" style={{ background: swatches[0] }}>{swatches.slice(1).map((color) => <i key={color} style={{ background: color }} />)}</span>
                      <span>{label}</span>
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Работа в фоне" hint="Крестик прячет окно в трей (значок у часов), ответы и вопросы модели приходят уведомлениями. Выйти совсем — правой кнопкой по значку → «Выйти».">
                <Toggle label="Сворачивать в трей при закрытии" checked={d.closeToTray} onChange={(value) => { void save({ closeToTray: value }); }} />
                <Toggle label="Уведомления, когда окно скрыто или в другом окне" checked={d.notifications} onChange={(value) => { void save({ notifications: value }); }} />
              </Field>
            </>}

            {section === "tools" && <ToolsPane api={api}>
              <Field label="Папка проектов" error={errors.projectRoot} hint="Сюда агент кладёт новые программы, каждую в своей папке. Если оставить пустым, это «Документы\PIVEN Projects». Папку отдельного чата выбирай рядом с полем ввода.">
                <div className="row grow">
                  <TextSetting mono value={d.projectRoot} onCommit={(value) => { void save({ projectRoot: value }); }} />
                  <Button onClick={() => { void api.pick_path("folder").then((path) => { if (path) void save({ projectRoot: path }); }); }}>Выбрать…</Button>
                </div>
              </Field>
            </ToolsPane>}
            {section === "memory" && <MemoryPane api={api} />}
            {section === "model" && modelPage !== null && <ModelSettingsPage api={api} scope={modelPage} onBack={() => setModelPage(null)} onSaved={() => setSavedAt(Date.now())} />}
            {section === "model" && modelPage === null && <>
              <Field label="Модель" hint={state.status}>
                <ModelList api={api} models={state.models} current={model} onOpenHub={onOpenHub}
                  onPick={(name) => { void api.set_model(name).then(() => setSavedAt(Date.now())); }} onTune={setModelPage} />
                {modelEstimate && memory && <MemoryBar gpu={memory.gpu} speed={modelEstimate} label={callMemoryLabel(memory.context)}
                  parts={{ ...modelEstimate, voice: memory.voiceCall }} />}
                <div className="row model-tune-open">
                  {model && <Button kind="ghost" icon="settings" onClick={() => setModelPage(model)}>Настроить эту модель</Button>}
                  <Button kind="ghost" onClick={() => setModelPage("*")}>Общие настройки</Button>
                </div>
              </Field>
              <Field label="Системный промпт" hint="Как модель должна себя вести. Применяется к следующим сообщениям." error={errors.systemPrompt}>
                <textarea className="textarea prompt-input" value={prompt} onChange={(event) => setPrompt(event.target.value)} spellCheck={false} />
                <div className="prompt-actions">
                  <span>{prompt.length.toLocaleString("ru-RU")} симв.</span>
                  <Button kind="ghost" disabled={prompt.trim() === d.defaultSystemPrompt.trim()} onClick={() => setPrompt(d.defaultSystemPrompt)}>Вернуть стандартный</Button>
                  <Button kind="ghost" disabled={!promptDirty} onClick={() => setPrompt(d.systemPrompt)}>Отменить</Button>
                  <Button kind="primary" disabled={!promptDirty} onClick={() => { void save({ systemPrompt: prompt }); }}>Сохранить</Button>
                </div>
              </Field>
              <Field label="Режим для тяжёлых моделей" hint="Для очень больших моделей: в памяти остаются только сама модель с её контекстом и модель долговременной памяти. Выключаются звонок, голосовой ввод, озвучка, картинки и видео, поиск в интернете, MCP-серверы и другие загруженные модели." error={errors.heavyMode}>
                <Toggle label="Выключить всё, кроме модели" checked={d.heavyMode} onChange={(next) => { void save({ heavyMode: next }); }} />
              </Field>
              <ModelParamsPane api={api}>
              <Field label="Моделей в памяти одновременно" hint="У каждого чата своя модель. Несколько моделей держатся загруженными и могут отвечать в разных чатах одновременно; модель без дела выгружается, если следующая не помещается рядом с ней в видеопамять.">
                <div className="segmented">
                  {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((count) => (
                    <button key={count} type="button" disabled={d.heavyMode} className={(d.heavyMode ? count === 1 : d.maxLoadedModels === count) ? "on" : ""} onClick={() => { void save({ maxLoadedModels: count }); }}>{count}</button>
                  ))}
                </div>
              </Field>
              </ModelParamsPane>
            </>}

            {section === "voice" && <>
              {d.heavyMode && <p className="pane-note">Голос сейчас выключен режимом для тяжёлых моделей. Выключить его можно в разделе «Модель».</p>}
              <Field label="Во время звонка" hint="Что программа слышит и видит, когда ты нажимаешь кнопку звонка у поля ввода.">
                <ListenSettings state={state} />
              </Field>
              <Field label="Озвучивать ответы" hint="Программа читает ответ вслух по предложениям, пока модель ещё его пишет.">
                <Switch label="Озвучивать ответы" checked={d.speechEnabled} onChange={(value) => { void save({ speechEnabled: value }); }} />
              </Field>
              <Field label="Перебивать голосом" hint="Если заговорить, пока модель отвечает, она замолчит и выслушает. С колонками вместо наушников может срабатывать от её собственного голоса — тогда выключи.">
                <Switch label="Перебивать голосом" checked={d.bargeIn} onChange={(value) => { void save({ bargeIn: value }); }} />
              </Field>
              <Field label="Голос">
                <select className="select" value={d.voice} onChange={(event) => { void save({ voice: event.target.value }); }}>
                  {d.voices.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </Field>
              <Field label="Микрофон" hint={d.micError || "Используется, когда включено прослушивание."}>
                <select className="select" value={d.micDevice} onChange={(event) => { void save({ micDevice: event.target.value }); }}>
                  <option value="">Как в Windows</option>
                  {d.microphones.map((name) => <option key={name} value={name}>{name}</option>)}
                  {d.micDevice && !d.microphones.includes(d.micDevice) && <option value={d.micDevice}>{d.micDevice} (не подключён)</option>}
                </select>
              </Field>
              <VoiceModels api={api} onOpenHub={onOpenVoiceHub} chatMemory={modelEstimate} context={memory?.context ?? 0} onChanged={() => { setSavedAt(Date.now()); void reload(); }} />
              <AdvancedHead />
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
              <Field label="Образец голоса" error={errors.voiceSample}
                hint="Запись WAV на 5–15 секунд. Модели с клонированием (XTTS, Chatterbox, F5-TTS, VoxCPM, OmniVoice, IndexTTS2 и другие) будут говорить этим голосом, если в поле «Голос» выбрать «Мой образец голоса». Используй только свой голос или голос человека, который на это согласился.">
                <div className="row grow">
                  <TextSetting mono value={d.voiceSample} placeholder="Файл не выбран" onCommit={(value) => { void save({ voiceSample: value }); }} />
                  <Button onClick={() => { void api.pick_path("audio").then((path) => { if (path) void save({ voiceSample: path }); }); }}>Выбрать…</Button>
                </div>
              </Field>
              <Field label="Что сказано в образце" hint="Точный текст записи. Части моделей он нужен, чтобы лучше скопировать голос.">
                <TextSetting value={d.voiceSampleText} placeholder="Например: Привет, это мой голос для озвучки." onCommit={(value) => { void save({ voiceSampleText: value }); }} />
              </Field>
            </>}

            {section === "images" && <>
              <Field label="Адрес ComfyUI" error={errors.comfyUrl} hint="Если ComfyUI запущен на этом компьютере, обычно это http://127.0.0.1:8188.">
                <TextSetting mono value={d.comfyUrl} placeholder="http://127.0.0.1:8188" onCommit={(value) => { void save({ comfyUrl: value }); }} />
              </Field>
              <AdvancedHead />
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

            {section === "integrations" && <IntegrationsPane api={api} d={d} save={save} onChanged={() => setSavedAt(Date.now())} />}

            {section === "phone" && !isPhone && <PhonePane api={api} />}
            {section === "data" && <>
              <Field label="Папка с данными" hint={<span className="mono">{d.dataDir}</span>}>
                <div className="row">
                  <Button icon="folder" onClick={() => { void api.open_data_folder("folder"); }}>Открыть папку</Button>
                  <Button icon="file" onClick={() => { void api.open_data_folder("log"); }}>Открыть журнал</Button>
                </div>
              </Field>
              <p className="pane-note">Тут лежат настройки, все чаты, журналы и нарисованные картинки. Настройки общие с обычным окном программы.</p>
              <Field label="Сброс настроек" hint="Вернёт рекомендуемые настройки: промпт, голос, микрофон, параметры модели, интеграции, оформление. Чаты, скачанные модели и выбранные модели останутся.">
                <ResetButton api={api} onReset={() => { setTheme("system"); setFontChoice(FONT_CHOICES[0][0]); void reload(); setSavedAt(Date.now()); }} />
              </Field>
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

function DeleteButton({ onDelete, disabled = false, compact = false }: { onDelete: () => Promise<void>; disabled?: boolean; compact?: boolean }) {
  const [armed, setArmed] = useState(false);
  const [working, setWorking] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(timer);
  }, [armed]);
  const remove = () => { setWorking(true); void onDelete().finally(() => { setWorking(false); setArmed(false); }); };
  if (compact) {
    return <IconButton icon="trash" size={15} className={armed ? "delete-armed" : ""} disabled={disabled || working}
      label={armed ? "Нажми ещё раз, чтобы удалить" : "Удалить с диска"} onClick={() => { if (armed) remove(); else setArmed(true); }} />;
  }
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

function ModelList({ api, models, current, onPick, onTune, onOpenHub }: { api: WebApi; models: string[]; current: string; onPick: (name: string) => void; onTune: (name: string) => void; onOpenHub: () => void }) {
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const ref = useOutsideClose(open, () => setOpen(false));
  const usage = useDiskUsage(api, `${revision}-${models.length}`);
  const sizes = new Map((usage?.models ?? []).map((item) => [item.name, item.bytes]));
  const groups = groupModels(models);
  return (
    <div className="menu-anchor model-picker" ref={ref}>
      <button type="button" className="model-picker-btn" onClick={() => setOpen((value) => !value)}>
        <ModelLogo api={api} name={current} size={20} />
        <span className="disk-name">{shortModel(current) || "Модель не выбрана"}</span>
        {sizes.has(current) && <small className="model-size">{gigabytes(sizes.get(current)!)}</small>}
        <Icon name="chevronDown" size={14} />
      </button>
      {open && (
        <div className="menu menu-left model-picker-menu">
          <div className="menu-list">
            {groups.map(([title, names]) => [
              groups.length > 1 && <div key={title} className="menu-title">{title}</div>,
              ...names.map((name) => (
                <div key={name} className={`model-option ${name === current ? "on" : ""}`}>
                  <button type="button" className="model-pick" title={name} onClick={() => { onPick(name); setOpen(false); }}>
                    <ModelLogo api={api} name={name} size={18} />
                    <span className="disk-name">{shortModel(name)}</span>
                    {sizes.has(name) && <small className="model-size">{gigabytes(sizes.get(name)!)}</small>}
                  </button>
                  <IconButton icon="settings" size={15} className="model-tune" label="Настроить модель" onClick={() => { setOpen(false); onTune(name); }} />
                  {sizes.has(name) && <DeleteButton compact onDelete={() => api.delete_model(name).then((reply) => { setError(reply.ok ? "" : reply.error ?? "Не удалось удалить."); setRevision((value) => value + 1); })} />}
                </div>
              )),
            ])}
          </div>
          <div className="menu-divider" />
          <button type="button" onClick={() => { setOpen(false); onOpenHub(); }}><Icon name="download" size={16} /><span>Скачать с Hugging Face…</span></button>
        </div>
      )}
      {error && <p className="pane-note">{error}</p>}
    </div>
  );
}

function VoiceModels({ api, onOpenHub, chatMemory, context, onChanged }: { api: WebApi; onOpenHub: (kind: VoiceKind) => void; chatMemory?: MemoryEstimate | null; context: number; onChanged: () => void }) {
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

  const select =(kind: VoiceKind, id: string) => {
    setError("");
    void api.voice_select(kind, id).then((result) => {
      if (result.error) setError(result.error);
      if (result.ok && result.restart) setRestartFor(kind);
      void load(); onChanged();
    });
  };
  const row = (kind: VoiceKind, model: VoiceModel) => {
    const selected = status[kind].selected === model.id;
    return (
      <div key={model.id} className={`voice-model ${selected ? "selected" : ""}`}>
        <ModelLogo api={api} name={model.title} size={32} />
        <div className="voice-model-copy">
          <strong>{model.title}</strong>
          <small>{model.note}</small>
          <small className="voice-model-meta">{model.engine} · {model.size} · {model.memory ? `в памяти ≈ ${gigabytes(model.memory)}` : "на процессоре"} · {model.license} · {model.source}</small>
        </div>
        <div className="voice-model-action">
          {selected ? <span className="unit"><Icon name="check" size={14} /> Используется</span>
            : <Button onClick={() => select(kind, model.id)}>Использовать</Button>}
          <DeleteButton onDelete={() => api.voice_delete(kind, model.id).then((reply) => {
            setError(reply.ok ? "" : reply.error ?? "Не удалось удалить."); setRevision((value) => value + 1); void load(); onChanged();
          })} />
        </div>
      </div>
    );
  };
  const inUse = (kind: VoiceKind) => status[kind].models.find((model) => model.id === status[kind].selected);
  const voice = (["asr", "tts"] as VoiceKind[]).map((kind) => inUse(kind)?.memory ?? 0).reduce((sum, bytes) => sum + bytes, 0);
  return <>
    {chatMemory && <MemoryBar gpu={status.gpu} speed={chatMemory} label={callMemoryLabel(context)} parts={{ ...chatMemory, voice }} />}
    {VOICE_KINDS.map(({ kind, title, hint }) => (
      <Field key={kind} label={title} hint={status[kind].engine ? hint : <>{hint} {status[kind].engineNote}</>}>
        {status[kind].models.length > 0 && <div className="voice-models">{status[kind].models.map((model) => row(kind, model))}</div>}
        <div className="voice-search-open"><Button icon="search" onClick={() => onOpenHub(kind)}>Найти модель на Hugging Face…</Button></div>
      </Field>
    ))}
    {error && <p className="pane-note">{error}</p>}
    {restartFor && <ConfirmDialog title="Нужен перезапуск"
      text={`Модель ${restartFor === "tts" ? "озвучки" : "распознавания"} сменена. Чтобы она заработала, программу нужно перезапустить. Чаты и настройки сохранятся.`}
      confirmLabel="Перезапустить сейчас" cancelLabel="Позже" onClose={() => setRestartFor(null)}
      onConfirm={() => { void api.restart_app(); }} />}
    {usage && (usage.voiceModels > 0 || usage.engines.length > 0) && (
      <Field label="Место на диске" hint="Модели удаляются кнопкой «Удалить» выше. Движок, который не нужен ни одной скачанной модели, можно удалить: он скачается снова вместе с моделью для него.">
        <div className="disk-list">
          <div className="disk-row"><span className="disk-name">Голосовые модели</span><span className="disk-size">{gigabytes(usage.voiceModels)}</span></div>
          {usage.engines.map((item) => (
            <div key={item.id} className="disk-row">
              <span className="disk-name">Движок · {item.label}</span><span className="disk-size">{gigabytes(item.bytes)}</span>
              {item.removable && <DeleteButton compact disabled={running} onDelete={() => api.voice_engine_delete(item.id).then((reply) => {
                setError(reply.ok ? "" : reply.error ?? "Не удалось удалить."); setRevision((value) => value + 1); void load();
              })} />}
            </div>
          ))}
          <div className="disk-row total"><span className="disk-name">Всего</span><span className="disk-size">{gigabytes(usage.voiceModels + usage.engines.reduce((sum, item) => sum + item.bytes, 0))}</span></div>
        </div>
      </Field>
    )}
  </>;
}
