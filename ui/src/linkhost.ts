// The computer's side of the phone link. It runs inside the PIVEN window and answers the phone's calls
// with the same engine the window uses, except for things that only make sense in front of the computer.
import type { WebApi } from "./bridge";
import { ICE_SERVERS, Mailbox, Wire, gathered, randomToken, topicFor, type Packet } from "./link";

const PC_ONLY = new Set([
  "pick_images", "pick_path", "code_pick_folder", "code_open_folder", "open_data_folder", "open_file", "open_url", "save_copy", "export_chat",
  "set_title_theme", "restart_app", "copy_text", "speak", "start_listening", "stop_listening", "set_mic_muted", "start_dictation", "stop_dictation",
  "browser_place", "browser_go", "browser_command", "browser_state",
]);
const QUIET: Record<string, unknown> = { pick_images: [], pick_path: "", set_title_theme: { ok: true } };

type Device = { id: string; secret: string; mailbox: Mailbox; peer: RTCPeerConnection | null };

export async function answerPhone(api: WebApi, method: string, args: unknown): Promise<unknown> {
  if (method.startsWith("remote_") || method.startsWith("_") || PC_ONLY.has(method)) {
    return method in QUIET ? QUIET[method] : { ok: false, error: "Это можно сделать только на компьютере." };
  }
  const handler = (api as unknown as Record<string, unknown>)[method];
  if (typeof handler !== "function") return { ok: false, error: "Неизвестная команда." };
  return await (handler as (...values: unknown[]) => Promise<unknown>).apply(api, Array.isArray(args) ? args : []);
}

class Host {
  private api: WebApi | null = null;
  private devices = new Map<string, Device>();
  private listeners = new Set<() => void>();
  readonly online = new Set<string>();

  start(api: WebApi) {
    if (this.api || typeof RTCPeerConnection === "undefined") return;
    this.api = api;
    void this.refresh();
  }

  subscribe(listener: () => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private changed() {
    this.listeners.forEach((listener) => listener());
  }

  async refresh() {
    if (!this.api) return;
    const saved = await this.api.remote_secrets();
    for (const [id, device] of this.devices) {
      if (saved.some((item) => item.id === id)) continue;
      device.mailbox.close();
      device.peer?.close();
      this.devices.delete(id);
      this.online.delete(id);
    }
    for (const { id, secret } of saved) {
      if (this.devices.has(id)) continue;
      const device: Device = { id, secret, peer: null, mailbox: null as unknown as Mailbox };
      device.mailbox = new Mailbox(await topicFor("device", secret), secret, (message) => { void this.offered(device, message); });
      this.devices.set(id, device);
      void device.mailbox.open();
    }
    this.changed();
  }

  private async offered(device: Device, message: Record<string, unknown>) {
    if (message.type !== "offer" || typeof message.sdp !== "string") return;
    device.peer?.close();
    const peer = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    device.peer = peer;
    const gone = () => {
      if (device.peer !== peer) return;
      this.online.delete(device.id);
      this.changed();
    };
    peer.onconnectionstatechange = () => { if (["failed", "closed", "disconnected"].includes(peer.connectionState)) gone(); };
    peer.ondatachannel = (event) => {
      const channel = event.channel;
      const wire = new Wire(channel, (packet) => { if (packet.t === "call") void this.call(wire, packet); });
      channel.onopen = () => {
        this.online.add(device.id);
        this.changed();
        void this.api?.remote_update(device.id, null, true);
      };
      channel.onclose = gone;
    };
    await peer.setRemoteDescription({ type: "offer", sdp: message.sdp });
    await peer.setLocalDescription(await peer.createAnswer());
    await gathered(peer);
    await device.mailbox.send({ type: "answer", session: message.session, sdp: peer.localDescription?.sdp ?? "" });
  }

  private async call(wire: Wire, packet: Extract<Packet, { t: "call" }>) {
    if (!this.api) return;
    try {
      wire.send({ t: "ret", id: packet.id, ok: true, r: await answerPhone(this.api, packet.m, packet.a) });
    } catch (error) {
      wire.send({ t: "ret", id: packet.id, ok: false, e: String(error) });
    }
  }

  /** Steam Link style: the phone shows a code, the computer answers it with a lasting secret. */
  async pair(code: string): Promise<{ ok: boolean; name?: string; error?: string }> {
    const api = this.api;
    if (!api) return { ok: false, error: "Связь с телефоном ещё не готова." };
    const id = randomToken(12);
    const secret = randomToken(32);
    const pin = code.replace(/\D/g, "");
    let finish: (result: { ok: boolean; name?: string; error?: string }) => void = () => undefined;
    const done = new Promise<{ ok: boolean; name?: string; error?: string }>((resolve) => { finish = resolve; });
    const mailbox = new Mailbox(await topicFor("pair", pin), pin, (message) => {
      if (message.type !== "hello" || message.id !== id) return;
      const name = String(message.name || "Телефон").slice(0, 60);
      void api.remote_add(id, secret, name).then(() => this.refresh()).then(() => finish({ ok: true, name }));
    });
    await mailbox.open();
    const offer = () => { void mailbox.send({ type: "paired", id, secret }); };
    offer();
    const repeat = window.setInterval(offer, 5000);
    const timer = window.setTimeout(() => finish({ ok: false, error: "Телефон не ответил. Проверь код: он меняется каждые 2 минуты." }), 25000);
    const result = await done;
    window.clearInterval(repeat);
    window.clearTimeout(timer);
    mailbox.close();
    return result;
  }
}

export const phoneHost = new Host();
