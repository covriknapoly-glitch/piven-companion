import { useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { EngineState, UpdateStatus, WebApi } from "./bridge";
import { currentLanguage } from "./i18n";
import { Icon } from "./icons";
import { Markdown } from "./markdown";
import { Button, Field, IconButton, Modal, Toggle, useShared } from "./ui";

const SHOT = /^!\[([^\]]*)\]\((https:\/\/[^\s)]+)\)$/;
const TRUSTED = /^https:\/\/(raw\.githubusercontent\.com|github\.com|user-images\.githubusercontent\.com|private-user-images\.githubusercontent\.com|objects\.githubusercontent\.com)\//;

/** Release notes are written in English, then "---", then Russian; the reader gets the half in their language. */
export function notesFor(notes: string, language = currentLanguage()) {
  const parts = notes.split(/\r?\n-{3,}\s*\r?\n/).map((part) => part.trim()).filter(Boolean);
  if (parts.length < 2) return notes.trim();
  const russian = parts.find((part) => /[а-яё]{3,}/i.test(part));
  const english = parts.find((part) => part !== russian);
  return (language === "en" ? english ?? russian : russian ?? english) ?? notes.trim();
}

function NotesBody({ api, text }: { api: WebApi; text: string }) {
  const blocks: ReactNode[] = [];
  let lines: string[] = [];
  const flush = () => {
    if (lines.join("").trim()) blocks.push(<Markdown key={blocks.length} text={lines.join("\n")} onCopy={(value) => { void api.copy_text(value); }} />);
    lines = [];
  };
  for (const line of text.split(/\r?\n/)) {
    const shot = SHOT.exec(line.trim());
    if (shot && TRUSTED.test(shot[2])) {
      flush();
      blocks.push(<img key={blocks.length} className="notes-shot" src={shot[2]} alt={shot[1]} loading="lazy" />);
    } else lines.push(line);
  }
  flush();
  return <div className="notes-body" data-i18n-skip>{blocks}</div>;
}

/** What changed in the new version, read inside the program instead of on GitHub. */
export function ReleaseNotes({ api, version, onClose, onUpdate }: { api: WebApi; version: string; onClose: () => void; onUpdate?: () => void }) {
  const [status] = useShared<UpdateStatus>("update", () => api.update_status());
  const text = status?.notes ? notesFor(status.notes) : "";
  // The banner sits inside the chat column; the window goes to the page root so nothing covers it.
  return createPortal(
    <Modal title={`Что нового в ${version}`} onClose={onClose} width={720} className="notes-modal" footer={<>
      {status?.page && <Button kind="ghost" icon="external" onClick={() => { void api.open_url(status.page); }}>Страница релиза</Button>}
      {onUpdate && <Button kind="primary" icon="download" onClick={() => { onClose(); onUpdate(); }}>Обновить сейчас</Button>}
    </>}>
      {text ? <NotesBody api={api} text={text} /> : <p className="dialog-note">{status ? "Описания у этой версии нет." : ""}</p>}
    </Modal>,
    document.body,
  );
}

/** A line at the top of the chat when a new version is out. Nothing is installed until the user presses the button. */
export function UpdateBanner({ api, state, onError }: { api: WebApi; state: EngineState; onError: (error?: string) => void }) {
  const [reading, setReading] = useState(false);
  const update = state.update;
  if (!update) return null;
  const reply = (result: { ok: boolean; error?: string }) => onError(result.ok ? undefined : result.error);
  const download = () => { void api.update_download().then(reply); };
  const idle = update.state !== "running" && !update.ready;
  const notes = (
    <>
      <button type="button" className="link-btn" onClick={() => setReading(true)}>Что нового</button>
      {reading && <ReleaseNotes api={api} version={update.version} onClose={() => setReading(false)} onUpdate={idle && update.canInstall ? download : undefined} />}
    </>
  );
  if (update.state === "running") {
    return (
      <div className="update-banner" role="status">
        <span className="spinner" /><span className="grow">{update.message || "Скачивается обновление"} · {update.percent}%</span>
        <div className="update-progress" aria-hidden="true"><i style={{ width: `${update.percent}%` }} /></div>
        {notes}
        <Button kind="ghost" onClick={() => { void api.update_cancel().then(reply); }}>Отменить</Button>
      </div>
    );
  }
  if (update.ready) {
    return (
      <div className="update-banner ready" role="status">
        <Icon name="check" size={15} />
        <span className="grow">{update.fromSources
          ? `Версия ${update.version} скачана. Эта копия запущена из исходников, поэтому установится обычная версия программы и откроется вместо неё.`
          : `Версия ${update.version} скачана. Программа закроется на минуту и откроется уже новой.`}</span>
        {notes}
        <Button kind="primary" onClick={() => { void api.update_install().then(reply); }}>{update.fromSources ? "Установить" : "Перезапустить и обновить"}</Button>
      </div>
    );
  }
  return (
    <div className="update-banner" role="status">
      <Icon name={update.state === "error" ? "alert" : "download"} size={15} />
      <span className="grow">{update.state === "error" ? update.message : `Вышла версия ${update.version}`}</span>
      {notes}
      {update.canInstall
        ? <Button kind="primary" onClick={download}>{update.state === "error" ? "Повторить" : "Обновить сейчас"}</Button>
        : <Button onClick={() => { void api.open_url(update.page); }}>Открыть релиз</Button>}
      {update.state !== "error" && <IconButton icon="close" size={14} label="Не напоминать об этой версии" onClick={() => { void api.update_skip(update.version).then(reply); }} />}
    </div>
  );
}

/** Settings → Data: the version, the check switch and a check button. */
export function UpdatePane({ api }: { api: WebApi }) {
  const [status, , setStatus] = useShared<UpdateStatus>("update", () => api.update_status());
  const [checking, setChecking] = useState(false);
  const [reading, setReading] = useState(false);
  if (!status) return null;
  const check = () => { setChecking(true); void api.update_check().then((next) => { setStatus(next); setChecking(false); }); };
  const line = checking ? "Проверяю…" : status.error ? status.error : !status.checked ? "Ещё не проверялось."
    : status.available ? `Вышла версия ${status.latest}.` : "Установлена последняя версия.";
  return (
    <Field label="Обновления" hint={`Версия ${status.current}. Новые версии берутся из релизов на GitHub, скачиваются и ставятся только по кнопке.`}>
      <Toggle label="Проверять обновления" checked={status.auto} onChange={(value) => { void api.update_set_check(value).then(() => api.update_status()).then(setStatus); }} />
      <div className="row update-row">
        <Button icon="refresh" disabled={checking} onClick={check}>Проверить сейчас</Button>
        <span className="pane-note">{line}</span>
        {status.available && <button type="button" className="link-btn" onClick={() => setReading(true)}>Что нового</button>}
      </div>
      {reading && <ReleaseNotes api={api} version={status.latest} onClose={() => setReading(false)}
        onUpdate={status.canInstall && status.job.state !== "running" && !status.ready ? () => { void api.update_download(); } : undefined} />}
    </Field>
  );
}
