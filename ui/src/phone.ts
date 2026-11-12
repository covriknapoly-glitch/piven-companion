// The phone's side of the link: pairing by code, keeping a direct channel to the computer, and an engine
// object that looks to the interface exactly like the one inside the PIVEN window.
import type { WebApi } from "./bridge";
import { ICE_SERVERS, Mailbox, Wire, gathered, randomToken, topicFor, type Packet } from "./link";

const STORE = "piven-phone-link";
export type SavedLink = { id: string; secret: string };
export type LinkStatus = "connecting" | "online" | "offline";

export function savedLink(): SavedLink | null {
  try {
    const value = JSON.parse(localStorage.getItem(STORE) ?? "null");
    return value && typeof value.id === "string" && typeof value.secret === "string" ? value : null;
  } catch {
    return null;
  }
}

export function forgetLink() {
  try { localStorage.removeItem(STORE); } catch { }
}

export function phoneName() {
  const agent = navigator.userAgent;
  return /iPhone/.test(agent) ? "iPhone" : /iPad/.test(agent) ? "iPad" : /Android/.test(agent) ? "Android" : "Телефон";
}

/** iOS keeps a separate storage for the home screen icon, so pairing in Safari would be lost there. */
export const needsHomeScreen = () => /iPhone|iPad/.test(navigator.userAgent) && !(navigator as Navigator & { standalone?: boolean }).standalone;

const newPin = () => String(crypto.getRandomValues(new Uint32Array(1))[0] % 1000000).padStart(6, "0");

/** Shows a code, waits for the computer to answer it, and keeps the secret it sends. */
export async function waitForPairing(onPin: (pin: string) => void, stopped: () => boolean): Promise<SavedLink | null> {
  while (!stopped()) {
    const pin = newPin();
    let mailbox: Mailbox | null = null;
    const paired = await new Promise<SavedLink | null>((resolve) => {
      const timer = window.setTimeout(() => resolve(null), 120000);
      const watch = window.setInterval(() => { if (stopped()) { window.clearTimeout(timer); resolve(null); } }, 500);
      void topicFor("pair", pin).then((topic) => {
        mailbox = new Mailbox(topic, pin, (message) => {
          if (message.type !== "paired" || typeof message.id !== "string" || typeof message.secret !== "string") return;
          window.clearTimeout(timer);
          window.clearInterval(watch);
          resolve({ id: message.id, secret: message.secret });
        });
        void mailbox.open().then(() => onPin(pin));
      });
    });
    if (paired) {
      const box = mailbox as Mailbox | null;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        await box?.send({ type: "hello", id: paired.id, name: phoneName() });
        await new Promise((resolve) => window.setTimeout(resolve, 700));
      }
      box?.close();
      try { localStorage.setItem(STORE, JSON.stringify(paired)); } catch { }
      return paired;
    }
    (mailbox as Mailbox | null)?.close();
  }
  return null;
}

type Pending = { method: string; args: unknown[]; resolve: (value: unknown) => void };

export class PhoneLink {
  status: LinkStatus = "connecting";
  private listeners = new Set<() => void>();
  private mailbox: Mailbox | null = null;
  private peer: RTCPeerConnection | null = null;
  private wire: Wire | null = null;
  private session = "";
  private answer: ((sdp: string) => void) | null = null;
  private waiting: Pending[] = [];
  private sent = new Map<number, Pending>();
  private next = 1;
  private failures = 0;
  private running = false;

  constructor(private saved: SavedLink) {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && this.status !== "online") void this.connect();
    });
  }

  subscribe(listener: () => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private set(status: LinkStatus) {
    this.status = status;
    this.listeners.forEach((listener) => listener());
  }

  async connect() {
    if (this.running) return;
    this.running = true;
    try {
      if (!this.mailbox) {
        this.mailbox = new Mailbox(await topicFor("device", this.saved.secret), this.saved.secret, (message) => {
          if (message.type === "answer" && message.session === this.session && typeof message.sdp === "string") this.answer?.(message.sdp);
        });
        await this.mailbox.open();
      }
      while (this.status !== "online") {
        if (await this.attempt()) { this.failures = 0; break; }
        this.failures += 1;
        if (this.failures >= 2) this.set("offline");
        await new Promise((resolve) => window.setTimeout(resolve, Math.min(15000, 2000 * this.failures)));
      }
    } finally {
      this.running = false;
    }
  }

  private async attempt() {
    this.peer?.close();
    const peer = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    this.peer = peer;
    const channel = peer.createDataChannel("piven", { ordered: true });
    const opened = new Promise<boolean>((resolve) => {
      const timer = window.setTimeout(() => resolve(false), 20000);
      channel.onopen = () => { window.clearTimeout(timer); resolve(true); };
    });
    await peer.setLocalDescription(await peer.createOffer());
    await gathered(peer);
    this.session = randomToken(8);
    const answered = new Promise<string | null>((resolve) => {
      const timer = window.setTimeout(() => resolve(null), 12000);
      this.answer = (sdp) => { window.clearTimeout(timer); resolve(sdp); };
    });
    await this.mailbox?.send({ type: "offer", session: this.session, sdp: peer.localDescription?.sdp ?? "" });
    const sdp = await answered;
    this.answer = null;
    if (!sdp || this.peer !== peer) { peer.close(); return false; }
    await peer.setRemoteDescription({ type: "answer", sdp });
    if (!await opened || this.peer !== peer) { peer.close(); return false; }
    this.wire = new Wire(channel, (packet) => this.received(packet));
    const lost = () => {
      if (this.peer !== peer) return;
      this.wire = null;
      this.set("connecting");
      this.dropSent();
      void this.connect();
    };
    channel.onclose = lost;
    peer.onconnectionstatechange = () => { if (["failed", "disconnected", "closed"].includes(peer.connectionState)) lost(); };
    this.set("online");
    const queued = this.waiting;
    this.waiting = [];
    queued.forEach((item) => this.transmit(item));
    return true;
  }

  private received(packet: Packet) {
    if (packet.t !== "ret") return;
    const pending = this.sent.get(packet.id);
    if (!pending) return;
    this.sent.delete(packet.id);
    pending.resolve(packet.ok ? packet.r : { ok: false, error: packet.e || "Компьютер не смог выполнить команду." });
  }

  /** Calls that were in flight when the line dropped are not repeated: they may already have run. */
  private dropSent() {
    const lost = [...this.sent.values()];
    this.sent.clear();
    lost.forEach((item) => item.resolve(item.method === "poll" ? { version: item.args[0], unchanged: true } : { ok: false, error: "Связь с компьютером прервалась. Проверь, выполнилось ли действие." }));
  }

  private transmit(item: Pending) {
    const id = this.next++;
    this.sent.set(id, item);
    if (!this.wire?.send({ t: "call", id, m: item.method, a: item.args })) {
      this.sent.delete(id);
      this.waiting.push(item);
    }
  }

  request(method: string, args: unknown[]) {
    return new Promise<unknown>((resolve) => {
      const item = { method, args, resolve };
      if (this.status === "online" && this.wire) this.transmit(item);
      else if (method === "poll") resolve({ version: args[0], unchanged: true });
      else this.waiting.push(item);
    });
  }
}

export function phoneApi(link: PhoneLink): WebApi {
  const local: Record<string, (...args: unknown[]) => Promise<unknown>> = {
    copy_text: async (text) => { try { await navigator.clipboard.writeText(String(text)); return { ok: true }; } catch { return { ok: false, error: "Телефон не дал скопировать." }; } },
    set_title_theme: async () => ({ ok: true }),
    open_url: async (url) => { window.open(String(url), "_blank", "noopener"); return { ok: true }; },
    pick_images: async () => [],
  };
  return new Proxy({}, {
    get: (_, name) => {
      if (typeof name !== "string" || name === "then") return undefined;
      return local[name] ?? ((...args: unknown[]) => link.request(name, args));
    },
  }) as WebApi;
}
