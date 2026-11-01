"""Video through ComfyUI: the user's own workflow does the work (see CompanionCore.generate_video_via_comfyui);
this module only finds what a finished prompt saved."""
from __future__ import annotations


def output_files(history_entry):
    """Saved files of a finished prompt: [{"filename", "subfolder", "type"}], videos first."""
    records = []
    for node_output in (history_entry or {}).get("outputs", {}).values():
        for values in node_output.values():
            if isinstance(values, list):
                records += [item for item in values if isinstance(item, dict) and item.get("filename")]
    return sorted(records, key=lambda item: not str(item["filename"]).lower().endswith((".mp4", ".webm", ".mkv", ".gif", ".webp")))
