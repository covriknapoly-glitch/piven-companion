import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { WebApi } from "./bridge";
import { Icon } from "./icons";
import { PHONE_URL } from "./link";
import { phoneHost } from "./linkhost";
import { forgetLink, needsHomeScreen, PhoneLink, phoneApi, savedLink, waitForPairing, type LinkStatus } from "./phone";
import { Button, Decor, Field, Logo } from "./ui";

let link: PhoneLink | null = null;

/** The phone's first screen: a code to type on the computer, then the wait for a connection. */
export function PhoneStart({ onReady }: { onReady: (api: WebApi) => void }) {
  const [paired, setPaired] = useState(() => Boolean(savedLink()));
  const [pin, setPin] = useState("");
  const [skipHint, setSkipHint] = useState(false);
  const [status, setStatus] = useState<LinkStatus>("connecting");
  const ready = useRef(false);

  useEffect(() => {
    if (paired || (needsHomeScreen() && !skipHint)) return;
    let stopped = false;
    void waitForPairing(setPin, () => stopped).then((result) => { if (result && !stopped) setPaired(true); });
    return () => { stopped = true; };
  }, [paired, skipHint]);

  useEffect(() => {
    const saved = savedLink();
    if (!paired || !saved) return;
    link = new PhoneLink(saved);
    const update = () => {
      setStatus(link!.status);
      if (link!.status === "online" && !ready.current) { ready.current = true; onReady(phoneApi(link!)); }
    };
    const stop = link.subscribe(update);
    void link.connect();
    return stop;
  }, [paired]);

  const unpair = () => { forgetLink(); window.location.reload(); };

  if (!paired && needsHomeScreen() && !skipHint) {
    return (
      <div className="splash phone-start"><Decor corner="br" />
        <Logo size={56} />
        <h2>Сначала добавь PIVEN на экран «Домой»</h2>
        <p>Нажми «Поделиться» внизу Safari, затем «На экран Домой», и открой PIVEN оттуда. Привязка, сделанная в Safari, там не сохранится.</p>
        <button type="button" className="link-btn" onClick={() => setSkipHint(true)}>Всё равно продолжить здесь</button>
      </div>
    );
  }
  if (!paired) {
    return (
      <div className="splash phone-start"><Decor corner="br" />
        <Logo size={56} />
        <h2>Привяжи телефон к компьютеру</h2>
        <p>Открой PIVEN на компьютере: Настройки → Телефон, и введи этот код.</p>
        <div className="phone-pin" aria-live="polite">{pin ? `${pin.slice(0, 3)} ${pin.slice(3)}` : "··· ···"}</div>
        <p className="phone-small">Код меняется каждые 2 минуты.</p>
      </div>
    );
  }
  return (
    <div className="splash phone-start"><Decor corner="br" />
      <Logo size={56} pulse={status !== "offline"} />
      <h2>{status === "offline" ? "Компьютер не отвечает" : "Подключаюсь к компьютеру…"}</h2>
      {status === "offline" && <p>Проверь, что компьютер включён и PIVEN запущен, можно в трее. Подключение продолжает пробовать само.</p>}
      <button type="button" className="link-btn" onClick={unpair}>Отвязать этот телефон</button>
    </div>
  );
}

/** A thin line on the phone when the computer drops off. */
export function PhoneBanner() {
  const status = useSyncExternalStore((listener) => link?.subscribe(listener) ?? (() => undefined), () => link?.status ?? "online");
  if (status === "online") return null;
  return <div className="phone-banner" role="status"><span className="spinner" /> {status === "offline" ? "Компьютер не отвечает, пробую снова…" : "Переподключаюсь к компьютеру…"}</div>;
}

const ago = (seconds: number) => {
  if (!seconds) return "ещё не подключался";
  const minutes = Math.round((Date.now() / 1000 - seconds) / 60);
  return minutes < 2 ? "был в сети только что" : minutes < 60 ? `был в сети ${minutes} мин назад` : `был в сети ${new Date(seconds * 1000).toLocaleDateString("ru-RU")}`;
};

/** Settings on the computer: type the phone's code, see and remove paired phones. */
export function PhonePane({ api }: { api: WebApi }) {
  const [devices, setDevices] = useState<{ id: string; name: string; created: number; seen: number }[]>([]);
  const [code, setCode] = useState("");
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [armed, setArmed] = useState("");
  const online = useSyncExternalStore((listener) => phoneHost.subscribe(listener), () => phoneHost.online.size ? [...phoneHost.online].sort().join(",") : "");
  const load = () => { void api.remote_devices().then(setDevices); };
  useEffect(load, [api, online]);

  const pair = () => {
    setWorking(true); setResult(null);
    void phoneHost.pair(code).then((reply) => {
      setWorking(false);
      setResult(reply.ok ? { ok: true, text: `Подключён: ${reply.name}.` } : { ok: false, text: reply.error ?? "Не получилось." });
      if (reply.ok) { setCode(""); load(); }
    });
  };
  const forget = (id: string) => {
    if (armed !== id) { setArmed(id); window.setTimeout(() => setArmed(""), 4000); return; }
    setArmed("");
    void api.remote_forget(id).then(() => phoneHost.refresh()).then(load);
  };

  return <>
    <Field label="Подключить телефон" hint={<>Открой на телефоне <span className="mono" data-i18n-skip>{PHONE_URL.replace("https://", "")}</span>, добавь на экран «Домой» и введи сюда код, который он покажет.</>}>
      <div className="row grow">
        <input className="input mono phone-code" value={code} inputMode="numeric" autoComplete="off" placeholder="000 000" maxLength={7}
          onChange={(event) => setCode(event.target.value.replace(/[^\d ]/g, ""))} onKeyDown={(event) => { if (event.key === "Enter" && code.replace(/\D/g, "").length === 6) pair(); }} />
        <Button kind="primary" disabled={working || code.replace(/\D/g, "").length !== 6} onClick={pair}>{working ? "Подключаю…" : "Подключить"}</Button>
      </div>
      {result && <div className={`inline-alert ${result.ok ? "ok" : ""}`}><Icon name={result.ok ? "check" : "alert"} size={15} /> {result.text}</div>}
    </Field>
    <Field label="Привязанные телефоны" hint="Телефон управляет PIVEN так же, как это окно: пишет агенту и подтверждает его действия.">
      {!devices.length && <p className="pane-note">Пока нет ни одного.</p>}
      <div className="disk-list">
        {devices.map((device) => (
          <div key={device.id} className="disk-row">
            <span className="disk-name">{device.name}</span>
            <span className="disk-size">{phoneHost.online.has(device.id) ? <b className="phone-online">в сети</b> : ago(device.seen)}</span>
            <Button kind={armed === device.id ? "danger" : "ghost"} onClick={() => forget(device.id)}>{armed === device.id ? "Точно отключить?" : "Отключить"}</Button>
          </div>
        ))}
      </div>
    </Field>
    <p className="pane-note">Компьютер должен быть включён, а PIVEN запущен, можно свёрнутым в трей. Телефон находит компьютер через ntfy.sh, а дальше они общаются напрямую, и всё зашифровано. В некоторых мобильных сетях прямое соединение не получается.</p>
  </>;
}
