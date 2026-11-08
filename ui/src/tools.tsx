import { type ReactNode, useCallback, useEffect, useState } from "react";
import type { McpServer, SkillRow, ToolsStatus, WebApi } from "./bridge";
import { ConfirmDialog } from "./dialogs";
import { AdvancedHead, Button, Field, Modal, Switch, Toggle } from "./ui";

export function ToolsPane({ api, children }: { api: WebApi; children?: ReactNode }) {
  const [status, setStatus] = useState<ToolsStatus | null>(null);
  const [editing, setEditing] = useState<McpServer | "new" | null>(null);
  const [skill, setSkill] = useState<SkillRow | "new" | null>(null);
  const [removing, setRemoving] = useState<{ kind: "server" | "skill"; name: string } | null>(null);
  const load = useCallback(() => api.tools_status().then(setStatus), [api]);
  useEffect(() => { void load(); }, [load]);
  if (!status) return <p className="pane-note">Загрузка…</p>;

  return <>
    <Field label="Инструменты в ответах" hint="Модель сама решает, когда открыть сайт во встроенном браузере, найти что-то в интернете, взять навык или вызвать инструмент MCP-сервера. Каждый вызов виден в чате.">
      <Toggle label="Разрешить модели пользоваться инструментами" checked={status.enabled} onChange={(value) => { void api.set_tools_enabled(value).then(load); }} />
    </Field>
    {children}

    <h5 className="pane-subhead">Навыки</h5>
    <p className="pane-note">Навык — инструкция для модели на определённый случай: как писать отчёт, как отвечать клиентам, как оформлять код. Модель видит их список и берёт нужный сама. Можно попросить модель «сохрани это как навык».</p>
    {status.skills.map((item) => (
      <section key={item.folder || item.name} className="provider-card">
        <div className="provider-head">
          <strong>{item.name}</strong>
          <span className="provider-state">{item.builtin ? "встроенный" : "свой"}</span>
          {!item.builtin && <Button kind="ghost" onClick={() => setSkill(item)}>Изменить</Button>}
          {!item.builtin && <Button kind="ghost" onClick={() => setRemoving({ kind: "skill", name: item.folder })}>Удалить</Button>}
        </div>
        <small className="provider-line">{item.description}</small>
      </section>
    ))}
    <Button icon="plus" onClick={() => setSkill("new")}>Создать навык</Button>

    <AdvancedHead />
    <h5 className="pane-subhead">MCP-серверы</h5>
    <p className="pane-note">Model Context Protocol подключает инструменты других программ: файлы, базы данных, GitHub, Notion и многое другое. Сервер запускается командой (например <span className="mono">npx -y @modelcontextprotocol/server-filesystem C:\Users\Я\Documents</span>) или доступен по адресу.</p>
    {status.servers.map((server) => (
      <section key={server.name} className={`provider-card ${server.enabled ? (server.error ? "warn" : "ok") : ""}`}>
        <div className="provider-head">
          <strong>{server.name}</strong>
          <span className="provider-state">{!server.enabled ? "выключен" : server.error ? server.error : server.tools === null ? "запустится при первом ответе" : `инструментов: ${server.tools}`}</span>
          <Button kind="ghost" onClick={() => setEditing(server)}>Изменить</Button>
          <Button kind="ghost" onClick={() => setRemoving({ kind: "server", name: server.name })}>Удалить</Button>
        </div>
        <small className="mono provider-line">{server.url || server.command}</small>
      </section>
    ))}
    <Button icon="plus" onClick={() => setEditing("new")}>Добавить MCP-сервер</Button>

    {editing && <ServerDialog api={api} server={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={load} />}
    {skill && <SkillDialog api={api} skill={skill === "new" ? null : skill} onClose={() => setSkill(null)} onSaved={load} />}
    {removing && <ConfirmDialog title={removing.kind === "server" ? "Удалить MCP-сервер?" : "Удалить навык?"} text={`«${removing.name}» будет удалён.`}
      confirmLabel="Удалить" danger onClose={() => setRemoving(null)}
      onConfirm={() => { void (removing.kind === "server" ? api.delete_mcp_server(removing.name) : api.delete_skill(removing.name)).then(load); }} />}
  </>;
}

function ServerDialog({ api, server, onClose, onSaved }: { api: WebApi; server: McpServer | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(server?.name ?? "");
  const [mode, setMode] = useState<"command" | "url">(server?.url ? "url" : "command");
  const [command, setCommand] = useState(server?.command ?? "");
  const [url, setUrl] = useState(server?.url ?? "");
  const [env, setEnv] = useState(Object.entries(server?.env ?? {}).map(([key, value]) => `${key}=${value}`).join("\n"));
  const [enabled, setEnabled] = useState(server?.enabled ?? true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const save = () => {
    setWorking(true); setError("");
    const variables = Object.fromEntries(env.split("\n").map((line) => line.split("=")).filter((parts) => parts[0]?.trim())
      .map(([key, ...rest]) => [key.trim(), rest.join("=").trim()]));
    void api.save_mcp_server({ name, command: mode === "command" ? command : "", url: mode === "url" ? url : "", env: variables, enabled }, server?.name ?? "")
      .then((reply) => { setWorking(false); onSaved(); if (reply.ok) onClose(); else setError(reply.error ?? "Не получилось."); });
  };
  return (
    <Modal title={server ? `MCP-сервер ${server.name}` : "Новый MCP-сервер"} onClose={onClose} width={600} footer={<>
      <Button kind="ghost" onClick={onClose}>Отмена</Button>
      <Button kind="primary" disabled={working || !name.trim() || !(mode === "command" ? command.trim() : url.trim())} onClick={save}>{working ? "Проверка…" : "Сохранить"}</Button>
    </>}>
      <Field label="Название" hint="Латиница, цифры, дефис. Им подписываются инструменты сервера."><input className="input" value={name} onChange={(event) => setName(event.target.value)} /></Field>
      <Field label="Как подключаться">
        <div className="segmented">
          <button type="button" className={mode === "command" ? "on" : ""} onClick={() => setMode("command")}>Команда</button>
          <button type="button" className={mode === "url" ? "on" : ""} onClick={() => setMode("url")}>Адрес</button>
        </div>
      </Field>
      {mode === "command"
        ? <Field label="Команда запуска" hint="Нужны установленные Node.js (npx) или uv (uvx) — смотри README сервера."><input className="input mono" value={command} placeholder="npx -y @modelcontextprotocol/server-filesystem C:\Users\Я\Documents" onChange={(event) => setCommand(event.target.value)} /></Field>
        : <Field label="Адрес сервера" hint="Streamable HTTP, например http://127.0.0.1:8000/mcp"><input className="input mono" value={url} onChange={(event) => setUrl(event.target.value)} /></Field>}
      <Field label="Переменные окружения" hint="По одной на строку: ИМЯ=значение. Например токены, которые просит сервер."><textarea className="textarea mono" rows={3} value={env} onChange={(event) => setEnv(event.target.value)} spellCheck={false} /></Field>
      <Toggle label="Включён" checked={enabled} onChange={setEnabled} />
      {error && <p className="pane-note error-text">{error}</p>}
    </Modal>
  );
}

function SkillDialog({ api, skill, onClose, onSaved }: { api: WebApi; skill: SkillRow | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(skill?.name ?? "");
  const [description, setDescription] = useState(skill?.description ?? "");
  const [body, setBody] = useState(skill?.body.trim() ?? "");
  const [error, setError] = useState("");
  const save = () => {
    void api.save_skill(name, description, body).then((reply) => {
      if (!reply.ok) { setError(reply.error ?? "Не получилось."); return; }
      if (skill && skill.folder !== reply.folder) void api.delete_skill(skill.folder);
      onSaved(); onClose();
    });
  };
  return (
    <Modal title={skill ? `Навык ${skill.name}` : "Новый навык"} onClose={onClose} width={680} footer={<>
      <Button kind="ghost" onClick={onClose}>Отмена</Button>
      <Button kind="primary" disabled={!name.trim() || !description.trim() || !body.trim()} onClick={save}>Сохранить</Button>
    </>}>
      <Field label="Название" hint="Латиница и дефис, например weekly-report."><input className="input mono" value={name} onChange={(event) => setName(event.target.value)} /></Field>
      <Field label="Когда применять" hint="По этому описанию модель решает, нужен ли навык."><input className="input" value={description} onChange={(event) => setDescription(event.target.value)} /></Field>
      <Field label="Инструкции" hint="Что и как делать, по шагам. Можно Markdown."><textarea className="textarea" rows={12} value={body} onChange={(event) => setBody(event.target.value)} /></Field>
      {error && <p className="pane-note error-text">{error}</p>}
    </Modal>
  );
}
