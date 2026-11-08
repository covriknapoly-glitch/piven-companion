"""Machine-readable "made by AI" marks on generated files (EU AI Act, article 50(2))."""
from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

XMP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="" xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
    'Iptc4xmpExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia" '
    'xmp:CreatorTool="PIVEN Companion"/></rdf:RDF></x:xmpmeta>'
).encode("utf-8")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MP4_XMP_ID = bytes.fromhex("be7acfcb97a942e89c71999491e3afac")


def _png(data):
    if data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    end = 16 + struct.unpack(">I", data[8:12])[0] + 4
    body = b"XML:com.adobe.xmp\0\0\0\0\0" + XMP
    chunk = struct.pack(">I", len(body)) + b"iTXt" + body + struct.pack(">I", zlib.crc32(b"iTXt" + body))
    return data[:end] + chunk + data[end:]


def _jpeg(data):
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    place = 2
    if data[2:4] == b"\xff\xe0":
        place = 4 + struct.unpack(">H", data[4:6])[0]
    payload = b"http://ns.adobe.com/xap/1.0/\0" + XMP
    return data[:place] + b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + data[place:]


def _replace(path, data):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _can_append_box(path):
    """A last box of size 0 runs to the end of the file and would swallow anything added after it."""
    total, place = path.stat().st_size, 0
    with path.open("rb") as file:
        while place < total:
            file.seek(place)
            head = file.read(16)
            if len(head) < 8:
                return False
            size = struct.unpack(">I", head[:4])[0]
            if size == 1 and len(head) == 16:
                size = struct.unpack(">Q", head[8:16])[0]
            if size < 8:
                return False
            place += size
    return place == total


def _inside(path):
    suffix = path.suffix.lower()
    if suffix == ".png":
        _replace(path, _png(path.read_bytes()))
    elif suffix in (".jpg", ".jpeg"):
        _replace(path, _jpeg(path.read_bytes()))
    elif suffix in (".mp4", ".m4v", ".mov") and _can_append_box(path):
        with path.open("ab") as file:
            file.write(struct.pack(">I", 8 + len(MP4_XMP_ID) + len(XMP)) + b"uuid" + MP4_XMP_ID + XMP)
    else:
        return False
    return True


def mark_file(path):
    """Marks the file itself where the format allows it, otherwise beside it. A failure never costs the user the file."""
    path = Path(path)
    try:
        if _inside(path):
            return True
    except (OSError, ValueError, struct.error):
        pass
    try:
        path.with_name(path.name + ".xmp").write_bytes(XMP)
        return True
    except OSError:
        return False
