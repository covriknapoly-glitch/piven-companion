import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { ProviderRow, SettingsDetails, WebApi } from "./bridge";
import { translate } from "./i18n";
import { Icon } from "./icons";
import { Button, Field, IconButton, Switch } from "./ui";
import claudeLogo from "./assets/integrations/claude-color.svg";
import comfyuiLogo from "./assets/integrations/comfyui-color.svg";
import geminiLogo from "./assets/integrations/gemini-color.svg";
import lmstudioLogo from "./assets/integrations/lmstudio.svg";
import ollamaLogo from "./assets/integrations/ollama.svg";
import openaiLogo from "./assets/integrations/openai.svg";
import openrouterLogo from "./assets/integrations/openrouter.svg";

const LOGOS: Record<string, string> = {
  comfyui: comfyuiLogo, ollama: ollamaLogo, lmstudio: lmstudioLogo, openai: openaiLogo, anthropic: claudeLogo, gemini: geminiLogo, openrouter: openrouterLogo,
};

function IntegrationLogo({ id }: { id: string }) {
  if (LOGOS[id]) return <span className={`integration-logo ${id}`} dangerouslySetInnerHTML={{ __html: LOGOS[id] }} />;
  return <span className={`integration-logo ${id}`}><Icon name="box" size={18} /></span>;
}

function IntegrationCard({ id, title, hint, state, tone = "", enabled, onToggle, action, tools, children }:
  { id: string; title: string; hint: string; state?: string; tone?: "" | "ok" | "warn"; enabled: boolean; onToggle?: (value: boolean) => void; action?: ReactNode; tools?: ReactNode; children?: ReactNode }) {
  return (
    <section className={`provider-card ${tone}`}>
      <div className="provider-head">
        <IntegrationLogo id={id} />
        <div className="provider-title"><strong>{title}</strong><small>{hint}</small></div>
        {state && <span className="provider-state">{state}</span>}
        {tools}
        {action ?? (onToggle && <Switch label={title} checked={enabled} onChange={onToggle} />)}
      </div>
      {enabled && children}
    </section>
  );
}

const HINTS: Record<string, string> = {
  ollama: "Модели из Ollama, которая запущена на этом компьютере.",
  lmstudio: "Модели из LM Studio, которая запущена на этом компьютере.",
  openai: "Модели OpenAI по твоему ключу.",
  anthropic: "Модели Claude по твоему ключу.",
  gemini: "Модели Google Gemini по твоему ключу.",
  openrouter: "Много моделей разных компаний через один ключ.",
  custom: "Любой сервер с OpenAI API, например vLLM или text-generation-webui.",
};

export function IntegrationsPane({ api, d, save, onChanged }:
  { api: WebApi; d: SettingsDetails; save: (patch: Record<string, unknown>) => Promise<unknown>; onChanged: () => void }) {
  const [rows, setRows] = useState<ProviderRow[] | null>(null);
  const [query, setQuery] = useState("");
  const load = useCallback(() => api.providers_status().then((reply) => setRows(reply.providers)), [api]);
  useEffect(() => {
    void load();
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
    matches("Модели (llama.cpp и подключённые сервисы)", "Ответы, код и презентации. Если выключить, текущий ответ остановится.", "llama.cpp") && (
      <IntegrationCard key="models" id="models" title="Модели (llama.cpp и подключённые сервисы)" hint="Ответы, код и презентации. Если выключить, текущий ответ остановится."
        enabled={on("models")} onToggle={toggle("models")} />),
    matches("ComfyUI", "Рисование картинок и видео.") && (
      <IntegrationCard key="comfyui" id="comfyui" title="ComfyUI" hint="Рисование картинок и видео." enabled={on("comfyui")} onToggle={toggle("comfyui")} />),
  ].filter(Boolean);

  const shown = (rows ?? []).filter((row) => matches(row.title, HINTS[row.id] ?? "", row.id));
  const local = shown.filter((row) => row.local);
  const cloud = shown.filter((row) => !row.local);
  const card = (row: ProviderRow) => <ProviderCard key={row.id} api={api} row={row} onChecked={() => { void load(); }} onSaved={() => { void load(); onChanged(); }} />;
  const nothing = !own.length && !local.length && !cloud.length && rows !== null;

  return <>
    <label className="search-field big integration-search"><Icon name="search" size={15} />
      <input placeholder="Найти интеграцию" value={query} onChange={(event) => setQuery(event.target.value)} />
      {query && <button type="button" aria-label="Очистить" onClick={() => setQuery("")}><Icon name="close" size={13} /></button>}
    </label>
    {own.length > 0 && <><h5 className="pane-subhead">Встроенные</h5>{own}</>}
    {rows === null && <p className="pane-note">Загрузка…</p>}
    {local.length > 0 && <><h5 className="pane-subhead">Локальные модели</h5>{local.map(card)}</>}
    {cloud.length > 0 && <><h5 className="pane-subhead">Облачные модели по своему ключу</h5>{cloud.map(card)}</>}
    {nothing && <p className="pane-note">Ничего не найдено</p>}
    <p className="pane-note">Модели из программ и сервисов появятся в общем списке моделей, и их можно выбрать для любого чата. Ключи хранятся зашифрованными средствами Windows и отправляются только своему сервису.</p>
  </>;
}

function ProviderCard({ api, row, onSaved, onChecked }: { api: WebApi; row: ProviderRow; onSaved: () => void; onChecked: () => void }) {
  const [url, setUrl] = useState(row.url);
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [armed, setArmed] = useState(false);
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState("");
  const [detail, setDetail] = useState("");
  useEffect(() => setUrl(row.url), [row.url]);
  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(timer);
  }, [armed]);
  const start = () => { setWorking(true); setResult(""); setDetail(""); };
  const apply = (patch: { enabled?: boolean; url?: string; key?: string }) => {
    start();
    void api.set_provider(row.id, patch.enabled ?? null, patch.url ?? null, patch.key ?? null).then((reply) => {
      setWorking(false);
      if (reply.rejected) {
        setResult(row.hasKey ? "Этот ключ не подошёл, остался прежний." : "Этот ключ не подошёл и не сохранён.");
        setDetail(reply.error);
      } else if (patch.key === "") setResult("Ключ удалён.");
      else if (reply.ok) setResult(`Подключено, моделей: ${reply.models}.`);
      else if (reply.keySaved) setResult(`Ключ сохранён, но проверить его не удалось: ${reply.error}.`);
      else setResult(`Не получилось: ${reply.error}.`);
      if (patch.key !== undefined && !reply.rejected) { setKey(""); setShowKey(false); }
      onSaved();
    });
  };
  const reconnect = () => {
    start();
    void api.reconnect_provider(row.id).then((reply) => {
      setWorking(false);
      setResult(reply.ok ? `Подключено, моделей: ${reply.models}.` : `Не получилось: ${reply.error}.`);
      onChecked();
    });
  };
  const hint = HINTS[row.id] ?? "";
  if (!row.installed) return (
    <IntegrationCard id={row.id} title={row.title} hint={hint} state="не установлена" enabled={false}
      action={<Button kind="ghost" icon="external" onClick={() => { void api.open_url(row.site); }}>Скачать с сайта</Button>} />
  );
  const trouble = !row.error ? "" : row.errorKind === "key" ? (row.hasKey ? "ключ не подошёл" : "нужен ключ") : row.local ? "не запущена" : "нет связи";
  const state = working ? "проверка…" : !row.enabled ? "выключено" : trouble || `моделей: ${row.models}`;
  const reconnectButton = !row.enabled ? undefined : row.error
    ? <Button kind="ghost" icon="refresh" disabled={working} onClick={reconnect}>Переподключить</Button>
    : <IconButton icon="refresh" size={15} label="Переподключить" disabled={working} onClick={reconnect} />;
  const keyHint = row.keyBroken ? "Сохранённый ключ не расшифровать. Введи его заново."
    : row.hasKey ? "Ключ сохранён. Новый заменит его, только если подойдёт."
    : <>Ключ из личного кабинета сервиса.{row.keyPage && <button type="button" className="link-btn key-page" onClick={() => { void api.open_url(row.keyPage); }}>Где взять ключ <Icon name="external" size={12} /></button>}</>;
  return (
    <IntegrationCard id={row.id} title={row.title} hint={hint} state={state} tone={row.enabled ? (row.error ? "warn" : "ok") : ""}
      enabled={row.enabled} onToggle={(value) => apply({ enabled: value })} tools={reconnectButton}>
      {row.needsKey && (
        <Field label="API-ключ" hint={keyHint}>
          <div className="row grow">
            <input className="input mono" type={showKey ? "text" : "password"} value={key} autoComplete="off" spellCheck={false} placeholder={row.hasKey ? `••••••••${row.keyEnd}` : "вставь ключ"}
              onChange={(event) => setKey(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && key) apply({ key }); }} />
            {key && <Button kind="ghost" onClick={() => setShowKey((value) => !value)}>{showKey ? "Скрыть" : "Показать"}</Button>}
            <Button kind="primary" disabled={working || !key} onClick={() => apply({ key })}>Сохранить</Button>
            {row.hasKey && <Button kind={armed ? "danger" : "ghost"} disabled={working} onClick={() => { if (armed) { setArmed(false); apply({ key: "" }); } else setArmed(true); }}>{armed ? "Точно удалить?" : "Удалить ключ"}</Button>}
          </div>
        </Field>
      )}
      <Field label="Адрес" hint={row.id === "custom" ? "Адрес до /v1." : `По умолчанию ${row.defaultUrl}`}>
        <div className="row grow">
          <input className="input mono" value={url} placeholder={row.defaultUrl || "http://127.0.0.1:8000/v1"} spellCheck={false}
            onChange={(event) => setUrl(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && url !== row.url) apply({ url }); }} />
          <Button disabled={working || url === row.url} onClick={() => apply({ url })}>Применить</Button>
        </div>
      </Field>
      {result ? <p className="pane-note">{result}</p> : row.error && !working && <p className="pane-note">{row.error}</p>}
      {detail && <p className="pane-note mono" data-i18n-skip>{detail}</p>}
    </IntegrationCard>
  );
}
