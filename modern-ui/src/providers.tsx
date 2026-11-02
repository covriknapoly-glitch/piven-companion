import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { ProviderRow, SettingsDetails, WebApi } from "./bridge";
import { translate } from "./i18n";
import { Icon } from "./icons";
import { Button, Field, Switch, TextSetting } from "./ui";

/** One integration in the settings: a title, what it is for, its state and a switch; the details open below when it is on. */
function IntegrationCard({ title, hint, state, tone = "", enabled, onToggle, action, children }:
  { title: string; hint: string; state?: string; tone?: "" | "ok" | "warn"; enabled: boolean; onToggle?: (value: boolean) => void; action?: ReactNode; children?: ReactNode }) {
  return (
    <section className={`provider-card ${tone}`}>
      <div className="provider-head">
        <div className="provider-title"><strong>{title}</strong><small>{hint}</small></div>
        {state && <span className="provider-state">{state}</span>}
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

/** Everything that can be connected, in one style: the app's own switches, programs on this computer and cloud services. */
export function IntegrationsPane({ api, d, save, errors, onOpenTwitch, onChanged }:
  { api: WebApi; d: SettingsDetails; save: (patch: Record<string, unknown>) => Promise<unknown>; errors: Record<string, string>; onOpenTwitch: () => void; onChanged: () => void }) {
  const [rows, setRows] = useState<ProviderRow[] | null>(null);
  const [query, setQuery] = useState("");
  const load = useCallback(() => api.providers_status().then((reply) => setRows(reply.providers)), [api]);
  useEffect(() => { void load(); }, [load]);

  const toggle = (key: string) => (value: boolean) => { void save({ integrations: { [key]: value } }); };
  const on = (key: string) => d.integrations[key] !== false;
  const matches = (...texts: string[]) => {
    const needle = query.trim().toLowerCase();
    // the shown (translated) words count as well as the Russian ones
    return !needle || texts.some((text) => `${text} ${translate(text) ?? ""}`.toLowerCase().includes(needle));
  };

  const own = [
    matches("Модели (llama.cpp и подключённые сервисы)", "Ответы, код и презентации. Если выключить, текущий ответ остановится.", "llama.cpp") && (
      <IntegrationCard key="ollama" title="Модели (llama.cpp и подключённые сервисы)" hint="Ответы, код и презентации. Если выключить, текущий ответ остановится."
        enabled={on("ollama")} onToggle={toggle("ollama")} />),
    matches("ComfyUI", "Рисование картинок и видео.") && (
      <IntegrationCard key="comfyui" title="ComfyUI" hint="Рисование картинок и видео." enabled={on("comfyui")} onToggle={toggle("comfyui")} />),
    matches("Twitch", "Сообщения в чат канала и опросы для зрителей.") && (
      <IntegrationCard key="twitch" title="Twitch" hint="Сообщения в чат канала и опросы для зрителей." enabled={on("twitch")} onToggle={toggle("twitch")}>
        <Field label="Twitch-канал" error={errors.twitchChannel} hint="Без решётки, например twitchdev.">
          <div className="row grow">
            <TextSetting mono value={d.twitchChannel} placeholder="канал" onCommit={(value) => { void save({ twitchChannel: value }); }} />
            <Button icon="twitch" onClick={onOpenTwitch}>Написать в чат…</Button>
          </div>
        </Field>
      </IntegrationCard>),
  ].filter(Boolean);

  const shown = (rows ?? []).filter((row) => matches(row.title, HINTS[row.id] ?? "", row.id));
  const local = shown.filter((row) => row.local);
  const cloud = shown.filter((row) => !row.local);
  const card = (row: ProviderRow) => <ProviderCard key={row.id} api={api} row={row} onSaved={() => { void load(); onChanged(); }} />;
  const nothing = !own.length && !local.length && !cloud.length && rows !== null;

  return <>
    <label className="search-field big integration-search"><Icon name="search" size={15} />
      <input placeholder="Найти интеграцию" value={query} onChange={(event) => setQuery(event.target.value)} />
      {query && <button type="button" aria-label="Очистить" onClick={() => setQuery("")}><Icon name="close" size={13} /></button>}
    </label>
    {own.length > 0 && <><h5 className="pane-subhead">Встроенные</h5>{own}</>}
    {rows === null && <p className="pane-note">Загрузка…</p>}
    {local.length > 0 && <><h5 className="pane-subhead">Программы на этом компьютере</h5>{local.map(card)}</>}
    {cloud.length > 0 && <><h5 className="pane-subhead">Облачные модели по своему ключу</h5>{cloud.map(card)}</>}
    {nothing && <p className="pane-note">Ничего не найдено</p>}
    <p className="pane-note">Модели из программ и сервисов появятся в общем списке моделей, и их можно выбрать для любого чата. Ключи хранятся зашифрованными средствами Windows и отправляются только своему сервису.</p>
  </>;
}

function ProviderCard({ api, row, onSaved }: { api: WebApi; row: ProviderRow; onSaved: () => void }) {
  const [url, setUrl] = useState(row.url);
  const [key, setKey] = useState("");
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState("");
  useEffect(() => setUrl(row.url), [row.url]);
  const apply = (patch: { enabled?: boolean; url?: string; key?: string }) => {
    setWorking(true); setResult("");
    void api.set_provider(row.id, patch.enabled ?? null, patch.url ?? null, patch.key ?? null).then((reply) => {
      setWorking(false);
      setResult(reply.ok ? `Подключено, моделей: ${reply.models}.` : `Не получилось: ${reply.error}.`);
      if (patch.key !== undefined) setKey("");
      onSaved();
    });
  };
  const hint = HINTS[row.id] ?? "";
  if (!row.installed) return (
    <IntegrationCard title={row.title} hint={hint} state="не установлена" enabled={false}
      action={<Button kind="ghost" icon="external" onClick={() => { void api.open_url(row.site); }}>Скачать с сайта</Button>} />
  );
  const state = working ? "проверка…" : !row.enabled ? "выключено" : row.error ? row.error : `моделей: ${row.models}`;
  return (
    <IntegrationCard title={row.title} hint={hint} state={state} tone={row.enabled ? (row.error ? "warn" : "ok") : ""}
      enabled={row.enabled} onToggle={(value) => apply({ enabled: value })}>
      <Field label="Адрес" hint={row.id === "custom" ? "Адрес до /v1." : `По умолчанию ${row.defaultUrl}`}>
        <div className="row grow">
          <input className="input mono" value={url} placeholder={row.defaultUrl || "http://127.0.0.1:8000/v1"} spellCheck={false}
            onChange={(event) => setUrl(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") apply({ url }); }} />
          <Button disabled={working} onClick={() => apply({ url })}>Проверить</Button>
        </div>
      </Field>
      {row.needsKey && (
        <Field label="API-ключ" hint={row.hasKey ? "Ключ сохранён. Введи новый, чтобы заменить." : "Ключ из личного кабинета сервиса."}>
          <div className="row grow">
            <input className="input mono" type="password" value={key} autoComplete="off" placeholder={row.hasKey ? "••••••••" : "вставь ключ"}
              onChange={(event) => setKey(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && key) apply({ key }); }} />
            <Button kind="primary" disabled={working || !key} onClick={() => apply({ key })}>Сохранить</Button>
            {row.hasKey && <Button kind="ghost" disabled={working} onClick={() => apply({ key: "" })}>Удалить ключ</Button>}
          </div>
        </Field>
      )}
      {result && <p className="pane-note">{result}</p>}
    </IntegrationCard>
  );
}
