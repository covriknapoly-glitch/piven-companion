import { useEffect, useState } from "react";
import type { EngineState, UpdateStatus, WebApi } from "./bridge";
import { Icon } from "./icons";
import { Button, Field, IconButton, Toggle } from "./ui";

/** A line at the top of the chat when a new version is out. Nothing is installed until the user presses the button. */
export function UpdateBanner({ api, state, onError }: { api: WebApi; state: EngineState; onError: (error?: string) => void }) {
  const update = state.update;
  if (!update) return null;
  const reply = (result: { ok: boolean; error?: string }) => onError(result.ok ? undefined : result.error);
  const notes = <button type="button" className="link-btn" onClick={() => { void api.open_url(update.page); }}>Что нового</button>;
  if (update.state === "running") {
    return (
      <div className="update-banner" role="status">
        <span className="spinner" /><span className="grow">{update.message || "Скачивается обновление"} · {update.percent}%</span>
        <Button kind="ghost" onClick={() => { void api.update_cancel().then(reply); }}>Отменить</Button>
      </div>
    );
  }
  if (update.ready) {
    return (
      <div className="update-banner ready" role="status">
        <Icon name="check" size={15} /><span className="grow">{`Версия ${update.version} скачана. Программа закроется на минуту и откроется уже новой.`}</span>
        <Button kind="primary" onClick={() => { void api.update_install().then(reply); }}>Перезапустить и обновить</Button>
      </div>
    );
  }
  return (
    <div className="update-banner" role="status">
      <Icon name={update.state === "error" ? "alert" : "download"} size={15} />
      <span className="grow">{update.state === "error" ? update.message : `Вышла версия ${update.version}`}</span>
      {notes}
      {update.canInstall
        ? <Button kind="primary" onClick={() => { void api.update_download().then(reply); }}>{update.state === "error" ? "Повторить" : "Обновить сейчас"}</Button>
        : <Button onClick={() => { void api.open_url(update.page); }}>Скачать</Button>}
      {update.state !== "error" && <IconButton icon="close" size={14} label="Не напоминать об этой версии" onClick={() => { void api.update_skip(update.version).then(reply); }} />}
    </div>
  );
}

/** Settings → Data: the version, the check switch and a check button. */
export function UpdatePane({ api }: { api: WebApi }) {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [checking, setChecking] = useState(false);
  useEffect(() => { void api.update_status().then(setStatus); }, [api]);
  if (!status) return null;
  const check = () => { setChecking(true); void api.update_check().then((next) => { setStatus(next); setChecking(false); }); };
  const line = checking ? "Проверяю…" : status.error ? status.error : !status.checked ? "Ещё не проверялось."
    : status.available ? `Вышла версия ${status.latest}.` : "Установлена последняя версия.";
  return (
    <Field label="Обновления" hint={`Версия ${status.current}. Новые версии берутся из релизов на GitHub, ставятся только по кнопке.`}>
      <Toggle label="Проверять обновления" checked={status.auto} onChange={(value) => { void api.update_set_check(value).then(() => api.update_status()).then(setStatus); }} />
      <div className="row update-row">
        <Button icon="refresh" disabled={checking} onClick={check}>Проверить сейчас</Button>
        <span className="pane-note">{line}</span>
      </div>
      {status.available && !status.canInstall && <p className="pane-note">Эта копия запущена не из установщика, поэтому сама не обновится. Скачай новую версию со страницы релиза.</p>}
    </Field>
  );
}
