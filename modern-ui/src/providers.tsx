import { useCallback, useEffect, useState } from "react";
import type { ProviderRow, WebApi } from "./bridge";
import { Button, Field, Switch } from "./ui";

/** Ollama, LM Studio and cloud services by API key: their models join the model list as "<service>:<model>". */
export function ProvidersPane({ api, onChanged }: { api: WebApi; onChanged: () => void }) {
  const [rows, setRows] = useState<ProviderRow[] | null>(null);
  const load = useCallback(() => api.providers_status().then((reply) => setRows(reply.providers)), [api]);
  useEffect(() => { void load(); }, [load]);
  if (!rows) return <p className="pane-note">Загрузка…</p>;
  const local = rows.filter((row) => row.local);
  const cloud = rows.filter((row) => !row.local);
  return <>
    <p className="pane-note">Модели из этих программ и сервисов появятся в общем списке моделей, и их можно выбрать для любого чата. Ключи хранятся зашифрованными средствами Windows и отправляются только своему сервису.</p>
    <h5 className="pane-subhead">Программы на этом компьютере</h5>
    {local.map((row) => <ProviderCard key={row.id} api={api} row={row} onSaved={() => { void load(); onChanged(); }} />)}
    <h5 className="pane-subhead">Облачные модели по своему ключу</h5>
    {cloud.map((row) => <ProviderCard key={row.id} api={api} row={row} onSaved={() => { void load(); onChanged(); }} />)}
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
  if (!row.installed) return (
    <section className="provider-card">
      <div className="provider-head">
        <strong>{row.title}</strong>
        <span className="provider-state">не установлена</span>
        <Button kind="ghost" icon="external" onClick={() => { void api.open_url(row.site); }}>Скачать с сайта</Button>
      </div>
    </section>
  );
  const state = !row.enabled ? "выключено" : row.error ? row.error : `моделей: ${row.models}`;
  return (
    <section className={`provider-card ${row.enabled ? (row.error ? "warn" : "ok") : ""}`}>
      <div className="provider-head">
        <strong>{row.title}</strong>
        <span className="provider-state">{working ? "проверка…" : state}</span>
        <Switch label="" checked={row.enabled} onChange={(value) => apply({ enabled: value })} />
      </div>
      {row.enabled && <>
        <Field label="Адрес" hint={row.id === "custom" ? "Любой сервер с OpenAI API, например vLLM или text-generation-webui: адрес до /v1." : `По умолчанию ${row.defaultUrl}`}>
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
      </>}
    </section>
  );
}
