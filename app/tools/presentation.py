from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

FONTS = ("Aptos", "Segoe UI", "Calibri", "Cambria", "Georgia", "Arial", "Trebuchet MS", "Verdana", "Bahnschrift",
         "Candara", "Corbel", "Constantia", "Century Gothic", "Franklin Gothic Medium", "Garamond", "Palatino Linotype",
         "Tahoma", "Times New Roman", "Consolas", "Segoe UI Semibold", "Book Antiqua")
LAYOUTS = ("bullets", "two_columns", "quote", "big_number", "steps", "cards", "section")
COVERS = ("band", "split", "center", "minimal")
IMAGE_LAYOUTS = ("bullets", "quote", "big_number", "section")
SOURCES_TITLE = {"ru": "Источники", "en": "Sources", "zh": "资料来源", "es": "Fuentes"}
INTRO_TITLE = {"ru": "Введение", "en": "Introduction", "zh": "简介", "es": "Introducción"}

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
TOPIC_PRESETS = [
    (r"природ|эколог|лес|растен|сад|климат|\bnatur|\becolog|\bforest|\bplants?\b|\bgarden|\bclimat|\bclima\b|\bbosque|\bplantas?\b|\bjard[ií]n|自然|生态|森林|植物|花园|气候", "forest"),
    (r"мор|океан|вода|путешеств|отпуск|\bseas?\b|\bocean|\bwater\b|\btravel|\bvacation|\bmar\b|\bmares\b|\boc[eé]ano|\bagua\b|\bviaj|\bvacaciones|海|旅行|旅游|度假", "ocean"),
    (r"истори|литератур|искусств|культур|философ|книг|поэт|\bhistor|\bliterat|\barts?\b|\bcultur|\bphilosoph|\bfilosof|\bbooks?\b|\bpoe|\bliteratura|\barte\b|\blibros?\b|历史|文学|艺术|文化|哲学|诗", "paper"),
    (r"технолог|программ|код|ии\b|нейросет|компьютер|кибер|\btechnolog|\btecnolog|\bprogramm|\bprogramaci|\bcode\b|\bcoding\b|\bc[oó]digo|\bai\b|\bia\b|\bneural|\bcomputer|\bcomputador|\bcyber|\bciber|科技|技术|编程|代码|人工智能|计算机|网络安全", "neon"),
    (r"бизнес|финанс|продаж|маркет|стартап|инвест|\bbusiness|\bfinanc|\bfinanz|\bsales\b|\bmarket|\bmercado|\bstartup|\binvest|\binversi|\bnegocio|\bventas\b|商业|金融|销售|营销|创业|投资", "slate"),
    (r"медицин|здоров|спорт|питани|\bmedic|\bhealth|\bsport|\bnutrition|\bmedicin|\bsalud\b|\bdeportes?\b|\bnutrici|医学|医疗|健康|运动|营养", "mint"),
    (r"космос|астроном|физик|наук|\bspace\b|\bastronom|\bphysics|\bscience|\bespacio\b|\bf[ií]sica|\bciencia|\bmars\b|\bmarte\b|太空|宇宙|天文|物理|科学|火星", "royal"),
    (r"еда|кухн|рецепт|кофе|\bfood|\bcuisine|\bcook|\brecipes?\b|\bcoffee|\bcomida|\bcocina|\brecetas?\b|\bcaf[eé]\b|美食|烹饪|食谱|咖啡", "sand"),
    (r"дет|школ|учёб|урок|\bchild|\bkids?\b|\bschool|\bstudy|\blessons?\b|\bni[ñn]os?\b|\bescuela|\bestudi|\blecciones\b|儿童|学校|学习|课程", "sky"),
]
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
CJK_FONT = "Microsoft YaHei"


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
        bullets = next((slide[key] for key in ("bullets", "points", "items", "content", "text") if slide.get(key)), [])
        if isinstance(bullets, str):
            bullets = [line.strip(" -•*\t") for line in bullets.splitlines()]
        bullets = [_clean_text(item, 260) for item in bullets if _clean_text(item)] if isinstance(bullets, list) else []
        if layout in ("bullets", "two_columns", "steps", "cards") and not bullets:
            layout = "quote" if slide.get("quote") else "big_number" if slide.get("number") else "section"
        normalized.append({"title": _clean_text(slide.get("title"), 100), "bullets": bullets[:8], "layout": layout,
                           "number": _clean_text(slide.get("number"), 12), "caption": _clean_text(slide.get("caption"), 160),
                           "quote": _clean_text(slide.get("quote"), 300), "author": _clean_text(slide.get("author"), 80),
                           "notes": _clean_text(slide.get("notes"), 1500), "image": slide.get("image")})
    return normalized


def _without_second_cover(slides, title, language):
    """Models often open with a slide that repeats the cover: an empty one goes, one with content gets its own heading."""
    same = lambda value: re.sub(r"\W+", "", value).lower() == re.sub(r"\W+", "", title).lower()
    kept = [item for item in slides if not (same(item["title"]) and not item["bullets"] and not item["quote"] and not item["number"])]
    for item in kept:
        if same(item["title"]):
            item["title"] = INTRO_TITLE.get(language, INTRO_TITLE["en"])
    return kept


def fit_bullets(bullets, width, height):
    """Picks the largest font at which the points fit the box; returns the size and each point's height in inches."""
    for size in range(20, 11, -1):
        per_line = width * 72 / (size * 0.58)
        rows = [(len(bullet) * (2 if CJK.search(bullet) else 1) // int(per_line) + 1) * size * 1.25 / 72 + 0.14 for bullet in bullets]
        if sum(rows) <= height:
            break
    return size, rows


def create_presentation(title, slides, output_root=None, design=None, cover_image=None, articles=None, language="ru"):
    try:
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import PP_ALIGN
        from pptx.oxml.ns import qn
        from pptx.oxml.xmlchemy import OxmlElement
        from pptx.util import Inches, Pt
    except ImportError as error:
        raise RuntimeError("Для создания PPTX нужен пакет python-pptx в окружении приложения.") from error

    title = _clean_text(title, 120)
    if not isinstance(slides, list) or not 1 <= len(slides) <= 20:
        raise ValueError("Презентация должна содержать от 1 до 20 содержательных слайдов.")
    normalized = _without_second_cover(_normalize(slides), title, language)
    if not normalized:
        raise ValueError("Презентация должна содержать от 1 до 20 содержательных слайдов.")
    look = choose_design(design, title, slides)

    root = Path(output_root or (Path.home() / "Documents" / "PIVEN" / "Презентации")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = root / f"{stamp}_{_slug(title)}.pptx"
    suffix = 2
    while destination.exists():
        destination = root / f"{stamp}_{_slug(title)}_{suffix}.pptx"
        suffix += 1

    rgb = lambda value: RGBColor.from_string(value.lstrip("#"))
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
        run = paragraph.add_run()
        run.text = text
        run.font.name = font or look["body_font"]
        run.font.size, run.font.bold, run.font.italic = Pt(size), bold, italic
        run.font.color.rgb = color
        if CJK.search(text):
            east_asian = OxmlElement("a:ea")
            east_asian.set("typeface", CJK_FONT)
            run.font._element.find(qn("a:latin")).addnext(east_asian)
        if align:
            paragraph.alignment = align
        return shape

    def rect(slide, x, y, w, h, color, shape=None):
        item = slide.shapes.add_shape(shape or MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        item.fill.solid(); item.fill.fore_color.rgb = color; item.line.fill.background()
        return item

    def fill(slide, color):
        slide.background.fill.solid(); slide.background.fill.fore_color.rgb = color

    def picture(slide, image, x, y, w, h):
        item = slide.shapes.add_picture(io.BytesIO(image["data"]), Inches(x), Inches(y), Inches(w), Inches(h))
        width, height = image["size"]
        excess = 1 - (w / h) / (width / height)
        if excess > 0:
            item.crop_left = item.crop_right = excess / 2
        elif excess < 0:
            excess = 1 - (width / height) / (w / h)
            item.crop_top = item.crop_bottom = excess / 2
        return item

    cover = prs.slides.add_slide(blank)
    fill(cover, background)
    date = datetime.now().strftime("%d.%m.%Y")
    if cover_image:
        picture(cover, cover_image, 7.2, 0, 6.133, 7.5)
        rect(cover, 7.14, 0, 0.06, 7.5, accent)
        box(cover, 0.9, 2.0, 5.9, 3.2, title, 34, cover_ink, True, look["heading_font"])
        box(cover, 0.95, 6.2, 5.9, 0.3, date, 11, cover_soft)
        box(cover, 0.95, 6.55, 5.9, 0.5, cover_image["credit"], 8, cover_soft)
    elif look["cover"] == "split":
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
    else:
        rect(cover, 0.9, 1.05, 0.12, 5.35, accent)
        box(cover, 1.4, 2.15, 10.7, 2.2, title, 34, cover_ink, True, look["heading_font"])
        box(cover, 1.45, 6.55, 10.7, 0.35, date, 11, cover_soft)

    for number, item in enumerate(normalized, 2):
        slide = prs.slides.add_slide(blank)
        layout, bullets = item["layout"], item["bullets"]
        image = item["image"] if layout in IMAGE_LAYOUTS else None
        if item["notes"]:
            slide.notes_slide.notes_text_frame.text = item["notes"]
        if layout == "section":
            fill(slide, background)
            rect(slide, 0.9, 3.1, 0.12, 1.3, accent)
            box(slide, 1.3, 2.9, 5.6 if image else 11, 1.6, item["title"], 30 if image else 34, cover_ink, True, look["heading_font"])
            if bullets:
                box(slide, 1.32, 4.5, 5.6 if image else 10.5, 1.4, bullets[0], 16, cover_soft)
            if image:
                picture(slide, image, 7.2, 0, 6.133, 7.5)
                box(slide, 1.32, 6.75, 5.6, 0.45, image["credit"], 8, cover_soft)
            continue
        fill(slide, surface)
        rect(slide, 0, 0, 13.333, 0.1, accent)
        box(slide, 0.8, 0.6, 11.7, 0.9, item["title"], 28, ink, True, look["heading_font"])
        text_width = 6.6 if image else 10.9
        if image:
            picture(slide, image, 8.05, 1.7, 4.5, 4.6)
            box(slide, 8.05, 6.33, 4.5, 0.45, image["credit"], 8, muted)
        if layout == "quote":
            quote = item["quote"] or (bullets[0] if bullets else "")
            opening, closing = ("«", "»") if re.search(r"[А-Яа-яЁё]", quote) else ("“", "”")
            box(slide, 1.2 if not image else 0.8, 1.9, text_width, 3.4, opening + quote + closing, 24 if image else 30, ink, False, look["heading_font"], italic=True)
            if item["author"]:
                box(slide, 1.2 if not image else 0.8, 5.5, text_width, 0.5, "— " + item["author"], 16, muted)
        elif layout == "big_number":
            box(slide, 0.8, 1.8, text_width, 2.6, item["number"] or (bullets[0] if bullets else ""), 72 if image else 96, accent, True, look["heading_font"])
            box(slide, 0.85, 4.5, text_width, 1.4, item["caption"] or (bullets[1] if len(bullets) > 1 else ""), 20, ink)
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
                rect(slide, x, y, width, height, background)
                rect(slide, x, y, 0.08, height, accent)
                box(slide, x + 0.3, y + 0.2, width - 0.5, height - 0.3, bullet, 16, cover_ink)
        else:
            top = 1.75
            width = 6.3 if image else 10.9
            size, rows = fit_bullets(bullets, width, 4.95)
            for bullet, row in zip(bullets, rows):
                rect(slide, 0.9, top + 0.1, 0.14, 0.14, accent, MSO_SHAPE.OVAL)
                box(slide, 1.28, top, width, row, bullet, size, ink)
                top += row
        rect(slide, 0.8, 6.88, 11.75, 0.012, muted)
        box(slide, 0.82, 7.0, 10.4, 0.25, title, 9, muted)
        box(slide, 11.55, 6.98, 0.8, 0.28, f"{number:02d}", 10, muted, True, align=PP_ALIGN.RIGHT)

    lines = [f"{article['title']} · Wikipedia · {unquote(article['url'])}" for article in articles or []]
    for image in [cover_image, *(item["image"] for item in normalized if item["layout"] in IMAGE_LAYOUTS)]:
        if image:
            lines.append(f"{image['credit']} · {image['page']}")
    if lines:
        slide = prs.slides.add_slide(blank)
        fill(slide, surface)
        rect(slide, 0, 0, 13.333, 0.1, accent)
        box(slide, 0.8, 0.6, 11.7, 0.9, SOURCES_TITLE.get(language, SOURCES_TITLE["en"]), 28, ink, True, look["heading_font"])
        size, top = 11 if len(lines) <= 14 else 9, 1.6
        for line in lines:
            height = (len(line) // int(11.7 * 72 / (size * 0.5)) + 1) * size * 1.3 / 72 + 0.06
            box(slide, 0.8, top, 11.7, height, line, size, ink)
            top += height

    prs.save(destination)
    return destination
