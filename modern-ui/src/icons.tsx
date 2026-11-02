import type { HTMLAttributes } from "react";

// Icons are glyphs of Symbols Nerd Font (subset in assets/fonts/SymbolsNerdFont-Icons.ttf):
// Codicons (CC BY 4.0), Material Design Icons (Apache 2.0) and Font Awesome (CC BY 4.0), see docs/THIRD_PARTY_NOTICES.md.
// To add one, add its glyph name to modern-ui/scripts/subset_icons.py and run it again.
const glyphs = {
  call: "\u{f03f2}", // md-phone
  alert: "\u{ea6c}", // cod-warning
  arrowDown: "\u{ea9a}", // cod-arrow_down
  arrowRight: "\u{ea9c}", // cod-arrow_right
  arrowUp: "\u{eaa1}", // cod-arrow_up
  check: "\u{eab2}", // cod-check
  chevronDown: "\u{eab4}", // cod-chevron_down
  chevronRight: "\u{eab6}", // cod-chevron_right
  close: "\u{ea76}", // cod-close
  download: "\u{eac2}", // cod-cloud_download
  external: "\u{eb14}", // cod-link_external
  fit: "\u{eb4c}", // cod-screen_full
  paperclip: "\u{ec34}", // cod-attach
  pause: "\u{ead1}", // cod-debug_pause
  play: "\u{eb2c}", // cod-play
  presentation: "\u{f0428}", // md-presentation
  retry: "\u{ebc0}", // cod-debug_rerun
  send: "\u{ec0f}", // cod-send
  spark: "\u{ec10}", // cod-sparkle
  stop: "\u{ead7}", // cod-debug_stop
  twitch: "\u{f1e8}", // fa-twitch
  user: "\u{eb99}", // cod-account
  zoomIn: "\u{eb81}", // cod-zoom_in
  zoomOut: "\u{eb82}", // cod-zoom_out
  plus: "\u{ea60}", // cod-add
  moon: "\u{f0594}", // md-weather_night
  sun: "\u{f0599}", // md-weather_sunny
  chat: "\u{ea6b}", // cod-comment
  code: "\u{eac4}", // cod-code
  copy: "\u{ebcc}", // cod-copy
  trash: "\u{ea81}", // cod-trash
  box: "\u{eb29}", // cod-package
  monitor: "\u{ea7a}", // cod-vm
  file: "\u{ea7b}", // cod-file
  edit: "\u{ea73}", // cod-edit
  compose: "\u{ec0e}", // cod-comment_draft
  extension: "\u{eae6}", // cod-extensions
  folder: "\u{ea83}", // cod-folder
  headphones: "\u{f02cb}", // md-headphones
  image: "\u{eaea}", // cod-file_media
  share: "\u{ebac}", // cod-export
  pin: "\u{eb2b}", // cod-pin
  sidebar: "\u{ebf3}", // cod-layout_sidebar_left
  sidebarOpen: "\u{ec02}", // cod-layout_sidebar_left_off
  workspace: "\u{ebf4}", // cod-layout_sidebar_right
  workspaceOff: "\u{ec00}", // cod-layout_sidebar_right_off
  menu: "\u{eb94}", // cod-menu
  mic: "\u{ec12}", // cod-mic
  more: "\u{ea7c}", // cod-ellipsis
  refresh: "\u{eb37}", // cod-refresh
  search: "\u{ea6d}", // cod-search
  settings: "\u{eb51}", // cod-settings_gear
  volume: "\u{eb75}", // cod-unmute
  palette: "\u{eb5c}", // cod-symbol_color
  globe: "\u{eb01}", // cod-globe
  tools: "\u{eb6d}", // cod-tools
  database: "\u{eace}", // cod-database
  plug: "\u{eb2d}", // cod-plug
  keyboard: "\u{ec3c}", // cod-keyboard_tab
} as const;

export type IconName = keyof typeof glyphs;

type IconProps = HTMLAttributes<HTMLElement> & { name: IconName; size?: number };

export function Icon({ name, size = 18, className = "", style, ...props }: IconProps) {
  return <i aria-hidden="true" className={`ico ${className}`} style={{ fontSize: size, ...style }} {...props}>{glyphs[name]}</i>;
}
