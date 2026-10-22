"""Create polished PowerPoint decks from structured slide content."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path


def _clean_text(value, limit=500):
    text = " ".join(str(value or "").split())
    if not text:
        raise ValueError("В презентации встретился пустой текст.")
    return text[:limit]


def _slug(value):
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", normalized).strip("-").lower()
    return (slug[:48] or "presentation")


def create_presentation(title, slides, output_root=None):
    """Save a 16:9 presentation in Documents without overwriting an existing file."""
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
    normalized = []
    for index, slide in enumerate(slides, 1):
        if not isinstance(slide, dict):
            raise ValueError(f"Слайд {index} должен быть объектом с заголовком и тезисами.")
        heading = _clean_text(slide.get("title"), 100)
        bullets = slide.get("bullets", [])
        if not isinstance(bullets, list) or not 1 <= len(bullets) <= 6:
            raise ValueError(f"На слайде {index} нужно от 1 до 6 тезисов.")
        normalized.append((heading, [_clean_text(item, 260) for item in bullets]))

    root = Path(output_root or (Path.home() / "Documents" / "PIVEN" / "Презентации")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = root / f"{stamp}_{_slug(title)}.pptx"
    suffix = 2
    while destination.exists():
        destination = root / f"{stamp}_{_slug(title)}_{suffix}.pptx"
        suffix += 1

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    navy = RGBColor(18, 29, 44)
    teal = RGBColor(36, 145, 139)
    ink = RGBColor(35, 45, 56)
    muted = RGBColor(105, 117, 128)
    paper = RGBColor(248, 247, 243)
    white = RGBColor(255, 255, 255)
    font_name = "Aptos"

    def text_box(slide, x, y, w, h, text, size, color, bold=False):
        shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = shape.text_frame
        frame.clear()
        frame.word_wrap = True
        frame.margin_left = Inches(0.02)
        frame.margin_right = Inches(0.02)
        frame.margin_top = Inches(0.02)
        frame.margin_bottom = Inches(0.02)
        paragraph = frame.paragraphs[0]
        paragraph.text = text
        paragraph.font.name = font_name
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = color
        return shape

    cover = prs.slides.add_slide(blank)
    cover.background.fill.solid()
    cover.background.fill.fore_color.rgb = navy
    accent = cover.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.9), Inches(1.05), Inches(0.12), Inches(5.35))
    accent.fill.solid(); accent.fill.fore_color.rgb = teal; accent.line.fill.background()
    text_box(cover, 1.4, 2.15, 10.7, 2.2, title, 34, white, True)
    text_box(cover, 1.45, 4.55, 9.5, 0.7, "ПРЕЗЕНТАЦИЯ · PIVEN", 14, RGBColor(169, 190, 203), True)
    text_box(cover, 1.45, 6.55, 10.7, 0.35, datetime.now().strftime("%d.%m.%Y"), 11, RGBColor(169, 190, 203))

    for number, (heading, bullets) in enumerate(normalized, 1):
        slide = prs.slides.add_slide(blank)
        slide.background.fill.solid(); slide.background.fill.fore_color.rgb = paper
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.13))
        bar.fill.solid(); bar.fill.fore_color.rgb = teal; bar.line.fill.background()
        text_box(slide, 0.8, 0.65, 11.7, 0.8, heading, 26, ink, True)
        rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.82), Inches(1.58), Inches(0.72), Inches(0.055))
        rule.fill.solid(); rule.fill.fore_color.rgb = teal; rule.line.fill.background()
        top = 2.0
        available = 4.65
        row_height = min(1.12, available / len(bullets))
        for bullet in bullets:
            dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.9), Inches(top + 0.12), Inches(0.14), Inches(0.14))
            dot.fill.solid(); dot.fill.fore_color.rgb = teal; dot.line.fill.background()
            text_box(slide, 1.28, top, 10.9, row_height, bullet, 18, ink)
            top += row_height
        footer = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(6.88), Inches(11.75), Inches(0.012))
        footer.fill.solid(); footer.fill.fore_color.rgb = RGBColor(218, 220, 218); footer.line.fill.background()
        text_box(slide, 0.82, 7.0, 10.4, 0.25, title, 9, muted)
        number_box = text_box(slide, 11.55, 6.98, 0.8, 0.28, f"{number + 1:02d}", 10, muted, True)
        number_box.text_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT

    prs.save(destination)
    return destination
