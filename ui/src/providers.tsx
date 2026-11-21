import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ProviderRow, SettingsDetails, WebApi } from "./bridge";
import { translate } from "./i18n";
import { Icon } from "./icons";
import { Button, Field, IconButton, Switch, useShared } from "./ui";
import claudeLogo from "./assets/integrations/claude-color.svg";
import comfyuiLogo from "./assets/integrations/comfyui-color.svg";
import geminiLogo from "./assets/integrations/gemini-color.svg";
import lmstudioLogo from "./assets/integrations/lmstudio.svg";
import ollamaLogo from "./assets/integrations/ollama.svg";
import openaiLogo from "./assets/integrations/openai.svg";
import openrouterLogo from "./assets/integrations/openrouter.svg";
import strataLogo from "./assets/integrations/strata.svg";
import unslothLogo from "./assets/integrations/unsloth.svg";
import vllmLogo from "./assets/integrations/vllm.svg";

const LOGOS: Record<string, string> = {
  comfyui: comfyuiLogo, ollama: ollamaLogo, lmstudio: lmstudioLogo, vllm: vllmLogo, strata: strataLogo, unsloth: unslothLogo,
  openai: openaiLogo, anthropic: claudeLogo, gemini: geminiLogo, openrouter: openrouterLogo,
};

const LOCAL_KEY_HINTS: Record<string, string> = {
  vllm: "Нужен, если на сервере задан API-ключ.",
  strata: "Нужен, если на сервере задан API-ключ.",
  unsloth: "Создай ключ в Unsloth Studio → Settings → API.",
};

function IntegrationLogo({ id }: { id: string }) {
  if (LOGOS[id]) return <span className={`integration-logo ${id}`} dangerouslySetInnerHTML={{ __html: LOGOS[id] }} />;
  return <span className={`integration-logo ${id}`}><Icon name="box" size={18} /></span>;
}

function IntegrationCard({ id, title, hint, state, tone = "", enabled, onToggle, working, tools, children }:
  { id: string; title: string; hint: string; state?: string; tone?: "" | "ok" | "warn" | "empty"; enabled: boolean; onToggle: (value: boolean) => void; working?: boolean; tools?: ReactNode; children?: ReactNode }) {
  return (
    <section className={`provider-card ${tone}`}>
      <div className="provider-head">
        <IntegrationLogo id={id} />
        <div className="provider-title"><strong>{title}</strong><small>{hint}</small></div>
        {state && <span className="provider-state">{state}</span>}
        {tools}
        <Switch label={title} checked={enabled} disabled={working} onChange={onToggle} />
      </div>
      {enabled && children}
    </section>
  );
}

const HINTS: Record<string, string> = {
  openai: "Модели OpenAI по твоему ключу.",
  anthropic: "Модели Claude по твоему ключу.",
  gemini: "Модели Google Gemini по твоему ключу.",
  openrouter: "Много моделей разных компаний через один ключ.",
  custom: "Любой сервер с OpenAI API, например text-generation-webui.",
};
const providerHint = (row: ProviderRow) => row.local ? "Модели с локального или удалённого сервера." : HINTS[row.id] ?? "";

export function IntegrationsPane({ api, d, save, onChanged }:
  { api: WebApi; d: SettingsDetails; save: (patch: Record<string, unknown>) => Promise<unknown>; onChanged: () => void }) {
  const [rows, load] = useShared<ProviderRow[]>("providers", () => api.providers_status().then((reply) => reply.providers));
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setInterval(() => { void load(); }, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const toggle = (key: string) => (value: boolean) => { void save({ integrations: { [key]: value } }); };
  const on = (key: string) => d.integrations[key] !== false;
  const matches = (...texts: string[]) => {
    const needle = query.trim().toLowerCase();

    return !needle || texts.some((text) => `${text} ${translate(text) ?? ""}`.toLowerCase().includes(needle));
  };

  const own = [
    matches("llama.cpp", "Скачанные модели GGUF. Если выключить, они выгрузятся из памяти, а подключённые сервисы продолжат работать.") && (
      <IntegrationCard key="models" id="models" title="llama.cpp" hint="Скачанные модели GGUF. Если выключить, они выгрузятся из памяти, а подключённые сервисы продолжат работать."
        enabled={on("models")} onToggle={toggle("models")} />),
  ].filter(Boolean);

  const shown = (rows ?? []).filter((row) => matches(row.title, providerHint(row), row.id));
  const local = shown.filter((row) => row.local);
  const cloud = shown.filter((row) => !row.local);
  const card = (row: ProviderRow) => <ProviderCard key={row.id} api={api} row={row} onChecked={load}
    onSaved={async () => { await load(); onChanged(); }} />;
  const nothing = !own.length && !local.length && !cloud.length && rows !== null;

  return <>
    <label className="search-field big integration-search"><Icon name="search" size={15} />
      <input placeholder="Найти интеграцию" value={query} onChange={(event) => setQuery(event.target.value)} />
      {query && <button type="button" aria-label="Очистить" onClick={() => setQuery("")}><Icon name="close" size={13} /></button>}
    </label>
    {own.length > 0 && <><h5 className="pane-subhead">Встроенные</h5>{own}</>}
    {local.length > 0 && <><h5 className="pane-subhead">Локальные модели</h5><div className="local-providers">{local.map(card)}</div></>}
    {cloud.length > 0 && <><h5 className="pane-subhead">Облачные модели по своему ключу</h5>{cloud.map(card)}</>}
    {nothing && <p className="pane-note">Ничего не найдено</p>}
    <p className="pane-note">Модели из программ и сервисов появятся в общем списке моделей, и их можно выбрать для любого чата. Ключи хранятся зашифрованными средствами Windows и отправляются только своему сервису.</p>
  </>;
}

function ProviderCard({ api, row, onSaved, onChecked }:
  { api: WebApi; row: ProviderRow; onSaved: () => Promise<void>; onChecked: () => Promise<void> }) {
  const [url, setUrl] = useState(row.url);
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [armed, setArmed] = useState(false);
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState("");
  const [detail, setDetail] = useState("");
  const keyInput = useRef<HTMLInputElement>(null);
  const addressInput = useRef<HTMLInputElement>(null);
  useEffect(() => setUrl(row.url), [row.url]);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(timer);
  }, [armed]);
  const start = () => { setWorking(true); setResult(""); setDetail(""); };
  const failed = () => setResult("Не удалось проверить подключение.");
  const apply = (patch: { enabled?: boolean; url?: string; key?: string }) => {
    if (working) return;
    start();
    void api.set_provider(row.id, patch.enabled ?? null, patch.url ?? null, patch.key ?? null).then((reply) => {
      if (reply.rejected) {
        setResult(row.hasKey ? "Этот ключ не подошёл, остался прежний." : "Этот ключ не подошёл и не сохранён.");
        setDetail(reply.error);
      } else if (patch.key === "") setResult("Ключ удалён.");
      else if (reply.keySaved) setResult("Ключ сохранён.");
      else if (!reply.ok && reply.models === undefined) setResult(`Не получилось: ${reply.error}.`);
      if (patch.key !== undefined && !reply.rejected) { setKey(""); setShowKey(false); }
      return onSaved();
    }).catch(failed).finally(() => setWorking(false));
  };
  const reconnect = () => {
    if (working) return;
    start();
    void api.reconnect_provider(row.id).then((reply) => {
      if (!reply.ok && reply.models === undefined) setResult(`Не получилось: ${reply.error}.`);
      return onChecked();
    }).catch(failed).finally(() => setWorking(false));
  };
  const keyProblem = row.needsKey && (row.errorKind === "key" || row.keyBroken);
  const empty = !row.error && !keyProblem && row.models === 0;
  const manualServer = row.local || row.id === "custom";
  const trouble = keyProblem ? (row.hasKey ? "ключ не подошёл" : "нужен ключ")
    : row.error ? (row.errorKind === "key" ? "доступ отклонён" : "нет связи") : empty ? "нет моделей" : "";
  const state = working ? "проверка…" : !row.enabled ? "выключено" : trouble || `моделей: ${row.models}`;
  const tone = !row.enabled || working ? "" : empty ? "empty" : trouble ? "warn" : "ok";
  const reconnectButton = !row.enabled || row.local || empty ? undefined
    : <IconButton icon="refresh" size={15} label="Переподключить" disabled={working} onClick={reconnect} />;
  const focusField = (input: HTMLInputElement | null) => { input?.focus(); input?.select(); };
  const advice = keyProblem ? <>
    <p>{row.hasKey || row.keyBroken ? "Введи новый API-ключ для этого сервиса." : "Добавь API-ключ для подключения к сервису."}</p>
    <Button kind="secondary" disabled={working} onClick={() => focusField(keyInput.current)}>{row.hasKey || row.keyBroken ? "Заменить ключ" : "Ввести ключ"}</Button>
  </> : row.error ? <>
    <p>{manualServer ? "Проверь, что сервер запущен и адрес совпадает с его настройками." : "Проверь адрес сервиса и попробуй переподключиться."}</p>
    <Button kind="secondary" disabled={working} onClick={() => focusField(addressInput.current)}>Проверить адрес</Button>
  </> : <>
    <p>{row.id === "unsloth" ? "Загрузи модель в Unsloth Studio и обнови список."
      : manualServer ? "Сервер отвечает. Загрузи модель в сервисе и обнови список."
      : "Сервис отвечает. Проверь, что аккаунту доступны модели, и обнови список."}</p>
    <div className="provider-advice-actions">
      {row.site && manualServer && <Button kind="ghost" icon="external" onClick={() => { void api.open_url(row.site); }}>
        {row.installed ? "Как загрузить модель" : "Скачать с сайта"}
      </Button>}
      <Button kind="secondary" icon="refresh" disabled={working} onClick={reconnect}>Обновить список</Button>
    </div>
  </>;
  const keyHint = row.keyBroken ? "Сохранённый ключ не расшифровать. Введи его заново."
    : row.hasKey ? "Ключ сохранён. Новый заменит его, только если подойдёт."
    : LOCAL_KEY_HINTS[row.id] ?? <>Ключ из личного кабинета сервиса.{row.keyPage && <button type="button" className="link-btn key-page" onClick={() => { void api.open_url(row.keyPage); }}>Где взять ключ <Icon name="external" size={12} /></button>}</>;
  const address = (
    <Field label="Адрес" hint={row.id === "custom" ? "Адрес до /v1." : `По умолчанию ${row.defaultUrl}`}>
      <div className="row grow">
        <input ref={addressInput} aria-label="Адрес" className="input mono" value={url} placeholder={row.defaultUrl || "http://127.0.0.1:8000/v1"} spellCheck={false}
          onChange={(event) => setUrl(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && url !== row.url) apply({ url }); }} />
        <Button disabled={working || url === row.url} onClick={() => apply({ url })}>Применить</Button>
      </div>
    </Field>
  );
  return (
    <IntegrationCard id={row.id} title={row.title} hint={providerHint(row)} state={state} tone={tone}
      enabled={row.enabled} onToggle={(value) => apply({ enabled: value })} working={working} tools={reconnectButton}>
      {trouble && <div className="provider-advice">
        <div className="provider-advice-main">{advice}</div>
        {row.error && <details><summary>Технические детали</summary><p>{row.error}</p></details>}
      </div>}
      {row.local && address}
      {row.needsKey && (
        <Field label="API-ключ" hint={keyHint}>
          <div className="row grow">
            <input ref={keyInput} aria-label="API-ключ" className="input mono" type={showKey ? "text" : "password"} value={key} autoComplete="off" spellCheck={false} placeholder={row.hasKey ? `••••••••${row.keyEnd}` : "вставь ключ"}
              onChange={(event) => setKey(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && key) apply({ key }); }} />
            {key && <Button kind="ghost" onClick={() => setShowKey((value) => !value)}>{showKey ? "Скрыть" : "Показать"}</Button>}
            <Button kind="primary" disabled={working || !key} onClick={() => apply({ key })}>Сохранить</Button>
            {row.hasKey && <Button kind={armed ? "danger" : "ghost"} disabled={working} onClick={() => { if (armed) { setArmed(false); apply({ key: "" }); } else setArmed(true); }}>{armed ? "Точно удалить?" : "Удалить ключ"}</Button>}
          </div>
        </Field>
      )}
      {!row.local && address}
      {row.local && !empty && <div className="local-provider-actions">
        <Button kind="ghost" icon="refresh" disabled={working} onClick={reconnect}>Переподключить</Button>
        {row.site && <Button kind="ghost" icon="external" onClick={() => { void api.open_url(row.site); }}>
          {row.installed ? "Установка и запуск" : "Скачать с сайта"}
        </Button>}
      </div>}
      {result && <p className="pane-note">{result}</p>}
      {detail && <p className="pane-note mono" data-i18n-skip>{detail}</p>}
    </IntegrationCard>
  );
}
