import { useCallback, useEffect, useState } from "react";
import { isPhone } from "./bridge";
import type { DiskUsage, EngineState, MemoryEstimate, ModelMemory, SettingsDetails, VoiceKind, VoiceModel, VoiceStatus, WebApi } from "./bridge";
import { Icon, type IconName } from "./icons";
import { ConfirmDialog, ListenSettings } from "./dialogs";
import { LANGUAGES, type Language } from "./i18n";
import { ModelParamsPane, ModelSettingsPage } from "./params";
import { PhonePane } from "./pairing";
import { UpdatePane } from "./update";
import { IntegrationsPane } from "./providers";
import { ToolsPane } from "./tools";
import { MemoryPane } from "./memory";
import { AdvancedHead, Button, callMemoryLabel, Decor, Field, gigabytes, groupModels, IconButton, MemoryBar, ModelLogo, MotionPresence, prefetchShared, SelectionMarker, shortModel, Switch, TextSetting, Toggle, useOutsideClose, useShared } from "./ui";
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
let lastDetails: SettingsDetails | null = null;

/** Fetches what every settings tab shows, so tabs open filled. Called once after start and whenever settings open. */
export function prefetchSettings(api: WebApi, model: string) {
  void api.settings_details().then((next) => { lastDetails = next; }).catch(() => {});
  prefetchShared([
    [`model_memory:${model}`, () => api.model_memory(model ? [model] : [])],
    ["disk", () => api.disk_usage()],
    ["voice", () => api.voice_status()],
    ["memory", () => api.memory_status()],
    ["tools", () => api.tools_status()],
    ["providers", () => api.providers_status().then((reply) => reply.providers)],
    ["params:", () => api.model_params("")],
    ["update", () => api.update_status()],
  ]);
}

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
  const [details, setDetails] = useState<SettingsDetails | null>(lastDetails);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [savedAt, setSavedAt] = useState(0);
  const [showSaved, setShowSaved] = useState(false);
  const model = state.settings.model;
  const [memory] = useShared<ModelMemory>(`model_memory:${model}`, () => api.model_memory(model ? [model] : []));
  useEffect(() => { prefetchSettings(api, model); }, [api]);
  const modelEstimate = memory?.models[model];

  const reload = useCallback(() => api.settings_details().then((next) => { lastDetails = next; setDetails(next); }), [api]);
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
  return (
    <div className="modal-backdrop">
      <div className="modal settings" role="dialog" aria-modal="true" aria-label="Настройки" ref={ref}>
        <nav className="settings-nav">
          <h3>Настройки</h3>
          <SelectionMarker selected={section} />
          {SECTIONS.filter((item) => !(isPhone && item.id === "phone")).map((item) => (
            <button key={item.id} type="button" aria-current={section === item.id ? "page" : undefined} className={section === item.id ? "on" : ""} onClick={() => { setSection(item.id); setModelPage(null); }}>
              <Icon name={item.icon} size={17} />{item.title}
            </button>
          ))}
          <Decor corner="bl" className="settings-decor" />
          <span className={`saved-note ${showSaved ? "visible" : ""}`}><Icon name="check" size={14} /> Сохранено</span>
        </nav>
        <div className="settings-pane">
          <IconButton icon="close" label="Закрыть (Esc)" className="settings-close" onClick={onClose} />
          {!d ? null : <div className="settings-fields tab-view" key={modelPage === null ? section : `model:${modelPage}`} data-smooth-wheel>
            {section === "look" && <>
              <Field label="Язык / Language" hint="Модель тоже будет отвечать на нём.">
                <div className="segmented wrap sliding-selection">
                  <SelectionMarker selected={language} />
                  {LANGUAGES.map(([value, label]) => (
                    <button key={value} type="button" className={language === value ? "on" : ""} onClick={() => setLanguage(value)} data-i18n-skip>{label}</button>
                  ))}
                </div>
              </Field>
              {FONT_CHOICES.length > 1 && <Field label="Шрифт">
                <div className="segmented wrap sliding-selection">
                  <SelectionMarker selected={fontChoice} />
                  {FONT_CHOICES.map(([value, label, family]) => (
                    <button key={value} type="button" className={fontChoice === value ? "on" : ""} style={{ fontFamily: family }} onClick={() => setFontChoice(value)}>{label}</button>
                  ))}
                </div>
              </Field>}
              <Field label="Тема">
                <ThemeSelect theme={theme} setTheme={setTheme} />
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
            {section === "model" && modelPage !== null && <ModelSettingsPage key={modelPage} api={api} scope={modelPage}
              onBack={() => setModelPage(null)} onSaved={() => setSavedAt(Date.now())} />}
            {section === "model" && modelPage === null && <>
              <Field label="Модель" hint={state.status}>
                <ModelList api={api} models={state.models} current={model} onOpenHub={onOpenHub}
                  onPick={(name) => { void api.set_model(name).then(() => setSavedAt(Date.now())); }} onTune={setModelPage} />
                {modelEstimate && memory && <MemoryBar gpu={memory.gpu} speed={modelEstimate} label={callMemoryLabel(memory.context)}
                  parts={{ ...modelEstimate, voice: memory.voiceCall }} />}
                <div className="row model-tune-open">
                  {model && <Button kind="ghost" icon="settings" onClick={() => setModelPage(model)}>Настроить эту модель</Button>}
                </div>
              </Field>
              <Field label="Режим для тяжёлых моделей" hint="Для очень больших моделей: в памяти остаются только сама модель с её контекстом и модель долговременной памяти. Выключаются звонок, голосовой ввод, озвучка, картинки и видео, поиск в интернете, MCP-серверы и другие загруженные модели." error={errors.heavyMode}>
                <Toggle label="Выключить всё, кроме модели" checked={d.heavyMode} onChange={(next) => { void save({ heavyMode: next }); }} />
              </Field>
              <ModelParamsPane api={api}>
              <Field label="Моделей в памяти одновременно" hint="У каждого чата своя модель. Несколько моделей держатся загруженными и могут отвечать в разных чатах одновременно; модель без дела выгружается, если следующая не помещается рядом с ней в видеопамять.">
                <div className="segmented sliding-selection">
                  <SelectionMarker selected={String(d.heavyMode ? 1 : d.maxLoadedModels)} />
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
              <UpdatePane api={api} />
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

function ThemeChip({ colors }: { colors: readonly string[] }) {
  return <span className="theme-chip" style={{ background: colors[0] }}>{colors.slice(1).map((color) => <i key={color} style={{ background: color }} />)}</span>;
}

function ThemeSelect({ theme, setTheme }: { theme: ThemeId; setTheme: (value: ThemeId) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(open, () => setOpen(false));
  const current = THEMES.find(([value]) => value === theme) ?? THEMES[0];
  return (
    <div className="menu-anchor theme-select" ref={ref}>
      <button type="button" className="model-picker-btn" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <ThemeChip colors={current[3]} /><span className="grow">{current[1]}</span><Icon name="chevronDown" size={14} />
      </button>
      <MotionPresence>{open && (
        <div className="menu menu-left theme-menu" role="listbox">
          <div className="menu-list">
            {THEMES.map(([value, label, , colors]) => (
              <button key={value} type="button" role="option" aria-selected={value === theme} className={value === theme ? "selected" : ""} onClick={() => { setTheme(value); setOpen(false); }}>
                <ThemeChip colors={colors} /><span className="grow">{label}</span>{value === theme && <Icon name="check" size={14} />}
              </button>
            ))}
          </div>
        </div>
      )}</MotionPresence>
    </div>
  );
}

function ResetButton({ api, onReset }: { api: WebApi; onReset: () => void }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");
  return <>
    <Button kind="danger" icon="refresh" onClick={() => setAsking(true)}>Сбросить все настройки</Button>
    {error && <p className="pane-note">{error}</p>}
    <MotionPresence>{asking && <ConfirmDialog title="Сбросить настройки?" text="Все настройки вернутся к рекомендуемым. Чаты и скачанные модели не пострадают." confirmLabel="Сбросить" danger
      onClose={() => setAsking(false)} onConfirm={() => { void api.reset_settings().then((result) => { setError(result.ok ? "" : result.error ?? ""); if (result.ok) onReset(); }); }} />}</MotionPresence>
  </>;
}

function DeleteButton({ onDelete, disabled = false }: { onDelete: () => Promise<void>; disabled?: boolean }) {
  const [armed, setArmed] = useState(false);
  const [working, setWorking] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(timer);
  }, [armed]);
  const remove = () => { setWorking(true); void onDelete().finally(() => { setWorking(false); setArmed(false); }); };
  return <IconButton icon="trash" size={15} className={armed ? "delete-icon delete-armed" : "delete-icon"} disabled={disabled || working}
    label={armed ? "Нажми ещё раз, чтобы удалить" : "Удалить с диска"} onClick={() => { if (armed) remove(); else setArmed(true); }} />;
}

function useDiskUsage(api: WebApi, revision: unknown) {
  const [usage, reload] = useShared<DiskUsage>("disk", () => api.disk_usage());
  const first = useState(revision)[0];
  useEffect(() => { if (revision !== first) void reload(); }, [revision]);
  return usage;
}

type PickerModel = { id: string; name: string; logo: string; description?: string; size?: string; removable: boolean };

function ModelPicker({ api, groups, current, onPick, onTune, onDelete, onOpenHub, hubLabel = "Скачать с Hugging Face…" }: {
  api: WebApi; groups: [string, PickerModel[]][]; current?: PickerModel;
  onPick: (id: string) => void; onTune?: (id: string) => void; onDelete: (id: string) => Promise<void>; onOpenHub: () => void; hubLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(open, () => setOpen(false));
  return (
    <div className="menu-anchor model-picker" ref={ref}>
      <button type="button" className="model-picker-btn" aria-expanded={open} title={current?.description} onClick={() => setOpen((value) => !value)}>
        <ModelLogo api={api} name={current?.logo ?? ""} size={20} />
        <span className="disk-name">{current?.name || "Модель не выбрана"}</span>
        {current?.size && <small className="model-size">{current.size}</small>}
        <Icon name="chevronDown" size={14} />
      </button>
      <MotionPresence>{open && (
        <div className="menu menu-left model-picker-menu">
          <div className="menu-list">
            {groups.map(([title, models]) => [
              groups.length > 1 && <div key={title} className="menu-title">{title}</div>,
              ...models.map((model) => (
                <div key={model.id} className={`model-option ${model.id === current?.id ? "on" : ""}`}>
                  <button type="button" className="model-pick" title={model.description ?? model.id}
                    aria-current={model.id === current?.id ? "true" : undefined}
                    onClick={() => { onPick(model.id); setOpen(false); }}>
                    <ModelLogo api={api} name={model.logo} size={18} />
                    <span className="disk-name">{model.name}</span>
                    {model.size && <small className="model-size">{model.size}</small>}
                  </button>
                  {onTune && <IconButton icon="settings" size={15} className="model-tune" label="Настроить модель" onClick={() => { setOpen(false); onTune(model.id); }} />}
                  {model.removable && <DeleteButton onDelete={() => onDelete(model.id)} />}
                </div>
              )),
            ])}
          </div>
          <div className="menu-divider" />
          <button type="button" onClick={() => { setOpen(false); onOpenHub(); }}><Icon name="download" size={16} /><span>{hubLabel}</span></button>
        </div>
      )}</MotionPresence>
    </div>
  );
}

function ModelList({ api, models, current, onPick, onTune, onOpenHub }: { api: WebApi; models: string[]; current: string; onPick: (name: string) => void; onTune: (name: string) => void; onOpenHub: () => void }) {
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const usage = useDiskUsage(api, `${revision}-${models.length}`);
  const sizes = new Map((usage?.models ?? []).map((item) => [item.name, gigabytes(item.bytes)]));
  const modelRow = (name: string): PickerModel => ({ id: name, name: shortModel(name), logo: name, size: sizes.get(name), removable: sizes.has(name) });
  return <>
    <ModelPicker api={api} groups={groupModels(models).map(([title, names]) => [title, names.map(modelRow)])}
      current={current ? modelRow(current) : undefined} onPick={onPick} onTune={onTune} onOpenHub={onOpenHub}
      onDelete={async (id) => {
        const reply = await api.delete_model(id);
        setError(reply.ok ? "" : reply.error ?? "Не удалось удалить.");
        setRevision((value) => value + 1);
      }} />
    {error && <p className="pane-note">{error}</p>}
  </>;
}

function voiceModelInfo(model: VoiceModel) {
  return [model.engine, model.size, model.memory ? `в памяти ≈ ${gigabytes(model.memory)}` : "на процессоре", model.license, model.source]
    .filter(Boolean).join(" · ");
}

function VoiceModels({ api, onOpenHub, chatMemory, context, onChanged }: { api: WebApi; onOpenHub: (kind: VoiceKind) => void; chatMemory?: MemoryEstimate | null; context: number; onChanged: () => void }) {
  const [status, load] = useShared<VoiceStatus>("voice", () => api.voice_status());
  const [error, setError] = useState("");
  const [restartFor, setRestartFor] = useState<VoiceKind | null>(null);
  const [revision, setRevision] = useState(0);
  const usage = useDiskUsage(api, `${revision}-${status?.job.state}`);
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
  const inUse = (kind: VoiceKind) => status[kind].models.find((model) => model.id === status[kind].selected);
  const voice = (["asr", "tts"] as VoiceKind[]).map((kind) => inUse(kind)?.memory ?? 0).reduce((sum, bytes) => sum + bytes, 0);
  return <>
    {chatMemory && <MemoryBar gpu={status.gpu} speed={chatMemory} label={callMemoryLabel(context)} parts={{ ...chatMemory, voice }} />}
    {VOICE_KINDS.map(({ kind, title, hint }) => {
      const group = status[kind];
      const models: PickerModel[] = group.models.map((model) => ({
        id: model.id, name: model.title, logo: model.title, size: model.size, removable: true,
        description: [model.title, model.note, voiceModelInfo(model)].filter(Boolean).join("\n"),
      }));
      const active = inUse(kind);
      return <Field key={kind} label={title} hint={group.engine ? hint : <>{hint} {group.engineNote}</>}>
        <ModelPicker api={api} groups={[[title, models]]} current={models.find((model) => model.id === group.selected)}
          onPick={(id) => { if (id !== group.selected) select(kind, id); }} onOpenHub={() => onOpenHub(kind)} hubLabel="Скачать модель…"
          onDelete={async (id) => {
            const reply = await api.voice_delete(kind, id);
            setError(reply.ok ? "" : reply.error ?? "Не удалось удалить.");
            setRevision((value) => value + 1);
            void load();
            onChanged();
          }} />
        {active && <p className="pane-note voice-model-info">{voiceModelInfo(active)}</p>}
      </Field>;
    })}
    {error && <p className="pane-note">{error}</p>}
    <MotionPresence>{restartFor && <ConfirmDialog title="Нужен перезапуск"
      text={`Модель ${restartFor === "tts" ? "озвучки" : "распознавания"} сменена. Чтобы она заработала, программу нужно перезапустить. Чаты и настройки сохранятся.`}
      confirmLabel="Перезапустить сейчас" cancelLabel="Позже" onClose={() => setRestartFor(null)}
      onConfirm={() => { void api.restart_app(); }} />}</MotionPresence>
    {usage && (usage.voiceModels > 0 || usage.engines.length > 0) && (
      <Field label="Место на диске" hint="Чтобы удалить модель, нажми на корзину в раскрывающемся списке. Неиспользуемый движок можно удалить. Он скачается снова вместе с моделью для него.">
        <div className="disk-list">
          <div className="disk-row"><span className="disk-name">Голосовые модели</span><span className="disk-size">{gigabytes(usage.voiceModels)}</span></div>
          {usage.legacyVoiceModels?.map((model) => (
            <div key={`${model.kind}:${model.id}`} className="disk-row">
              <span className="disk-name" title="Модель другого формата">{model.title}</span><span className="disk-size">{gigabytes(model.bytes)}</span>
              <DeleteButton disabled={running} onDelete={async () => {
                const reply = await api.voice_delete(model.kind, model.id);
                setError(reply.ok ? "" : reply.error ?? "Не удалось удалить.");
                setRevision((value) => value + 1);
                void load();
                onChanged();
              }} />
            </div>
          ))}
          {usage.engines.map((item) => (
            <div key={item.id} className="disk-row">
              <span className="disk-name">Движок · {item.label}</span><span className="disk-size">{gigabytes(item.bytes)}</span>
              {item.removable && <DeleteButton disabled={running} onDelete={() => api.voice_engine_delete(item.id).then((reply) => {
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
