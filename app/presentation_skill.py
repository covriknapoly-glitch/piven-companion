"""PowerPoint presentations from a model's plan.

The model designs the deck itself: colours, a pair of fonts, a cover style and a layout for every slide.
Colours that would make text hard to read (contrast below WCAG 4.5:1) are replaced by the nearest of the
prepared presets, and a plan without a design gets a preset that suits its topic.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

FONTS = ("Aptos", "Segoe UI", "Calibri", "Cambria", "Georgia", "Arial", "Trebuchet MS", "Verdana", "Bahnschrift",
         "Candara", "Corbel", "Constantia", "Century Gothic", "Franklin Gothic Medium", "Garamond", "Palatino Linotype",
         "Tahoma", "Times New Roman", "Consolas", "Segoe UI Semibold", "Book Antiqua")
LAYOUTS = ("bullets", "two_columns", "quote", "big_number", "steps", "cards", "section")
COVERS = ("band", "split", "center", "minimal")

# name: (background, surface, text, accent, muted, heading font, body font, cover)
PRESETS = {
    "ocean": ("#0F1E2E", "#F7F8F6", "#1E2A36", "#2A9D8F", "#6B7A88", "Aptos", "Aptos", "band"),
    "sunrise": ("#FFF6EC", "#FFFFFF", "#3B2A1E", "#E76F51", "#8A7363", "Georgia", "Segoe UI", "split"),
    "graphite": ("#16181D", "#1F2228", "#ECEDEF", "#F4B400", "#9AA0A8", "Bahnschrift", "Segoe UI", "minimal"),
    "forest": ("#13261D", "#F3F5EF", "#1F2D24", "#5FA36A", "#6E7F72", "Cambria", "Calibri", "band"),
    "royal": ("#1B1340", "#F6F4FB", "#251E3D", "#7B5CFF", "#726A8C", "Century Gothic", "Segoe UI", "center"),
    "paper": ("#FBFAF7", "#FFFFFF", "#202020", "#C0392B", "#7A7A7A", "Garamond", "Georgia", "minimal"),
    "mint": ("#EFFAF6", "#FFFFFF", "#173A31", "#1F9D7A", "#5F7D74", "Trebuchet MS", "Verdana", "split"),
    "crimson": ("#2B0B12", "#FBF5F6", "#2A1418", "#D7263D", "#8C6F74", "Franklin Gothic Medium", "Segoe UI", "band"),
    "sky": ("#EAF4FF", "#FFFFFF", "#12263F", "#2F80ED", "#5D7189", "Segoe UI Semibold", "Segoe UI", "center"),
    "sand": ("#F4ECDF", "#FFFDF8", "#3A3024", "#B5651D", "#867563", "Palatino Linotype", "Candara", "split"),
    "neon": ("#0B0B12", "#14141F", "#F2F2F7", "#00E5A8", "#8D8DA6", "Consolas", "Segoe UI", "minimal"),
    "slate": ("#263238", "#F5F7F8", "#1E272C", "#FF7043", "#6C7A80", "Corbel", "Corbel", "band"),
}
TOPIC_PRESETS = [  # a plan without a design: a preset by topic words
    (r"природ|эколог|лес|растен|сад|климат", "forest"), (r"мор|океан|вода|путешеств|отпуск", "ocean"),
    (r"истори|литератур|искусств|культур|философ|книг|поэт", "paper"), (r"технолог|программ|код|ии\b|нейросет|компьютер|кибер", "neon"),
    (r"бизнес|финанс|продаж|маркет|стартап|инвест", "slate"), (r"медицин|здоров|спорт|питани", "mint"),
    (r"космос|астроном|физик|наук", "royal"), (r"еда|кухн|рецепт|кофе", "sand"), (r"дет|школ|учёб|урок", "sky"),
]


def _clean_text(value, limit=500):
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def _slug(value):
    clean = re.sub(r"[^\w\s-]", "", str(value), flags=re.UNICODE).strip().lower()
    clean = re.sub(r"[\s_-]+", "_", clean)
    return clean[:60] or "presentation"


def _hex(value):
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(value or "").strip())
    return "#" + match.group(1).upper() if match else None


def _luminance(color):
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _preset(name):
    values = PRESETS[name]
    return dict(zip(("background", "surface", "text", "accent", "muted", "heading_font", "body_font", "cover"), values), name=name)


def choose_design(design, title, slides):
    """The model's design when it is readable; otherwise a preset (named by the model, or by the topic)."""
    design = design if isinstance(design, dict) else {}
    if str(design.get("preset", "")).lower() in PRESETS:
        return _preset(str(design["preset"]).lower())
    colours = {key: _hex(design.get(key)) for key in ("background", "surface", "text", "accent", "muted")}
    if all(colours.values()):
        cover_text = "#FFFFFF" if _luminance(colours["background"]) < 0.4 else "#111111"
        readable = (contrast(colours["text"], colours["surface"]) >= 4.5 and contrast(cover_text, colours["background"]) >= 4.5
                    and contrast(colours["muted"], colours["surface"]) >= 2.5)
        if readable:
            fonts = {key: next((font for font in FONTS if font.lower() == str(design.get(key, "")).strip().lower()), "Aptos")
                     for key in ("heading_font", "body_font")}
            cover = str(design.get("cover", "band")).lower()
            return {**colours, **fonts, "cover": cover if cover in COVERS else "band", "name": "своё оформление"}
    topic = (title + " " + " ".join(str(slide.get("title", "")) for slide in slides)).lower()
    return _preset(next((name for pattern, name in TOPIC_PRESETS if re.search(pattern, topic)), "ocean"))


def _normalize(slides):
    normalized = []
    for index, slide in enumerate(slides, 1):
        if not isinstance(slide, dict):
            raise ValueError(f"Слайд {index} должен быть объектом с заголовком и тезисами.")
        layout = str(slide.get("layout", "bullets")).lower()
        layout = layout if layout in LAYOUTS else "bullets"
        # Models often name the list differently or write it as one text; a slide left without points becomes a
        # section slide (quote or number when the slide has one) instead of failing the whole presentation.
        bullets = next((slide[key] for key in ("bullets", "points", "items", "content", "text") if slide.get(key)), [])
        if isinstance(bullets, str):
            bullets = [line.strip(" -•*\t") for line in bullets.splitlines()]
        bullets = [_clean_text(item, 260) for item in bullets if _clean_text(item)] if isinstance(bullets, list) else []
        if layout in ("bullets", "two_columns", "steps", "cards") and not bullets:
            layout = "quote" if slide.get("quote") else "big_number" if slide.get("number") else "section"
        normalized.append({"title": _clean_text(slide.get("title"), 100), "bullets": bullets[:8], "layout": layout,
                           "number": _clean_text(slide.get("number"), 12), "caption": _clean_text(slide.get("caption"), 160),
                           "quote": _clean_text(slide.get("quote"), 300), "author": _clean_text(slide.get("author"), 80)})
    return normalized


def create_presentation(title, slides, output_root=None, design=None):
    """Save a 16:9 presentation in Documents without overwriting an existing file; returns its path."""
    try:
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches, Pt
    except ImportError as error:
        raise RuntimeError("Для создания PPTX нужен пакет python-pptx в окружении приложения.") from error

    title = _clean_text(title, 120)
    if not isinstance(slides, list) or not 1 <= len(slides) <= 20:
        raise ValueError("Презентация должна содержать от 1 до 20 содержательных слайдов.")
    normalized = _normalize(slides)
    look = choose_design(design, title, slides)

    root = Path(output_root or (Path.home() / "Documents" / "PIVEN" / "Презентации")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = root / f"{stamp}_{_slug(title)}.pptx"
    suffix = 2
    while destination.exists():
        destination = root / f"{stamp}_{_slug(title)}_{suffix}.pptx"
        suffix += 1

    rgb = lambda value: RGBColor.from_string(value.lstrip("#"))  # noqa: E731
    background, surface, ink = rgb(look["background"]), rgb(look["surface"]), rgb(look["text"])
    accent, muted = rgb(look["accent"]), rgb(look["muted"])
    on_dark = _luminance(look["background"]) < 0.4
    cover_ink = RGBColor(255, 255, 255) if on_dark else RGBColor(17, 17, 17)
    cover_soft = rgb("#C9D3DB") if on_dark else rgb("#555555")

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]

    def box(slide, x, y, w, h, text, size, color, bold=False, font=None, align=None, italic=False):
        shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = shape.text_frame
        frame.clear(); frame.word_wrap = True
        for side in ("left", "right", "top", "bottom"):
            setattr(frame, f"margin_{side}", Inches(0.02))
        paragraph = frame.paragraphs[0]
        paragraph.text = text
        paragraph.font.name = font or look["body_font"]
        paragraph.font.size, paragraph.font.bold, paragraph.font.italic = Pt(size), bold, italic
        paragraph.font.color.rgb = color
        if align:
            paragraph.alignment = align
        return shape

    def rect(slide, x, y, w, h, color, shape=None):
        item = slide.shapes.add_shape(shape or MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        item.fill.solid(); item.fill.fore_color.rgb = color; item.line.fill.background()
        return item

    def fill(slide, color):
        slide.background.fill.solid(); slide.background.fill.fore_color.rgb = color

    # cover
    cover = prs.slides.add_slide(blank)
    fill(cover, background)
    date = datetime.now().strftime("%d.%m.%Y")
    if look["cover"] == "split":
        rect(cover, 8.4, 0, 4.933, 7.5, accent)
        box(cover, 0.9, 2.2, 7.1, 2.4, title, 36, cover_ink, True, look["heading_font"])
        box(cover, 0.95, 6.5, 6.5, 0.35, date, 11, cover_soft)
    elif look["cover"] == "center":
        box(cover, 1.2, 2.4, 10.9, 2.0, title, 38, cover_ink, True, look["heading_font"], PP_ALIGN.CENTER)
        rect(cover, 6.17, 4.55, 1.0, 0.06, accent)
        box(cover, 1.2, 4.85, 10.9, 0.4, date, 12, cover_soft, align=PP_ALIGN.CENTER)
    elif look["cover"] == "minimal":
        box(cover, 0.9, 4.3, 11.5, 1.8, title, 40, cover_ink, True, look["heading_font"])
        rect(cover, 0.92, 4.1, 2.2, 0.05, accent)
        box(cover, 0.95, 6.6, 6, 0.35, date, 11, cover_soft)
    else:  # band
        rect(cover, 0.9, 1.05, 0.12, 5.35, accent)
        box(cover, 1.4, 2.15, 10.7, 2.2, title, 34, cover_ink, True, look["heading_font"])
        box(cover, 1.45, 6.55, 10.7, 0.35, date, 11, cover_soft)

    for number, item in enumerate(normalized, 2):
        slide = prs.slides.add_slide(blank)
        layout, bullets = item["layout"], item["bullets"]
        if layout == "section":
            fill(slide, background)
            rect(slide, 0.9, 3.1, 0.12, 1.3, accent)
            box(slide, 1.3, 2.9, 11, 1.6, item["title"], 34, cover_ink, True, look["heading_font"])
            if bullets:
                box(slide, 1.32, 4.5, 10.5, 0.8, bullets[0], 16, cover_soft)
            continue
        fill(slide, surface)
        rect(slide, 0, 0, 13.333, 0.1, accent)
        box(slide, 0.8, 0.6, 11.7, 0.9, item["title"], 28, ink, True, look["heading_font"])
        if layout == "quote":
            box(slide, 1.2, 1.9, 10.9, 3.4, "«" + (item["quote"] or (bullets[0] if bullets else "")) + "»", 30, ink, False,
                look["heading_font"], italic=True)
            if item["author"]:
                box(slide, 1.2, 5.5, 10.9, 0.5, "— " + item["author"], 16, muted)
        elif layout == "big_number":
            box(slide, 0.8, 1.8, 11.7, 2.6, item["number"] or (bullets[0] if bullets else ""), 96, accent, True, look["heading_font"])
            box(slide, 0.85, 4.5, 11, 1.4, item["caption"] or (bullets[1] if len(bullets) > 1 else ""), 20, ink)
        elif layout == "two_columns":
            half = (len(bullets) + 1) // 2
            for column, part in enumerate((bullets[:half], bullets[half:])):
                x, top = 0.8 + column * 6.1, 1.9
                for bullet in part:
                    rect(slide, x, top + 0.13, 0.12, 0.12, accent, MSO_SHAPE.OVAL)
                    box(slide, x + 0.3, top, 5.4, 1.05, bullet, 17, ink)
                    top += min(1.15, 4.7 / max(1, half))
        elif layout == "steps":
            count = len(bullets)
            width = 11.7 / count
            for index, bullet in enumerate(bullets):
                x = 0.8 + index * width
                circle = rect(slide, x, 2.1, 0.62, 0.62, accent, MSO_SHAPE.OVAL)
                circle.text_frame.text = str(index + 1)
                circle.text_frame.paragraphs[0].font.size = Pt(16); circle.text_frame.paragraphs[0].font.bold = True
                circle.text_frame.paragraphs[0].font.color.rgb = surface; circle.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
                if index < count - 1:
                    rect(slide, x + 0.7, 2.39, width - 0.78, 0.04, muted)
                box(slide, x, 3.0, width - 0.2, 3.4, bullet, 15 if count > 4 else 17, ink)
        elif layout == "cards":
            columns = 3 if len(bullets) > 4 else 2
            rows = (len(bullets) + columns - 1) // columns
            width, height = (11.7 - (columns - 1) * 0.3) / columns, min(2.3, (4.9 - (rows - 1) * 0.3) / rows)
            for index, bullet in enumerate(bullets):
                x = 0.8 + (index % columns) * (width + 0.3)
                y = 1.85 + (index // columns) * (height + 0.3)
                # a card has the deck's main colour and the cover's text colour (their contrast was checked)
                rect(slide, x, y, width, height, background)
                rect(slide, x, y, 0.08, height, accent)
                box(slide, x + 0.3, y + 0.2, width - 0.5, height - 0.3, bullet, 16, cover_ink)
        else:  # bullets
            top = 1.95
            row = min(1.12, 4.7 / len(bullets))
            for bullet in bullets:
                rect(slide, 0.9, top + 0.12, 0.14, 0.14, accent, MSO_SHAPE.OVAL)
                box(slide, 1.28, top, 10.9, row, bullet, 18, ink)
                top += row
        rect(slide, 0.8, 6.88, 11.75, 0.012, muted)
        box(slide, 0.82, 7.0, 10.4, 0.25, title, 9, muted)
        box(slide, 11.55, 6.98, 0.8, 0.28, f"{number:02d}", 10, muted, True, align=PP_ALIGN.RIGHT)

    prs.save(destination)
    return destination
