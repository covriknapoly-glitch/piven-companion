import { useCallback, useEffect, useState } from "react";
import type { HfFile, MemoryStatus, WebApi } from "./bridge";
import { ConfirmDialog } from "./dialogs";
import { Button, Field, IconButton, Switch, Toggle } from "./ui";

function EmbeddingSearch({ api, onStarted }: { api: WebApi; onStarted: () => void }) {
  const [query, setQuery] = useState("");
  const [models, setModels] = useState<{ id: string; downloads: number }[] | null>(null);
  const [repo, setRepo] = useState("");
  const [files, setFiles] = useState<HfFile[]>([]);
  const [file, setFile] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setModels(null);
      void api.memory_search_models(query.trim()).then((reply) => { setModels(reply.models); setNote(reply.ok ? "" : reply.error ?? ""); });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [api, query]);
  const choose = (id: string) => {
    setRepo(id); setFiles([]); setFile("");
    void api.memory_model_files(id).then((reply) => {
      setFiles(reply.files);
      setFile((reply.files.find((item) => /q8_0/i.test(item.path)) ?? reply.files[0])?.path ?? "");
    });
  };
  const picked = files.find((item) => item.path === file);
  return (
    <div className="embed-search">
      <input className="input" value={query} placeholder="Найти модель эмбеддингов, например qwen3 embedding, bge-m3, e5" onChange={(event) => setQuery(event.target.value)} />
      <div className="embed-list">
        {models === null && <p className="pane-note">Поиск…</p>}
        {models?.length === 0 && <p className="pane-note">Ничего не нашлось.</p>}
        {models?.map((item) => (
          <button key={item.id} type="button" className={item.id === repo ? "selected" : ""} onClick={() => choose(item.id)}>
            <span className="mono">{item.id}</span><small>{item.downloads.toLocaleString("ru-RU")}</small>
          </button>
        ))}
      </div>
      {repo && files.length > 0 && (
        <div className="row grow">
          <select className="select" value={file} onChange={(event) => setFile(event.target.value)}>
            {files.map((item) => <option key={item.path} value={item.path}>{item.path}{item.size ? ` (${(item.size / 2 ** 20).toFixed(0)} МБ)` : ""}</option>)}
          </select>
          <Button kind="primary" icon="download" disabled={!file} onClick={() => { void api.memory_download_model(repo, file, picked?.size ?? 0).then(onStarted); }}>Скачать</Button>
        </div>
      )}
      {note && <p className="pane-note">{note}</p>}
    </div>
  );
}

export function MemoryPane({ api }: { api: WebApi }) {
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [fact, setFact] = useState("");
  const [clearing, setClearing] = useState<"" | "fact" | "exchange" | "all">("");
  const load = useCallback(() => api.memory_status().then(setStatus), [api]);
  useEffect(() => { void load(); }, [load]);
  const job = status?.job;
  useEffect(() => {
    if (job?.state !== "running") return;
    const timer = window.setInterval(() => { void load(); }, 700);
    return () => window.clearInterval(timer);
  }, [job?.state, load]);
  if (!status) return <p className="pane-note">Загрузка…</p>;
  const add = () => { if (fact.trim()) void api.memory_add_fact(fact).then(() => { setFact(""); void load(); }); };

  return <>
    <Field label="Долговременная память" hint="Модель помнит факты о тебе и находит нужное в прошлых разговорах из всех чатов. Всё хранится только на этом компьютере.">
      <Toggle label="Пользоваться памятью" checked={status.enabled} onChange={(value) => { void api.memory_set_enabled(value).then(load); }} />
    </Field>
    <p className="pane-note">В памяти: фактов {status.counts.facts}, разговоров {status.counts.exchanges}. Удалённый чат забывается вместе со своими разговорами.</p>

    <Field label="Поиск по смыслу" hint={status.modelReady
      ? `Включён: память находит связанное по смыслу, а не только по словам (обработано записей: ${status.counts.withMeaning}).`
      : "Сейчас память ищет по словам. Модель эмбеддингов научит её искать по смыслу: найди любую ниже (рекомендуем Qwen3-Embedding-0.6B, 610 МБ, Apache 2.0). Она работает на процессоре и не занимает видеопамять."}>
      {status.modelReady && <p className="pane-note">Модель: <span className="mono">{status.modelName}</span></p>}
      {job?.state === "running"
        ? <div className="side-download running"><div className="progress-track"><i style={{ width: `${job.percent}%` }} /></div><small>{job.message}</small>
            <Button kind="ghost" onClick={() => { void api.memory_cancel(); }}>Отменить</Button></div>
        : <EmbeddingSearch api={api} onStarted={() => { void load(); }} />}
      {job && job.state !== "running" && job.message && <p className="pane-note">{job.message}</p>}
    </Field>

    <h5 className="pane-subhead">Факты</h5>
    <div className="row grow">
      <input className="input" value={fact} placeholder="Например: я пишу на Python и люблю короткие ответы" onChange={(event) => setFact(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") add(); }} />
      <Button disabled={!fact.trim()} onClick={add}>Запомнить</Button>
    </div>
    {!status.facts.length && <p className="pane-note">Пока пусто. Скажи модели «запомни, что…», и факт появится здесь.</p>}
    <div className="memory-facts">
      {status.facts.map((item) => (
        <div key={item.id} className="memory-fact">
          <span>{item.text}</span>
          <IconButton icon="close" label="Забыть" size={13} onClick={() => { void api.memory_delete(item.id).then(load); }} />
        </div>
      ))}
    </div>

    <h5 className="pane-subhead">Очистка</h5>
    <div className="row">
      <Button kind="ghost" onClick={() => setClearing("exchange")}>Забыть разговоры</Button>
      <Button kind="ghost" onClick={() => setClearing("fact")}>Забыть факты</Button>
      <Button kind="danger" onClick={() => setClearing("all")}>Очистить всю память</Button>
    </div>
    {clearing && <ConfirmDialog title="Очистить память?" danger confirmLabel="Очистить"
      text={clearing === "all" ? "Модель забудет все факты и прошлые разговоры. Сами чаты останутся." : clearing === "fact" ? "Модель забудет все сохранённые факты." : "Модель перестанет находить прошлые разговоры. Сами чаты останутся."}
      onClose={() => setClearing("")} onConfirm={() => { void api.memory_clear(clearing === "all" ? "" : clearing).then(load); }} />}
  </>;
}
