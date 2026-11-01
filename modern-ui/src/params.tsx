import { useCallback, useEffect, useState } from "react";
import type { ModelParams, ParamValue, WebApi } from "./bridge";
import { Button, Field, Switch, Toggle } from "./ui";

/** Every llama.cpp parameter of the model, grouped, with presets; changes go to all models or to the chosen one. */
type Kind = "int" | "float" | "choice" | "bool";
interface Param { key: string; label: string; hint: string; kind: Kind; step?: number; unit?: string; names?: Record<string, string> }

const CONTEXT_MIN = 2048, CONTEXT_MAX = 262144;
// the slider moves on a logarithmic scale (each step doubles the context every 1/7 of its length)
const toSlider = (value: number) => Math.round(100 * Math.log2(value / CONTEXT_MIN) / Math.log2(CONTEXT_MAX / CONTEXT_MIN));
const fromSlider = (position: number) => Math.round(CONTEXT_MIN * 2 ** (position / 100 * Math.log2(CONTEXT_MAX / CONTEXT_MIN)) / 256) * 256;
const GROUPS: { title: string; note: string; params: Param[] }[] = [
  {
    title: "Загрузка модели", note: "Эти параметры применяются при следующем ответе: модель перезагрузится.",
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
  {
    title: "Лимиты памяти", note: "0 — без ограничения. Пригодится, чтобы оставить место для озвучки, распознавания или игры.",
    params: [
      { key: "vram_limit_gb", label: "Максимум видеопамяти", hint: "Модель займёт не больше; остальные слои пойдут в оперативную память.", kind: "float", step: 0.5, unit: "ГБ" },
      { key: "ram_limit_gb", label: "Максимум оперативной памяти", hint: "Если модель не помещается в лимит, она не загрузится и программа объяснит почему.", kind: "float", step: 1, unit: "ГБ" },
    ],
  },
  {
    title: "Ответы", note: "Применяются сразу, без перезагрузки модели.",
    params: [
      { key: "temperature", label: "Температура", hint: "Ниже — точнее и однообразнее, выше — творческее и случайнее.", kind: "float", step: 0.05 },
      { key: "top_p", label: "Top-P", hint: "Модель выбирает из самых вероятных слов, пока их сумма не наберёт эту долю.", kind: "float", step: 0.01 },
      { key: "top_k", label: "Top-K", hint: "Выбор только из K самых вероятных слов. 0 — без ограничения.", kind: "int" },
      { key: "min_p", label: "Min-P", hint: "Отбрасывает слова, которые намного менее вероятны, чем лучшее.", kind: "float", step: 0.01 },
      { key: "typical_p", label: "Typical-P", hint: "1 — выключено.", kind: "float", step: 0.01 },
      { key: "repeat_penalty", label: "Штраф за повторы", hint: "1 — выключен. 1.05–1.15 помогает, если модель зацикливается.", kind: "float", step: 0.01 },
      { key: "repeat_last_n", label: "Окно повторов", hint: "Сколько последних токенов учитывает штраф. −1 — весь контекст.", kind: "int" },
      { key: "presence_penalty", label: "Штраф за присутствие", hint: "Подталкивает к новым темам.", kind: "float", step: 0.05 },
      { key: "frequency_penalty", label: "Штраф за частоту", hint: "Снижает частые слова.", kind: "float", step: 0.05 },
      { key: "dry_multiplier", label: "DRY", hint: "Мягко запрещает дословно повторять длинные куски. 0 — выключен, 0.8 — обычное значение.", kind: "float", step: 0.1 },
      { key: "dry_base", label: "DRY: основа", hint: "Как быстро растёт штраф с длиной повтора.", kind: "float", step: 0.05 },
      { key: "dry_allowed_length", label: "DRY: допустимая длина", hint: "Повторы короче этого не штрафуются.", kind: "int" },
      { key: "xtc_probability", label: "XTC: вероятность", hint: "Иногда убирает самые предсказуемые слова — текст живее. 0 — выключено.", kind: "float", step: 0.05 },
      { key: "xtc_threshold", label: "XTC: порог", hint: "Какие слова считаются слишком предсказуемыми.", kind: "float", step: 0.01 },
      { key: "mirostat", label: "Mirostat", hint: "Держит «удивительность» текста постоянной. 0 — выключен, 2 — версия 2.0.", kind: "int" },
      { key: "mirostat_tau", label: "Mirostat: цель", hint: "Желаемая удивительность.", kind: "float", step: 0.5 },
      { key: "mirostat_eta", label: "Mirostat: скорость", hint: "Как быстро он подстраивается.", kind: "float", step: 0.01 },
      { key: "seed", label: "Зерно (seed)", hint: "−1 — случайное. Одинаковое зерно даёт одинаковые ответы на одинаковые вопросы.", kind: "int" },
      { key: "max_tokens", label: "Максимум токенов в ответе", hint: "−1 — без ограничения.", kind: "int" },
    ],
  },
];
const contextName = (value: number) => (value >= 1024 ? `${Math.round(value / 1024)}K` : String(value));

export function ModelParamsPane({ api, model, onSaved }: { api: WebApi; model: string; onSaved: () => void }) {
  const [data, setData] = useState<ModelParams | null>(null);
  const [scope, setScope] = useState<"*" | "model">("*");
  const load = useCallback(() => api.model_params(model).then(setData), [api, model]);
  useEffect(() => { void load(); }, [load]);
  if (!data) return <p className="pane-note">Загрузка…</p>;

  const target = scope === "*" ? "*" : data.model;
  const changes = scope === "*" ? data.all : data.own;
  const base = scope === "*" ? data.defaults : { ...data.defaults, ...data.all };
  const shown = { ...base, ...changes };
  const save = (values: Record<string, ParamValue>, replace = false) =>
    api.set_model_params(target, values, replace).then(() => { onSaved(); void load(); });
  const changedCount = Object.keys(changes).length;

  const input = (param: Param) => {
    const value = shown[param.key];
    const changed = param.key in changes;
    const limits = data.limits[param.key];
    if (param.kind === "bool") return <Switch label={changed ? "изменено" : ""} checked={Boolean(value)} onChange={(next) => { void save({ [param.key]: next }); }} />;
    if (param.kind === "choice") return (
      <select className="select" value={String(value)} onChange={(event) => { void save({ [param.key]: event.target.value }); }}>
        {(data.choices[param.key] ?? []).map((choice) => <option key={choice} value={choice}>{param.names?.[choice] ?? choice}</option>)}
      </select>
    );
    return (
      <div className="param-number">
        <input type="number" className={`input mono ${changed ? "changed" : ""}`} step={param.step ?? 1} min={limits?.[0]} max={limits?.[1]}
          defaultValue={String(value)} key={`${target}-${param.key}-${String(value)}`}
          onBlur={(event) => { if (event.target.value !== String(value) && event.target.value !== "") void save({ [param.key]: Number(event.target.value) }); }}
          onKeyDown={(event) => { if (event.key === "Enter") (event.target as HTMLInputElement).blur(); }} />
        {param.unit && <span className="unit">{param.unit}</span>}
        {changed && <button type="button" className="link-btn" onClick={() => {
          const rest = { ...changes }; delete rest[param.key]; void save(rest, true);
        }}>по умолчанию ({String(base[param.key])})</button>}
      </div>
    );
  };

  return <>
    <Field label="Для каких моделей" hint={scope === "*" ? "Изменения действуют на все модели, кроме тех, где заданы свои." : `Только для ${data.model}; поверх общих настроек.`}>
      <div className="segmented">
        <button type="button" className={scope === "*" ? "on" : ""} onClick={() => setScope("*")}>Все модели</button>
        <button type="button" className={scope === "model" ? "on" : ""} disabled={!data.model} onClick={() => setScope("model")}>Только эта модель</button>
      </div>
    </Field>
    <Field label="Контекст" hint="Сколько текста модель помнит за раз. Больше — длиннее память разговора, но больше видеопамяти. Модель перезагрузится.">
      <ContextSlider value={Number(shown.ctx_size)} onCommit={(value) => { void save({ ctx_size: value }); }} />
    </Field>
    <Field label="Память разговора" hint="Когда разговор перестаёт помещаться в контекст, его начало сжимается моделью в краткое содержание, чтобы она не забывала важное.">
      <Toggle label="Сжимать раннюю часть разговора" checked={Boolean(shown.compress_context)} onChange={(next) => { void save({ compress_context: next }); }} />
      <Toggle label="Модель сама называет новые чаты" checked={data.autoTitles} onChange={(next) => { void api.set_auto_titles(next).then(() => load()); }} />
    </Field>
    {GROUPS.map((group) => (
      <section key={group.title} className="param-group">
        <h5>{group.title}</h5>
        <p className="pane-note">{group.note}</p>
        {group.params.map((param) => <Field key={param.key} label={param.label} hint={param.hint}>{input(param)}</Field>)}
      </section>
    ))}
    {changedCount > 0 && <Button kind="ghost" onClick={() => { void save({}, true); }}>Сбросить изменения {scope === "*" ? "для всех моделей" : "этой модели"}</Button>}
  </>;
}

/** The context size: a slider for quick choice and a field for an exact number; saved on release. */
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
