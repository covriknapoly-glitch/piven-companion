import re
import unicodedata

SENTENCE_START = r"(?:^|[.!?;:,\n]\s*|\b(?:please|can you|could you|would you|then)\s+)"
PATH = r"(?:[a-z]:[\\/]|\\\\)"

MAKE = (r"\b(?:make|create|build|prepare|generate|compose|haz|hacer|crea|crear|prepara|preparar|genera|generar|componer)\b"
        r"|制作|做|创建|生成|准备|创作")
SLIDES = r"\b(?:presentations?|slides?|slideshow|powerpoint|pptx?|presentacion(?:es)?|diapositivas?)\b|演示文稿|幻灯片"
VIDEO = r"\bvideos?\b(?! games?)|\bclips?\b|视频|短片"
AUDIO = r"\b(?:audio|sounds?|music|melody|song|sonido|musica|melodia|cancion)\b|音频|音乐|歌曲|旋律|声音"
PICTURE = r"\b(?:imagen(?:es)?|foto|ilustracion|retrato|paisaje|avatar|fondo de pantalla)\b"
PICTURE_ZH = r"(?:生成|创建|制作|做).{0,40}(?:图片|图像|插画|照片|肖像|壁纸|头像)"

CHANGE = (r"\b(?:add|create|write|run|test|arregla|arreglar|corrige|corregir|implementa|implementar|actualiza|actualizar|"
          r"modifica|modificar|anade|anadir|crea|crear|escribe|escribir|ejecuta|ejecutar|elimina|eliminar)\b"
          r"|修复|修改|实现|更新|添加|创建|编写|运行|删除")
PROJECT = (r"\b(?:program|website|site|interface|module|button|error|proyecto|codigo|repositorio|aplicacion|programa|sitio|"
           r"interfaz|funcion|clase|modulo|script|errore?s?|fallo|boton)\b"
           r"|项目|代码|仓库|应用|程序|网站|界面|函数|模块|脚本|错误|按钮")

COMPUTER = (
    SENTENCE_START + r"(?:open|launch|click|double-click|press|scroll|go to|navigate to|minimi[sz]e|maximi[sz]e|run|type(?! of))\b",
    r"\b(?:abre|abra|abrir|ejecuta|inicia|lanza|haz clic|pulsa|presiona|teclea|desplaza|minimiza|maximiza)\b",
    r"打开|启动|运行|点击|单击|双击|按下|输入|滚动|转到|最小化|最大化",
    SENTENCE_START + r"(?:search|google|look up|find)\b.{0,80}\b(?:internet|web|online|google)\b",
    r"\b(?:busca|buscar)\b.{0,80}\b(?:internet|web|en linea|google)\b",
    r"(?:搜索|查找|搜一下|查一下).{0,40}(?:网上|互联网|网络|在线|谷歌)|网上(?:搜|查|找)",
    r"\b(?:read|show|find|rename|move|copy|create|edit|fix|lee|muestra|busca|renombra|mueve|copia|crea|edita|corrige)\b.{0,160}" + PATH,
    r"(?:读取|显示|查找|重命名|移动|复制|创建|修改|修复).{0,80}" + PATH,
    SENTENCE_START + r"download\b.{0,100}\b(?:file|model|program|archive|document|image|link|site)",
    r"\b(?:descarga|descargar|baja)\b.{0,100}\b(?:archivo|modelo|programa|documento|imagen|enlace|sitio)",
    r"下载.{0,50}(?:文件|模型|程序|压缩包|文档|图片|链接|网站)",
    SENTENCE_START + r"(?:create|make|write|read|show|find|rename|move|copy|save|list)\b.{0,90}\b(?:files?|folders?|documents?|director(?:y|ies)|desktop|downloads)\b",
    r"\b(?:crea|haz|escribe|lee|muestra|busca|renombra|mueve|copia|guarda)\b.{0,90}\b(?:archivos?|carpetas?|documentos?|escritorio|descargas)\b",
    r"(?:创建|新建|写|读取|显示|查找|重命名|移动|复制|保存).{0,40}(?:文件|文档|桌面|下载)",
)

WEB_RU = (r"\b(?:поищи|погугли|загугли|гугли)\b|\b(?:найди|ищи|узнай|посмотри|проверь)\b.{0,80}\b(?:интернет\w*|онлайн|в сети|гугл\w*|браузер\w*)\b"
          r"|\b(?:эту страницу|этой странице|открытую страницу)\b")
WEB_OTHER = (r"https?://|\bwww\.|\b[\w-]+\.(?:com|ru|org|net|io|ai|dev|app|gov|edu)\b"
             r"|\b(?:search|look up|find|check)\b.{0,80}\b(?:internet|web|online|google|browser)\b|\b(?:look up|google|search for)\b"
             r"|\b(?:this page|current page|esta pagina|googlea)\b"
             r"|\b(?:busca|buscar|encuentra|mira)\b.{0,80}\b(?:internet|web|en linea|google|navegador)\b"
             r"|搜索|上网|网上|百度|谷歌|查一下|这个页面|当前页面")

APP_NAMES = {
    "проводник": ("explorador", "资源管理器"),
    "браузер": ("navegador", "浏览器"),
    "блокнот": ("bloc de notas", "记事本"),
    "калькулятор": ("calculadora", "计算器"),
    "terminal": ("terminal", "simbolo del sistema", "终端", "命令提示符"),
}
WINDOW_WORDS = {
    "minimize_window": ("minimize", "minimise", "minimiza", "最小化"),
    "maximize_window": ("maximize", "maximise", "full screen", "fullscreen", "maximiza", "pantalla completa", "最大化", "全屏"),
    "restore_window": ("restore", "restaura", "还原", "恢复窗口"),
}


def clean(text):
    decomposed = unicodedata.normalize("NFKD", " ".join(str(text or "").lower().split()))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _found(pattern, text):
    return bool(re.search(pattern, clean(text)))


def asks_presentation(text):
    return _found(SLIDES, text) and _found(MAKE, text)


def asks_video(text):
    return _found(VIDEO, text) and _found(MAKE, text)


def asks_audio(text):
    return _found(AUDIO, text) and _found(MAKE, text)


def asks_image(text):
    return (_found(r"\b(?:dibuja|dibujar|dibujame|pinta|pintar)\b|^(?:请|帮我|给我)*画|绘制", text)
            or (_found(MAKE, text) and _found(PICTURE, text)) or _found(PICTURE_ZH, text))


def asks_code(text):
    return _found(CHANGE, text) and _found(PROJECT, text)


GAME_WORDS = (r"клон\w*|симулятор\w*|майнкрафт\w*|minecraft|тетрис\w*|змейк\w*|арканоид\w*|понг\w*|шахмат\w*|шашк\w*|сапер\w*|платформер\w*|шутер\w*|раннер\w*|рогалик\w*|"
              r"clones?|simulators?|tetris|snake|arkanoid|pong|chess|minesweeper|platformers?|shooters?|roguelikes?")
CODE_LANGUAGE = r"\b(?:на|in|en)\s+(?:python|питон\w*|pygame|javascript|джаваскрипт\w*|js|typescript|c\+\+|c#|java|джав\w*|golang|rust|lua|html|unity|godot)(?![\w+#])|\bpygame\b"
CODE_FILE = r"(?<![\w.-])([\w-]+\.(?:py|pyw|js|mjs|cjs|ts|tsx|jsx|html?|css|json|c|h|cpp|hpp|cs|java|go|rs|lua|gd|rb|php|sh|bat|cmd|ps1|sql|vue|kt|swift))(?![\w-])"
LIBRARY_NAMES = {"node.js", "next.js", "nuxt.js", "vue.js", "react.js", "three.js", "d3.js", "express.js", "angular.js", "p5.js", "chart.js"}
NEW_PROGRAM = (r"(?:напиши|написать|сделай|сделать|создай|создать|разработай|разработать|запрограммируй|собери|собрать|закодь|write|make|create|build|develop|code|program|escribe|haz|crea|programa|desarrolla)"
               r"\s+(?:[\w-]+\s+){0,5}?(?:игр\w*|игруш\w*|сайт\w*|страниц\w*|веб-\w+|лендинг\w*|приложени\w*|программ\w*|калькулятор\w*|таймер\w*|бот\w*|скрипт\w*|утилит\w*|" + GAME_WORDS + r"|"
               r"games?|websites?|sites?|web ?pages?|pages?|apps?|applications?|programs?|calculators?|timers?|bots?|scripts?|juegos?|sitio|aplicacion|programa|calculadora|temporizador)\b")
NOT_A_PROGRAM = r"\b(?:про|о|об|обзор\w*|отзыв\w*|about|review|sobre)\s+(?:[\w-]+\s+){0,3}?(?:игр\w*|сайт\w*|приложени\w*|программ\w*|games?|apps?|websites?|" + GAME_WORDS + r")"
TRANSLIT = str.maketrans({"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
                          "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"})
NAME_FILLER = {"напиши", "написать", "сделай", "сделать", "создай", "создать", "разработай", "запрограммируй", "собери", "простую", "простой", "простое", "мне", "пожалуйста", "небольшую", "красивую", "для", "на", "в", "и", "с",
               "браузера", "write", "make", "create", "build", "develop", "a", "an", "the", "simple", "me", "please", "small", "for", "in", "with", "and", "игру", "game"}


MAKE_VERB = r"\b(?:напиши|написать|сделай|сделать|создай|создать|разработай|разработать|запрограммируй|собери|собрать|закодь|write|make|create|build|develop|escribe|haz|crea|programa|desarrolla)\b"


def asks_edit(text):
    lowered = " ".join(str(text or "").lower().replace("ё", "е").split())
    if re.fullmatch(r"(?:да|давай|ага|ок|окей|yes|ok|okay|go)[.!]*", lowered):
        return True
    if re.search(r"\b(?:открой|открыть|прочитай|прочитать|open|read)\b", lowered) and re.search(r"\b(?:файл\w*|код\w*|игр\w*|программ\w*|file|code|game|program)\b", lowered):
        return True
    return bool(re.search(r"\b(?:добавь|добавить|измени|изменить|исправь|исправить|почини|починить|пофикси|убери|убрать|удали|удалить|сделай|сделать|улучши|улучшить|доработай|доработать|переделай|переделать|"
                          r"замени|заменить|поменяй|поменять|допиши|дописать|дополни|ускорь|замедли|увеличь|уменьши|запусти|запустить|создай|создать|сохрани|сохранить|попробуй|попробовать|продолжи|продолжай|повтори|еще раз|"
                          r"add|change|fix|remove|improve|replace|make|run|create|save|continue|retry|try again)\b", lowered))


def is_small_talk(text):
    lowered = " ".join(str(text or "").lower().replace("ё", "е").split())
    return len(lowered) <= 60 and bool(re.search(r"\b(?:привет\w*|здравствуй\w*|спасибо|благодарю|пока|как дела|как жизнь|что нового|hello|hi|hey|thanks?|thank you|bye)\b", lowered))


def code_file_names(text):
    return [name for name in re.findall(CODE_FILE, str(text or ""), flags=re.I) if name.lower() not in LIBRARY_NAMES]


COMMON_FILE_STEMS = {
    "main", "index", "app", "game", "script", "scripts", "style", "styles", "test", "tests", "utils", "util", "helper", "helpers",
    "config", "settings", "server", "client", "run", "start", "setup", "build", "readme", "requirements", "package", "package-lock",
}


def is_common_file_name(name):
    """Almost every project has a main.py or an index.html, so the name says nothing about which one is meant."""
    return str(name).lower().rsplit(".", 1)[0] in COMMON_FILE_STEMS


def asks_new_project(text):
    lowered = " ".join(str(text or "").lower().replace("ё", "е").split())
    if re.search(MAKE_VERB, lowered) and re.search(CODE_LANGUAGE, lowered) and not re.search(NOT_A_PROGRAM, lowered):
        return True
    return bool(re.search(NEW_PROGRAM, lowered) or re.search(NEW_PROGRAM, clean(text)) or re.search(r"(?:写|做|创建|开发|制作).{0,20}(?:游戏|网站|应用|程序|计算器|计时器|番茄钟)", lowered)) and not re.search(NOT_A_PROGRAM, lowered)


def project_name(text):
    words = [word for word in re.findall(r"[\w-]+", str(text or "").lower().replace("ё", "е")) if word not in NAME_FILLER and not word.isdigit()]
    name = "-".join(words[:3]).translate(TRANSLIT)
    return re.sub(r"[^a-z0-9-]+", "", name).strip("-")[:40]


def asks_only_question(text):
    lowered = " ".join(str(text or "").lower().replace("ё", "е").split())
    return (lowered.rstrip().endswith("?") or bool(re.search(r"\b(?:объясни|расскажи|что делает|как работает|почему|зачем|покажи|посмотри|explain|what does|how does|why|review|show)\b", lowered))) and not asks_new_project(text)


def asks_computer(text):
    return any(_found(pattern, text) for pattern in COMPUTER)


def needs_screenshot(text):
    return _found(r"\b(?:click|double-click|scroll|look at the screen|what'?s on the screen|what is on the screen|haz clic|pulsa en|"
                  r"desplaza|mira la pantalla|que hay en la pantalla)\b|点击|单击|滚动|看屏幕|屏幕上", text)


def asks_how_to(text):
    return _found(r"\b(?:how|explain|como|explica)\b|如何|怎么|怎样|解释", text)


def allows_download(text):
    return _found(r"\b(?:download|descarga|descargar|baja)\b|下载", text)


def asks_web(text):
    lowered = " ".join(str(text or "").lower().replace("ё", "е").split())
    return bool(re.search(WEB_RU, lowered)) or _found(WEB_OTHER, text)


def allows_web_search(text):
    return _found(r"\b(?:search|find|look up|google|busca|buscar|encuentra)\b|搜索|查找|搜一下|查一下", text)


def names_web(text):
    return _found(r"\b(?:internet|web|online|en linea)\b|网上|互联网|网络|在线", text)


def allows_typing(text):
    return _found(r"\b(?:enter|teclea|escribe|busca|ingresa)\b|输入|键入|搜索", text)


def allows_closing(text):
    return _found(r"\b(?:close|quit|exit|cierra|cerrar|salir)\b|关闭|退出", text)


def allows_file_change(text):
    return _found(r"\b(?:create|make|write|save|rename|move|copy|crea|crear|haz|hacer|escribe|escribir|guarda|guardar|"
                  r"renombra|renombrar|mueve|mover|copia|copiar)\b|创建|新建|写|保存|重命名|移动|复制|制作", text)


def app_words(key):
    return APP_NAMES.get(key, ())


def allows_window(action, text):
    cleaned = clean(text)
    return any(word in cleaned for word in WINDOW_WORDS[action])
