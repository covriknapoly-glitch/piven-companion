from __future__ import annotations

import io
import struct
import subprocess
import threading
import urllib.parse
import urllib.request

USER_AGENT = "PIVEN-Companion/1.0"
COMPUTE_BYTES = 450 * 2**20
PROJECTOR_EXTRA = 250 * 2**20
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_lock = threading.Lock()
_cache: dict = {}
_gpu: list = []


def _exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise EOFError("GGUF header ended early")
    return data


def _value(stream, kind):
    if kind in _SCALARS:
        fmt = _SCALARS[kind]
        return struct.unpack(fmt, _exact(stream, struct.calcsize(fmt)))[0]
    if kind == 8:
        (length,) = struct.unpack("<Q", _exact(stream, 8))
        return _exact(stream, length).decode("utf-8", errors="replace")
    if kind == 9:
        item_kind, count = struct.unpack("<IQ", _exact(stream, 12))
        if item_kind in _SCALARS and count <= 4096:
            return [_value(stream, item_kind) for _ in range(count)]
        for _ in range(count):
            _value(stream, item_kind)
        return None
    raise ValueError(f"unknown GGUF value type {kind}")


def read_metadata(stream):
    if _exact(stream, 4) != b"GGUF":
        raise ValueError("not a GGUF file")
    version, _tensors, count = struct.unpack("<IQQ", _exact(stream, 20))
    if version < 2:
        raise ValueError("GGUF v1 is not supported")
    meta = {}
    for _ in range(count):
        (length,) = struct.unpack("<Q", _exact(stream, 8))
        key = _exact(stream, length).decode("utf-8", errors="replace")
        (kind,) = struct.unpack("<I", _exact(stream, 4))
        value = _value(stream, kind)
        if value is not None:
            meta[key] = value
    return meta


def local_metadata(path):
    key = ("file", str(path), path.stat().st_mtime_ns)
    with _lock:
        if key in _cache:
            return _cache[key]
    try:
        with open(path, "rb") as handle:
            meta = read_metadata(io.BufferedReader(handle, 1 << 20))
    except Exception:
        meta = {}
    with _lock:
        _cache[key] = meta
    return meta


def remote_metadata(repo_id, file_path, token=""):
    key = ("hf", repo_id, file_path)
    with _lock:
        if key in _cache:
            return _cache[key]
    quoted = "/".join(urllib.parse.quote(part, safe="") for part in str(file_path).split("/"))
    url = f"https://huggingface.co/{urllib.parse.quote(repo_id, safe='/')}/resolve/main/{quoted}"
    headers = {"User-Agent": USER_AGENT, "Range": "bytes=0-"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            meta = read_metadata(io.BufferedReader(response, 1 << 20))
    except Exception:
        meta = {}
    with _lock:
        _cache[key] = meta
    return meta


def _number(value):
    if isinstance(value, list):
        numbers = [item for item in value if isinstance(item, (int, float))]
        return max(numbers) if numbers else None
    return value if isinstance(value, (int, float)) else None


def kv_cache_bytes(meta, context):
    arch = meta.get("general.architecture")
    if not arch:
        return 0
    raw = lambda name: meta.get(f"{arch}.{name}")
    get = lambda name: _number(raw(name))
    layers, heads = int(get("block_count") or 0), get("attention.head_count")
    if not layers or not heads:
        return 0
    per_layer = lambda value, default: value if isinstance(value, list) and len(value) == layers else [default] * layers
    kv_heads = per_layer(raw("attention.head_count_kv"), _number(raw("attention.head_count_kv")) or heads)
    window = int(get("attention.sliding_window") or 0)
    pattern = raw("attention.sliding_window_pattern")
    if isinstance(pattern, list) and len(pattern) == layers:
        sliding = [bool(item) for item in pattern]
    elif window and isinstance(pattern, (int, float)) and pattern > 1:
        sliding = [(index + 1) % int(pattern) != 0 for index in range(layers)]
    elif window and arch in ("gemma3", "gemma3n"):
        sliding = [(index + 1) % 6 != 0 for index in range(layers)]
    elif window and arch == "gemma2":
        sliding = [index % 2 == 0 for index in range(layers)]
    else:
        sliding = [False] * layers
    shared = int(get("attention.shared_kv_layers") or 0)
    width = get("embedding_length") or 0
    key_size = get("attention.key_length") or (width // heads if width else 0)
    value_size = get("attention.value_length") or key_size
    key_swa = get("attention.key_length_swa") or key_size
    value_swa = get("attention.value_length_swa") or value_size
    tokens = min(context, int(get("context_length") or context))
    window_tokens = min(tokens, window + 512) if window else tokens
    total = 0
    for index in range(layers - shared):
        if sliding[index]:
            total += window_tokens * kv_heads[index] * (key_swa + value_swa)
        else:
            total += tokens * kv_heads[index] * (key_size + value_size)
    return int(total * 2)


GPU_BANDWIDTH = {"RTX 5090": 1792, "RTX 5080": 960, "RTX 5070 Ti": 896, "RTX 5070": 672, "RTX 5060 Ti": 448, "RTX 5060": 448,
                 "RTX 5050": 320, "RTX 4090": 1008, "RTX 4080 SUPER": 736, "RTX 4080": 717, "RTX 4070 Ti SUPER": 672,
                 "RTX 4070 Ti": 504, "RTX 4070 SUPER": 504, "RTX 4070": 504, "RTX 4060 Ti": 288, "RTX 4060": 272,
                 "RTX 3090 Ti": 1008, "RTX 3090": 936, "RTX 3080 Ti": 912, "RTX 3080": 760, "RTX 3070 Ti": 608, "RTX 3070": 448,
                 "RTX 3060 Ti": 448, "RTX 3060": 360, "RTX 3050": 224, "RTX 2080 Ti": 616, "RTX 2080": 448, "RTX 2070": 448,
                 "RTX 2060": 336, "GTX 1660": 192, "GTX 1080 Ti": 484, "GTX 1080": 320, "GTX 1070": 256,
                 "RTX A6000": 768, "RTX A4000": 448, "A100": 1555, "H100": 2039, "L40": 864}
EFFICIENCY = 0.65
LAYER_OVERHEAD = 0.00004
KV_FILL = 0.25
_ram = []


def ram_bandwidth():
    if _ram:
        return _ram[0]
    value = 50.0
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command",
                                 "Get-CimInstance Win32_PhysicalMemory | ForEach-Object { $_.ConfiguredClockSpeed }"],
                                capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        speeds = [int(line) for line in result.stdout.split() if line.strip().isdigit() and int(line) > 0]
        if speeds:
            value = min(speeds) * 8 * min(len(speeds), 2) / 1000
    except Exception:
        pass
    _ram.append(value)
    return value


def active_fraction(meta):
    arch = meta.get("general.architecture", "")
    experts = _number(meta.get(f"{arch}.expert_count"))
    used = _number(meta.get(f"{arch}.expert_used_count"))
    if experts and used and experts > used:
        return 0.05 + 0.95 * used / experts
    return 1.0


def speed(weights, meta, total, kv, other, reserved=0, vram_limit=0):
    gpu_total, name = gpu_memory(), gpu_name()
    gpu_bandwidth = next((value for key, value in sorted(GPU_BANDWIDTH.items(), key=lambda item: -len(item[0])) if key in name), 400)
    room = gpu_total * 0.95 - reserved if gpu_total else 0
    if vram_limit:
        room = min(room, vram_limit) if gpu_total else vram_limit
    arch = meta.get("general.architecture", "")
    experts, used = _number(meta.get(f"{arch}.expert_count")), _number(meta.get(f"{arch}.expert_used_count"))
    routed = used / experts if experts and used and experts > used else 1.0
    shared = weights * 0.05 if routed < 1 else weights
    room_weights = max(0.0, room - kv - other) if gpu_total else 0.0
    if total <= room:
        gpu_read, ram_read = shared + (weights - shared) * routed, 0.0
    elif routed < 1:
        gpu_experts = max(0.0, min(weights - shared, room_weights - shared))
        gpu_read = min(shared, room_weights) + gpu_experts * routed
        ram_read = max(0.0, shared - room_weights) + (weights - shared - gpu_experts) * routed
    else:
        on_gpu = min(1.0, room_weights / max(weights, 1))
        gpu_read, ram_read = weights * on_gpu, weights * (1 - on_gpu)
    gpu_rate, ram_rate = gpu_bandwidth * 1e9 * EFFICIENCY, ram_bandwidth() * 1e9 * EFFICIENCY
    kv_read = kv * KV_FILL
    seconds = (gpu_read / gpu_rate + ram_read / ram_rate
               + kv_read / (gpu_rate if gpu_read >= ram_read else ram_rate)
               + LAYER_OVERHEAD * (_number(meta.get(f"{meta.get('general.architecture', '')}.block_count")) or 32))
    return round(1 / seconds, 1) if seconds > 0 else 0.0


def estimate(weights, meta, context, projector=0, kv_share=1.0, reserved=0, vram_limit=0):
    kv = kv_cache_bytes(meta, context) * kv_share
    other = COMPUTE_BYTES + (projector + PROJECTOR_EXTRA if projector else 0)
    total = int(weights + kv + other)
    return {"total": total, "weights": int(weights), "kv": int(kv), "other": int(other),
            "speed": speed(weights, meta, total, kv, other, reserved, vram_limit), "measured": False}


def _gpu_info():
    with _lock:
        if _gpu:
            return _gpu
    total, name = 0, ""
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
        memory, name = [part.strip() for part in result.stdout.strip().splitlines()[0].split(",", 1)]
        total = int(memory) * 2**20
    except Exception:
        pass
    with _lock:
        _gpu[:] = [total, name]
    return _gpu


def gpu_memory():
    return _gpu_info()[0]


def gpu_name():
    return _gpu_info()[1]
