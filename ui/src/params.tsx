import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import type { ModelParams, ParamValue, WebApi } from "./bridge";
import { Icon } from "./icons";
import { AdvancedHead, Button, Field, IconButton, ModelLogo, shortModel, Switch, Toggle } from "./ui";

type Kind = "int" | "float" | "choice" | "bool" | "context";
interface Param { key: string; label: string; hint: string; kind: Kind; step?: number; unit?: string; names?: Record<string, string> }
interface Group { title: string; note?: string; open?: boolean; local?: boolean; params: Param[] }

const CONTEXT_MIN = 2048, CONTEXT_MAX = 1048576;

const toSlider = (value: number) => Math.round(100 * Math.log2(value / CONTEXT_MIN) / Math.log2(CONTEXT_MAX / CONTEXT_MIN));
const fromSlider = (position: number) => Math.round(CONTEXT_MIN * 2 ** (position / 100 * Math.log2(CONTEXT_MAX / CONTEXT_MIN)) / 256) * 256;

const GROUPS: Group[] = [
  {
    title: "Основное", open: true,
    params: [
      { key: "ctx_size", label: "Контекст", hint: "Сколько текста модель помнит за раз. Больше — длиннее память разговора, но больше видеопамяти. Модель перезагрузится.", kind: "context" },
      { key: "temperature", label: "Температура", hint: "Ниже — точнее и однообразнее, выше — творческее и случайнее.", kind: "float", step: 0.05 },
      { key: "max_tokens", label: "Максимум токенов в ответе", hint: "−1 — без ограничения.", kind: "int" },
      { key: "compress_context", label: "Сжимать раннюю часть разговора", hint: "Когда разговор перестаёт помещаться в контекст, его начало сжимается моделью в краткое содержание, чтобы она не забывала важное.", kind: "bool" },
    ],
  },
  {
    title: "Выбор слов",
    params: [
      { key: "top_p", label: "Top-P", hint: "Модель выбирает из самых вероятных слов, пока их сумма не наберёт эту долю.", kind: "float", step: 0.01 },
      { key: "top_k", label: "Top-K", hint: "Выбор только из K самых вероятных слов. 0 — без ограничения.", kind: "int" },
      { key: "min_p", label: "Min-P", hint: "Отбрасывает слова, которые намного менее вероятны, чем лучшее.", kind: "float", step: 0.01 },
      { key: "typical_p", label: "Typical-P", hint: "1 — выключено.", kind: "float", step: 0.01 },
      { key: "xtc_probability", label: "XTC: вероятность", hint: "Иногда убирает самые предсказуемые слова — текст живее. 0 — выключено.", kind: "float", step: 0.05 },
      { key: "xtc_threshold", label: "XTC: порог", hint: "Какие слова считаются слишком предсказуемыми.", kind: "float", step: 0.01 },
      { key: "mirostat", label: "Mirostat", hint: "Держит «удивительность» текста постоянной. 0 — выключен, 2 — версия 2.0.", kind: "int" },
      { key: "mirostat_tau", label: "Mirostat: цель", hint: "Желаемая удивительность.", kind: "float", step: 0.5 },
      { key: "mirostat_eta", label: "Mirostat: скорость", hint: "Как быстро он подстраивается.", kind: "float", step: 0.01 },
      { key: "seed", label: "Зерно (seed)", hint: "−1 — случайное. Одинаковое зерно даёт одинаковые ответы на одинаковые вопросы.", kind: "int" },
    ],
  },
  {
    title: "Повторы",
    params: [
      { key: "repeat_penalty", label: "Штраф за повторы", hint: "1 — выключен. 1.05–1.15 помогает, если модель зацикливается.", kind: "float", step: 0.01 },
      { key: "repeat_last_n", label: "Окно повторов", hint: "Сколько последних токенов учитывает штраф. −1 — весь контекст.", kind: "int" },
      { key: "presence_penalty", label: "Штраф за присутствие", hint: "Подталкивает к новым темам.", kind: "float", step: 0.05 },
      { key: "frequency_penalty", label: "Штраф за частоту", hint: "Снижает частые слова.", kind: "float", step: 0.05 },
      { key: "dry_multiplier", label: "DRY", hint: "Мягко запрещает дословно повторять длинные куски. 0 — выключен, 0.8 — обычное значение.", kind: "float", step: 0.1 },
      { key: "dry_base", label: "DRY: основа", hint: "Как быстро растёт штраф с длиной повтора.", kind: "float", step: 0.05 },
      { key: "dry_allowed_length", label: "DRY: допустимая длина", hint: "Повторы короче этого не штрафуются.", kind: "int" },
    ],
  },
  {
    title: "Лимиты памяти", local: true, note: "0 — без ограничения. Пригодится, чтобы оставить место для озвучки, распознавания или игры.",
    params: [
      { key: "vram_limit_gb", label: "Максимум видеопамяти", hint: "Модель займёт не больше; остальные слои пойдут в оперативную память.", kind: "float", step: 0.5, unit: "ГБ" },
      { key: "ram_limit_gb", label: "Максимум оперативной памяти", hint: "Если модель не помещается в лимит, она не загрузится и программа объяснит почему.", kind: "float", step: 1, unit: "ГБ" },
    ],
  },
  {
    title: "Загрузка модели", local: true, note: "Эти параметры применяются при следующем ответе: модель перезагрузится.",
    params: [
      { key: "gpu_layers", label: "Слоёв на видеокарте", hint: "−1 — сколько поместится (рекомендуется). 0 — всё на процессоре.", kind: "int" },
      { key: "flash_attn", label: "Flash Attention", hint: "Быстрее и экономнее по памяти на видеокартах NVIDIA.", kind: "choice", names: { auto: "Авто", on: "Вкл.", off: "Выкл." } },
      { key: "kv_type", label: "Сжатие контекста в памяти (KV-кэш)", hint: "q8_0 почти без потерь вдвое экономит память контекста, q4_0 — вчетверо, но может ухудшить ответы.", kind: "choice", names: { f16: "Без сжатия (f16)", q8_0: "q8_0", q4_0: "q4_0" } },
      { key: "speculative", label: "Ускорение (спекулятивное декодирование)", hint: "Авто: у моделей со встроенными MTP-головами (Qwen3.5/3.6 MTP, GLM) ответы идут примерно в 1,4 раза быстрее, текст тот же. N-граммы дополнительно ускоряют повторяющийся текст, например правки кода.", kind: "choice", names: { auto: "Авто", ngram: "Авто + n-граммы", off: "Выкл." } },
      { key: "n_cpu_moe", label: "Экспертов MoE на процессоре", hint: "Для MoE-моделей (A3B, A4B…): веса экспертов первых N слоёв держатся в ОЗУ. Освобождает видеопамять почти без потери скорости.", kind: "int" },
      { key: "threads", label: "Потоки процессора", hint: "0 — выбрать автоматически.", kind: "int" },
      { key: "batch", label: "Размер пакета", hint: "Сколько токенов запроса обрабатывается за раз. Больше — быстрее чтение длинного текста, но больше памяти.", kind: "int" },
      { key: "ubatch", label: "Физический пакет", hint: "Часть пакета, которая считается на видеокарте за раз.", kind: "int" },
      { key: "mmap", label: "Отображать файл в память (mmap)", hint: "Быстрая загрузка; выключи, если модель на медленном диске.", kind: "bool" },
      { key: "mlock", label: "Не выгружать из ОЗУ (mlock)", hint: "Windows не будет выгружать модель на диск. Нужна свободная память.", kind: "bool" },
    ],
  },
];

/** What a remote service actually receives; the rest would do nothing there. */
const REMOTE_PARAMS = new Set(["ctx_size", "compress_context", "temperature", "max_tokens", "top_p", "top_k", "min_p", "seed", "repeat_penalty", "presence_penalty", "frequency_penalty"]);

const contextName = (value: number) => (value >= CONTEXT_MAX ? "1M" : value >= 1024 ? `${Math.round(value / 1024)}K` : String(value));

export function ModelParamsPane({ api, children }: { api: WebApi; children?: ReactNode }) {
  const [data, setData] = useState<ModelParams | null>(null);
  const load = useCallback(() => api.model_params("").then(setData), [api]);
  useEffect(() => { void load(); }, [load]);
  if (!data) return <p className="pane-note">Загрузка…</p>;
  return <>
    <Field label="Названия чатов">
      <Toggle label="Модель сама называет новые чаты" checked={data.autoTitles} onChange={(next) => { void api.set_auto_titles(next).then(() => load()); }} />
    </Field>
    <AdvancedHead />
    {children}
  </>;
}

/** One model, or the common settings when scope is "*". */
export function ModelSettingsPage({ api, scope, onBack, onSaved }: { api: WebApi; scope: string; onBack: () => void; onSaved: () => void }) {
  const [data, setData] = useState<ModelParams | null>(null);
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  const head = useRef<HTMLDivElement>(null);
  const load = useCallback(() => api.model_params(scope).then(setData), [api, scope]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { head.current?.closest(".settings-fields")?.scrollTo(0, 0); }, [scope]);

  const common = scope === "*";
  const changes = !data ? {} : common ? data.all : data.own;
  const base = !data ? {} : common ? data.defaults : { ...data.defaults, ...data.all };
  const shown = { ...base, ...changes };
  const save = (values: Record<string, ParamValue>, replace = false) =>
    api.set_model_params(scope, values, replace).then(() => { onSaved(); void load(); });
  const reset = (key: string) => { const rest = { ...changes }; delete rest[key]; void save(rest, true); };
  const visible = (param: Param) => !data?.cloud || REMOTE_PARAMS.has(param.key);
  const groups = GROUPS.filter((group) => !(group.local && data?.cloud)).map((group) => ({ ...group, params: group.params.filter(visible) })).filter((group) => group.params.length);
  const changedCount = Object.keys(changes).length;

  const control = (param: Param) => {
    const value = shown[param.key];
    if (param.kind === "context") return <ContextSlider value={Number(value)} onCommit={(next) => { void save({ ctx_size: next }); }} />;
    if (param.kind === "bool") return <Switch label={param.label} checked={Boolean(value)} onChange={(next) => { void save({ [param.key]: next }); }} />;
    if (param.kind === "choice") return (
      <select className="select" value={String(value)} onChange={(event) => { void save({ [param.key]: event.target.value }); }}>
        {(data?.choices[param.key] ?? []).map((choice) => <option key={choice} value={choice}>{param.names?.[choice] ?? choice}</option>)}
      </select>
    );
    const limits = data?.limits[param.key];
    return <>
      <input type="number" className="input mono" aria-label={param.label} step={param.step ?? 1} min={limits?.[0]} max={limits?.[1]}
        defaultValue={String(value)} key={`${param.key}-${String(value)}`}
        onBlur={(event) => { if (event.target.value !== String(value) && event.target.value !== "") void save({ [param.key]: Number(event.target.value) }); }}
        onKeyDown={(event) => { if (event.key === "Enter") (event.target as HTMLInputElement).blur(); }} />
      {param.unit && <span className="unit">{param.unit}</span>}
    </>;
  };

  const row = (param: Param) => {
    const changed = param.key in changes;
    const label = `${common ? "По умолчанию" : "Как в общих"}: ${String(base[param.key])}`;
    return (
      <div key={param.key} className={`param-row ${param.kind === "context" ? "wide" : ""} ${changed ? "changed" : ""}`}>
        <div className="param-name"><span>{param.label}</span><small>{param.hint}</small></div>
        <div className="param-control">
          {control(param)}
          <span className="param-reset">{changed && <IconButton icon="retry" size={13} label={label} onClick={() => reset(param.key)} />}</span>
        </div>
      </div>
    );
  };

  return (
    <div className="model-page">
      <div className="model-page-head" ref={head}>
        <IconButton icon="arrowRight" className="flip" label="Назад" onClick={onBack} />
        {common ? <Icon name="box" size={18} /> : <ModelLogo api={api} name={scope} size={20} />}
        <div className="model-page-title">
          {common ? <strong>Общие настройки</strong> : <strong title={scope} data-i18n-skip>{shortModel(scope)}</strong>}
          <small>{common ? "Действуют на все модели, кроме значений, заданных для конкретной модели." : "Подсвечено то, что отличается от общих настроек."}</small>
        </div>
        {changedCount > 0 && <Button kind="ghost" icon="refresh" onClick={() => { void save({}, true); }}>Сбросить</Button>}
      </div>
      {!data ? <p className="pane-note">Загрузка…</p> : groups.map((group) => {
        const count = group.params.filter((param) => param.key in changes).length;
        const open = opened[group.title] ?? (Boolean(group.open) || count > 0);
        return (
          <section key={group.title} className="param-section">
            <button type="button" className="param-section-head" aria-expanded={open} onClick={() => setOpened((current) => ({ ...current, [group.title]: !open }))}>
              <Icon name={open ? "chevronDown" : "chevronRight"} size={14} />
              <span>{group.title}</span>
              {count > 0 && <span className="tune-count">изменено: {count}</span>}
            </button>
            {open && <>
              {group.note && <p className="pane-note">{group.note}</p>}
              {group.params.map(row)}
            </>}
          </section>
        );
      })}
    </div>
  );
}

function ContextSlider({ value, onCommit }: { value: number; onCommit: (value: number) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = (next: number) => {
    const clean = Math.max(512, Math.min(1048576, Math.round(next || 0)));
    setDraft(clean);
    if (clean !== value) onCommit(clean);
  };
  return (
    <div className="context-slider">
      <input type="range" min={0} max={100} step={1} value={toSlider(Math.max(CONTEXT_MIN, draft))} aria-label="Контекст"
        onChange={(event) => setDraft(fromSlider(Number(event.target.value)))}
        onPointerUp={() => commit(draft)} onKeyUp={() => commit(draft)} />
      <input type="number" className="input mono" min={512} max={1048576} step={256} value={draft}
        onChange={(event) => setDraft(Number(event.target.value))} onBlur={() => commit(draft)}
        onKeyDown={(event) => { if (event.key === "Enter") commit(draft); }} />
      <span className="unit">токенов · {contextName(draft)}</span>
    </div>
  );
}
