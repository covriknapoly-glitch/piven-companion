import { useContext, useState } from "react";
import type { WebApi } from "./bridge";
import { Icon, type IconName } from "./icons";
import { LinkContext, Markdown } from "./markdown";
import { fileName } from "./ui";

export interface CodeCardData {
  kind: "read" | "write" | "edit" | "command" | "page" | "plan" | "note" | "changes" | "offer" | "plan_ready";
  title?: string;
  text?: string;
  path?: string;
  diff?: string;
  output?: string;
  added?: number;
  removed?: number;
  exit?: number | null;
  seconds?: number;
  denied?: boolean;
  stopped?: boolean;
  background?: boolean;
  items?: { text: string; status: "pending" | "in_progress" | "done" }[];
  root?: string;
  files?: { path: string; state: "created" | "edited" | "deleted" }[];
  checkpoint?: string;
  undone?: boolean;
  kept?: string[];
  answered?: "code" | "chat" | "go" | "keep";
}

export function parseCard(text: string): CodeCardData | null {
  try {
    return JSON.parse(text) as CodeCardData;
  } catch {
    return null;
  }
}

function Diff({ text }: { text: string }) {
  return (
    <pre className="code-card-body code-diff" data-i18n-skip>
      {text.split("\n").map((line, key) => (
        <div key={key} className={line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : line.startsWith("@@") ? "hunk" : ""}>{line || " "}</div>
      ))}
    </pre>
  );
}

function Expandable({ icon, title, tags, open: startOpen = false, tone = "", children }: { icon: IconName; title: string; tags?: React.ReactNode; open?: boolean; tone?: string; children?: React.ReactNode }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <div className={`code-card ${tone}`}>
      <button type="button" className="code-card-head" aria-expanded={open} disabled={!children} onClick={() => setOpen((value) => !value)}>
        <Icon name={icon} size={14} />
        <span className="code-card-title" title={title}>{title}</span>
        {tags}
        {children ? <Icon name="chevronRight" size={13} className={open ? "rot90" : ""} /> : null}
      </button>
      {open && children}
    </div>
  );
}

function Offer({ api, card, index }: { api: WebApi; card: CodeCardData; index: number }) {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const answer = (accept: boolean) => {
    setSent(true);
    void api.answer_code_offer(index, accept).then((reply) => { if (!reply.ok) { setSent(false); setError(reply.error ?? ""); } });
  };
  if (card.answered) return <div className="code-card-line"><Icon name={card.answered === "code" ? "code" : "chat"} size={13} /><span>{card.answered === "code" ? "Перешли в режим кода" : "Остались в чате"}</span></div>;
  return (
    <div className="code-offer">
      <div className="code-changes-title"><Icon name="code" size={14} /><span>Здесь нужно работать с файлами и командами</span></div>
      <p>В режиме кода агент сам создаст файлы, запустит программу и проверит результат.</p>
      <div className="code-changes-actions">
        <button type="button" className="btn btn-primary" disabled={sent} onClick={() => answer(true)}><Icon name="code" size={14} /> Перейти в режим кода</button>
        <button type="button" className="btn" disabled={sent} onClick={() => answer(false)}>Остаться в чате</button>
      </div>
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}

function PlanReady({ api, card, index }: { api: WebApi; card: CodeCardData; index: number }) {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const answer = (accept: boolean) => {
    setSent(true);
    void api.answer_plan(index, accept).then((reply) => { if (!reply.ok) { setSent(false); setError(reply.error ?? ""); } });
  };
  if (card.answered) return <div className="code-card-line"><Icon name={card.answered === "go" ? "play" : "edit"} size={13} /><span>{card.answered === "go" ? "План принят" : "План дорабатывается"}</span></div>;
  return (
    <div className="code-offer">
      <div className="code-changes-title"><Icon name="file" size={14} /><span>План готов</span></div>
      <div className="code-changes-actions">
        <button type="button" className="btn btn-primary" disabled={sent} onClick={() => answer(true)}><Icon name="play" size={14} /> Выполнить план</button>
        <button type="button" className="btn" disabled={sent} onClick={() => answer(false)}>Доработать</button>
      </div>
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}

function Changes({ api, card, index, onCopy }: { api: WebApi; card: CodeCardData; index: number; onCopy: (text: string) => void }) {
  const openLink = useContext(LinkContext);
  const [armed, setArmed] = useState(false);
  const open = (url: string) => openLink?.(url);
  const [error, setError] = useState("");
  const files = card.files ?? [];
  const root = (card.root ?? "").replace(/\\/g, "/");
  const relative = (path: string) => { const clean = path.replace(/\\/g, "/"); return clean.startsWith(`${root}/`) ? clean.slice(root.length + 1) : clean; };
  const start = files.map((file) => relative(file.path)).filter((path) => /\.html?$/i.test(path)).sort((a, b) => Number(/index\.html?$/i.test(b)) - Number(/index\.html?$/i.test(a)) || a.length - b.length)[0];
  const stillThere = files.some((file) => relative(file.path) === start && file.state !== "deleted");
  return (
    <div className="code-changes">
      <div className="code-changes-title"><Icon name="check" size={14} /><span>{card.undone ? "Изменения отменены" : `Изменено файлов: ${files.length}`}</span></div>
      {!card.undone && <ul data-i18n-skip>
        {files.slice(0, 40).map((file) => (
          <li key={file.path} className={file.state}><span>{file.state === "created" ? "+" : file.state === "deleted" ? "−" : "~"}</span>{relative(file.path)}</li>
        ))}
      </ul>}
      {card.undone && Boolean(card.kept?.length) && <p className="pane-note">{`Не тронуты, потому что менялись после работы агента: ${card.kept?.join(", ")}`}</p>}
      <div className="code-changes-actions">
        {!card.undone && start && stillThere && <button type="button" className="btn btn-primary" onClick={() => { void api.code_preview(start).then((reply) => { if (reply.ok && reply.url) open(reply.url); else setError(reply.error ?? ""); }); }}><Icon name="play" size={14} /> Запустить</button>}
        <button type="button" className="btn" onClick={() => { void api.code_open_folder().then((reply) => setError(reply.ok ? "" : reply.error ?? "")); }}><Icon name="folder" size={14} /> Открыть папку</button>
        <button type="button" className="btn" onClick={() => onCopy(card.root ?? "")}><Icon name="copy" size={14} /> Скопировать путь</button>
        {!card.undone && (armed
          ? <button type="button" className="link-btn danger" onClick={() => { void api.code_undo(index).then((reply) => { setArmed(false); setError(reply.ok ? "" : reply.error ?? ""); }); }}>Точно отменить?</button>
          : <button type="button" className="link-btn" onClick={() => setArmed(true)}><Icon name="retry" size={13} /> Отменить изменения</button>)}
      </div>
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}

export function CodeCard({ api, card, index, onCopy }: { api: WebApi; card: CodeCardData; index: number; onCopy: (text: string) => void }) {
  switch (card.kind) {
    case "note":
      return <div className="code-note"><Markdown text={card.text ?? ""} onCopy={onCopy} /></div>;
    case "read":
      return <div className="code-card-line"><Icon name="search" size={13} /><span>{card.title}</span></div>;
    case "plan":
      return (
        <ul className="code-plan">
          {(card.items ?? []).map((item, key) => (
            <li key={key} className={item.status}><Icon name={item.status === "done" ? "check" : item.status === "in_progress" ? "arrowRight" : "more"} size={13} /><span data-i18n-skip>{item.text}</span></li>
          ))}
        </ul>
      );
    case "write":
    case "edit":
      return (
        <Expandable icon={card.kind === "write" ? "file" : "edit"} title={card.title ?? fileName(card.path ?? "")}
          tags={<span className="code-tags" data-i18n-skip>{Boolean(card.added) && <b>+{card.added}</b>}{Boolean(card.removed) && <i>−{card.removed}</i>}</span>}>
          {card.diff ? <Diff text={card.diff} /> : undefined}
        </Expandable>
      );
    case "command":
    case "page": {
      const failed = !card.denied && !card.background && !card.stopped && card.exit !== 0 && card.exit !== undefined && card.exit !== null;
      const status = card.denied ? "не разрешено" : card.background ? "работает в фоне" : card.stopped ? "остановлено по времени" : failed ? (card.kind === "page" ? "есть ошибки" : `код ${card.exit}`) : "готово";
      return (
        <Expandable icon={card.kind === "page" ? "globe" : "keyboard"} title={card.title ?? ""} open={failed} tone={failed ? "failed" : ""}
          tags={<span className="code-status">{status}{card.seconds ? ` · ${card.seconds} с` : ""}</span>}>
          {card.output ? <pre className="code-card-body" data-i18n-skip>{card.output}</pre> : undefined}
        </Expandable>
      );
    }
    case "offer":
      return <Offer api={api} card={card} index={index} />;
    case "plan_ready":
      return <PlanReady api={api} card={card} index={index} />;
    case "changes":
      return <Changes api={api} card={card} index={index} onCopy={onCopy} />;
    default:
      return null;
  }
}
