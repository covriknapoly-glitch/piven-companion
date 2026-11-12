// The phone and the computer find each other through a public ntfy.sh topic, then talk over a direct WebRTC
// data channel. Everything sent through ntfy is sealed with the pair's secret, so the service sees only noise.

const NTFY = "https://ntfy.sh";
export const PHONE_URL = "https://covriknapoly-glitch.github.io/piven-companion/";
export const ICE_SERVERS: RTCIceServer[] = [{ urls: ["stun:stun.l.google.com:19302", "stun:stun.cloudflare.com:3478"] }];
const CHUNK = 3000;
const FRAME = 60000;

const encoder = new TextEncoder();
const decoder = new TextDecoder();

export function toBase64(bytes: Uint8Array) {
  let text = "";
  for (let start = 0; start < bytes.length; start += 0x8000) text += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
  return btoa(text);
}

export function fromBase64(text: string) {
  const raw = atob(text);
  const bytes = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) bytes[index] = raw.charCodeAt(index);
  return bytes;
}

export const randomToken = (size = 32) => toBase64(crypto.getRandomValues(new Uint8Array(size))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function hash(text: string) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(text)));
}

export async function topicFor(kind: "pair" | "device", secret: string) {
  const bytes = await hash(`piven-${kind}-v1:${secret}`);
  return "piven" + Array.from(bytes.subarray(0, 20), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function keyFor(secret: string) {
  return crypto.subtle.importKey("raw", await hash(`piven-key-v1:${secret}`), "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function seal(secret: string, value: unknown) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const body = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await keyFor(secret), encoder.encode(JSON.stringify(value))));
  const joined = new Uint8Array(iv.length + body.length);
  joined.set(iv);
  joined.set(body, iv.length);
  return toBase64(joined);
}

async function unseal(secret: string, text: string): Promise<Record<string, unknown> | null> {
  try {
    const bytes = fromBase64(text);
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: bytes.subarray(0, 12) }, await keyFor(secret), bytes.subarray(12));
    const value = JSON.parse(decoder.decode(plain));
    return value && typeof value === "object" ? value as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

/** A sealed mailbox on ntfy.sh. Messages are not stored there, so both sides must be listening. */
export class Mailbox {
  private source: EventSource | null = null;
  private parts = new Map<string, string[]>();

  constructor(private topic: string, private secret: string, private onMessage: (message: Record<string, unknown>) => void) {}

  /** Resolves once the subscription is live, so nothing sent to it right after is missed. */
  open() {
    if (this.source) return Promise.resolve();
    this.source = new EventSource(`${NTFY}/${this.topic}/sse`);
    const ready = new Promise<void>((resolve) => {
      const timer = window.setTimeout(resolve, 6000);
      this.source?.addEventListener("open", () => { window.clearTimeout(timer); window.setTimeout(resolve, 300); }, { once: true });
    });
    this.source.onmessage = (event) => {
      let text = "";
      try {
        const data = JSON.parse(event.data);
        if (data.event !== "message") return;
        text = String(data.message ?? "");
      } catch {
        return;
      }
      const match = /^(\w+) (\d+)\/(\d+) (.*)$/s.exec(text);
      if (!match) return;
      const [, id, place, count, piece] = match;
      const parts = this.parts.get(id) ?? [];
      parts[Number(place)] = piece;
      if (parts.filter((part) => part !== undefined).length < Number(count)) { this.parts.set(id, parts); return; }
      this.parts.delete(id);
      void unseal(this.secret, parts.join("")).then((message) => { if (message) this.onMessage(message); });
    };
    return ready;
  }

  async send(message: Record<string, unknown>) {
    const text = await seal(this.secret, message);
    const id = randomToken(6).replace(/[^A-Za-z0-9]/g, "x");
    const count = Math.ceil(text.length / CHUNK);
    for (let place = 0; place < count; place += 1) {
      await fetch(`${NTFY}/${this.topic}?cache=no`, { method: "POST", body: `${id} ${place}/${count} ${text.slice(place * CHUNK, (place + 1) * CHUNK)}` });
    }
  }

  close() {
    this.source?.close();
    this.source = null;
  }
}

export async function gathered(peer: RTCPeerConnection, wait = 4000) {
  if (peer.iceGatheringState === "complete") return;
  await new Promise<void>((resolve) => {
    const timer = window.setTimeout(resolve, wait);
    peer.addEventListener("icegatheringstatechange", () => {
      if (peer.iceGatheringState === "complete") { window.clearTimeout(timer); resolve(); }
    });
  });
}

export type Packet = { t: "call"; id: number; m: string; a: unknown[] } | { t: "ret"; id: number; ok: boolean; r?: unknown; e?: string } | { t: "ping" };

/** JSON packets over a data channel, split into frames that every browser accepts. */
export class Wire {
  private frames = new Map<string, string[]>();

  constructor(private channel: RTCDataChannel, private onPacket: (packet: Packet) => void) {
    channel.onmessage = (event) => this.receive(String(event.data));
  }

  send(packet: Packet) {
    if (this.channel.readyState !== "open") return false;
    const text = JSON.stringify(packet);
    if (text.length <= FRAME) { this.channel.send(text); return true; }
    const id = randomToken(6);
    const count = Math.ceil(text.length / FRAME);
    for (let place = 0; place < count; place += 1) this.channel.send(JSON.stringify({ f: id, i: place, n: count, d: text.slice(place * FRAME, (place + 1) * FRAME) }));
    return true;
  }

  private receive(text: string) {
    let value: Record<string, unknown>;
    try { value = JSON.parse(text); } catch { return; }
    if (typeof value.f === "string") {
      const parts = this.frames.get(value.f) ?? [];
      parts[Number(value.i)] = String(value.d ?? "");
      if (parts.filter((part) => part !== undefined).length < Number(value.n)) { this.frames.set(value.f, parts); return; }
      this.frames.delete(value.f);
      try { value = JSON.parse(parts.join("")); } catch { return; }
    }
    this.onPacket(value as Packet);
  }
}
