import { useCallback, useEffect, useState } from "react";
import { isPhone, type CommandResult, type KnowledgeSource, type KnowledgeStatus, type WebApi } from "./bridge";
import { Icon } from "./icons";
import { Button, Modal } from "./ui";

export function KnowledgeDialog({ api, chatId, onClose }: { api: WebApi; chatId: string; onClose: () => void }) {
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const read = useCallback(() => api.knowledge_status(chatId).then(setStatus), [api, chatId]);
  useEffect(() => { void read(); }, [read]);
  const indexing = status?.ok && status.indexing;
  useEffect(() => {
    if (!indexing) return;
    const timer = window.setInterval(() => { void read(); }, 800);
    return () => window.clearInterval(timer);
  }, [indexing, read]);

  const change = async (action: () => Promise<CommandResult>) => {
    setPending(true);
    setError("");
    try {
      const result = await action();
      if (!result.ok && !result.cancelled) setError(result.error || "Не удалось обновить базу знаний.");
      await read();
    } catch {
      setError("Не удалось обновить базу знаний.");
    } finally {
      setPending(false);
    }
  };
  const folder = status?.ok ? status.folder : "";
  const blocked = pending || Boolean(indexing) || status?.ok === false;

  return (
    <Modal title="База знаний" onClose={onClose} className="knowledge-modal">
      <p className="pane-note">Выбери папку с Markdown, TXT, PDF или DOCX. Индекс хранится на компьютере. Найденные фрагменты отправляются выбранной модели вместе с вопросом.</p>
      {folder && <p className="knowledge-folder" data-i18n-skip><Icon name="folder" size={16} />{folder}</p>}
      {status?.ok && folder && <p className="pane-note">{`Файлов в индексе: ${status.files}. Пропущено: ${status.skipped}.`}</p>}
      {status?.ok && status.limited && <p className="pane-note">Достигнут лимит индекса. Можно выбрать папку поменьше.</p>}
      {indexing && status?.ok && <p className="pane-note" role="status">{`Индексируется папка ${status.pendingFolder}…`}</p>}
      {(error || status?.error) && <p className="pane-note" role="alert">{error || status?.error}</p>}
      <div className="knowledge-controls">
        <Button icon="folder" disabled={blocked} onClick={() => { void change(() => api.knowledge_pick_folder(chatId)); }}>
          {folder ? "Сменить папку…" : "Выбрать папку…"}
        </Button>
        {folder && <Button icon="refresh" disabled={blocked} onClick={() => { void change(() => api.knowledge_refresh(chatId)); }}>Обновить индекс</Button>}
        {folder && <Button kind="ghost" disabled={blocked} onClick={() => { void change(() => api.knowledge_remove(chatId)); }}>Отключить папку</Button>}
      </div>
    </Modal>
  );
}

export function KnowledgeExcerpt({ source, api, chatId, index, number, onClose }:
  { source: KnowledgeSource; api: WebApi; chatId: string; index: number; number: number; onClose: () => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const unavailable = "Файл источника недоступен.";
  useEffect(() => {
    let active = true;
    void api.knowledge_excerpt(chatId, index, number, source.path).then((reply) => {
      if (!active) return;
      if (reply.ok) setText(reply.text || "");
      else setError(reply.error || unavailable);
    }).catch(() => { if (active) setError(unavailable); });
    return () => { active = false; };
  }, [api, chatId, index, number, source.path]);
  const location = source.page ? `Страница ${source.page}` : /\.docx$/i.test(source.path) ? "Фрагмент документа" : `Строки ${source.start}–${source.end}`;
  return (
    <Modal title="Источник из базы знаний" onClose={onClose} className="knowledge-modal"
      footer={!isPhone && <Button icon="external" onClick={() => { void api.knowledge_open_source(chatId, index, number, source.path).then((reply) => setError(reply.ok ? "" : reply.error || unavailable)); }}>Открыть файл</Button>}>
      <p className="knowledge-folder" data-i18n-skip><Icon name="file" size={16} />{source.path}</p>
      <p className="pane-note">{location}{source.section && <> · <span data-i18n-skip>{source.section}</span></>}</p>
      {text && <pre className="knowledge-excerpt" data-i18n-skip>{text}</pre>}
      {error && <p className="pane-note" role="alert">{error}</p>}
    </Modal>
  );
}
