"""Cut the icons the interface uses out of Symbols Nerd Font and print the name -> code point table for src/icons.tsx.

Needs fontTools. Usage (font from github.com/ryanoasis/nerd-fonts, NerdFontsSymbolsOnly.zip):
    python subset_icons.py SymbolsNerdFont-Regular.ttf ../src/assets/fonts/SymbolsNerdFont-Icons.ttf
"""
import sys
from fontTools.ttLib import TTFont
from fontTools import subset

source, target = sys.argv[1], sys.argv[2]
ICONS = {
    "call": "md-phone", "alert": "cod-warning", "arrowDown": "cod-arrow_down", "arrowRight": "cod-arrow_right",
    "arrowUp": "cod-arrow_up", "check": "cod-check", "chevronDown": "cod-chevron_down", "chevronRight": "cod-chevron_right",
    "close": "cod-close", "download": "cod-cloud_download", "external": "cod-link_external", "fit": "cod-screen_full",
    "paperclip": "cod-attach", "pause": "cod-debug_pause", "play": "cod-play", "presentation": "md-presentation",
    "retry": "cod-debug_rerun", "send": "cod-send", "spark": "cod-sparkle", "stop": "cod-debug_stop",
    "twitch": "fa-twitch", "user": "cod-account", "zoomIn": "cod-zoom_in", "zoomOut": "cod-zoom_out",
    "plus": "cod-add", "moon": "md-weather_night", "sun": "md-weather_sunny", "chat": "cod-comment",
    "code": "cod-code", "copy": "cod-copy", "trash": "cod-trash", "box": "cod-package", "monitor": "cod-vm",
    "file": "cod-file", "edit": "cod-edit", "compose": "cod-comment_draft", "extension": "cod-extensions",
    "folder": "cod-folder", "headphones": "md-headphones", "image": "cod-file_media", "share": "cod-export",
    "pin": "cod-pin", "sidebar": "cod-layout_sidebar_left", "sidebarOpen": "cod-layout_sidebar_left_off",
    "workspace": "cod-layout_sidebar_right", "workspaceOff": "cod-layout_sidebar_right_off",
    "menu": "cod-menu", "mic": "cod-mic", "more": "cod-ellipsis", "refresh": "cod-refresh", "search": "cod-search",
    "settings": "cod-settings_gear", "volume": "cod-unmute", "palette": "cod-symbol_color", "globe": "cod-globe",
    "tools": "cod-tools", "database": "cod-database", "plug": "cod-plug", "keyboard": "cod-keyboard_tab",
}
font = TTFont(source)
by_name = {name: code for code, name in font.getBestCmap().items()}
missing = [glyph for glyph in ICONS.values() if glyph not in by_name]
if missing:
    sys.exit(f"missing: {missing}")
codes = {icon: by_name[glyph] for icon, glyph in ICONS.items()}
options = subset.Options()
options.layout_features = []
options.name_IDs = ["*"]
options.notdef_outline = True
sub = subset.Subsetter(options)
sub.populate(unicodes=sorted(set(codes.values())))
sub.subset(font)
font.save(target)
for icon, code in codes.items():
    print(f'  {icon}: "\\u{{{code:x}}}", // {ICONS[icon]}')
