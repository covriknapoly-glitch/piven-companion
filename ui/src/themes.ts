export type ThemeId = "system" | "dark" | "light" | "forest" | "coffee" | "abyss" | "gruvbox" | "everforest"
  | "kanagawa" | "tokyonight" | "nord" | "catppuccin" | "rosepine" | "onedark";

export const THEMES: readonly (readonly [ThemeId, string, boolean, readonly string[]])[] = [
  ["system", "Как в Windows", false, ["#0a0a0a", "#ffffff", "#7a7a7a", "#5c9cf5"]],
  ["dark", "Графит", false, ["#0a0a0a", "#111111", "#eeeeee", "#5c9cf5"]],
  ["light", "Светлая", true, ["#ffffff", "#f7f7f7", "#1a1a1a", "#2f6fd0"]],
  ["forest", "Тёмный лес", false, ["#0a120e", "#0e1813", "#dbe7de", "#7cc49b"]],
  ["coffee", "Кофе", false, ["#14100c", "#1b1510", "#eadfd2", "#86b8ad"]],
  ["abyss", "Глубина", false, ["#050c13", "#08121b", "#d3e2ec", "#4fb3d9"]],
  ["gruvbox", "Gruvbox", false, ["#282828", "#1d2021", "#ebdbb2", "#83a598"]],
  ["everforest", "Everforest", false, ["#2d353b", "#272e33", "#d3c6aa", "#a7c080"]],
  ["kanagawa", "Kanagawa", false, ["#1f1f28", "#16161d", "#dcd7ba", "#7e9cd8"]],
  ["tokyonight", "Tokyo Night", false, ["#1a1b26", "#16161e", "#c0caf5", "#7aa2f7"]],
  ["nord", "Nord", false, ["#2e3440", "#272c36", "#eceff4", "#88c0d0"]],
  ["catppuccin", "Catppuccin", false, ["#1e1e2e", "#181825", "#cdd6f4", "#cba6f7"]],
  ["rosepine", "Rosé Pine", false, ["#191724", "#1f1d2e", "#e0def4", "#c4a7e7"]],
  ["onedark", "One Dark", false, ["#282c34", "#21252b", "#abb2bf", "#61afef"]],
];

export const THEME_IDS = THEMES.map(([id]) => id);
export const isLightTheme = (id: ThemeId) => THEMES.find(([value]) => value === id)?.[2] ?? false;
