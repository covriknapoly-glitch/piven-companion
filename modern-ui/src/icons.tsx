import type { SVGProps } from "react";

const paths = {
  arrowDown: ["M12 4v15", "m6 13 6 6 6-6"],
  arrowRight: ["M4 12h15", "m13 6 6 6-6 6"],
  arrowUp: ["M12 20V5", "m6 11 6-6 6 6"],
  check: ["m5 12.5 4.5 4.5L19 7.5"],
  chevronDown: ["m6 9 6 6 6-6"],
  close: ["m6 6 12 12", "M18 6 6 18"],
  code: ["m8 7-5 5 5 5", "m16 7 5 5-5 5"],
  copy: ["M9 9h11v11H9z", "M5 15H4V4h11v1"],
  edit: ["M4 20h4L19 9l-4-4L4 16v4Z", "m13.5 6.5 4 4"],
  file: ["M6 3h8l4 4v14H6z", "M14 3v4h4"],
  fit: ["M4 9V4h5", "M20 9V4h-5", "M4 15v5h5", "M20 15v5h-5"],
  grip: ["M9 6h.01", "M15 6h.01", "M9 12h.01", "M15 12h.01", "M9 18h.01", "M15 18h.01"],
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M4 21a8 8 0 0 1 16 0"],
  image: ["M4 5h16v14H4z", "m4 16 5-5 4 4 2-2 5 5", "M15.5 9.5h.01"],
  menu: ["M4 6h16", "M4 12h16", "M4 18h16"],
  monitor: ["M3 4h18v12H3z", "M8 20h8", "M12 16v4"],
  moon: ["M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z"],
  more: ["M5 12h.01", "M12 12h.01", "M19 12h.01"],
  newChat: ["M12 5v14", "M5 12h14"],
  compose: ["M12 4H5v15h15v-7", "M17.5 3.5a2.1 2.1 0 0 1 3 3L13 14l-4 1 1-4 7.5-7.5Z"],
  pin: ["M9 3h6l-1 6 4 4H6l4-4-1-6Z", "M12 13v8"],
  presentation: ["M3 4h18v12H3z", "M12 16v4", "M8 20h8", "M7 12l3-3 2 2 4-4"],
  refresh: ["M20 11a8 8 0 0 0-14-5L4 8", "M4 4v4h4", "M4 13a8 8 0 0 0 14 5l2-2", "M20 20v-4h-4"],
  search: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Z", "m20 20-4-4"],
  send: ["m3 11 18-8-8 18-2-8-8-2Z", "m11 13 10-10"],
  settings: ["M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z", "m19.4 15 .1.1 1.4 1.1-1.4 2.4-1.8-.6a7.8 7.8 0 0 1-1.7 1l-.3 1.9h-2.8l-.3-1.9a7.8 7.8 0 0 1-1.7-1l-1.8.6-1.4-2.4L7.1 15a8 8 0 0 1 0-2l-1.4-1.1 1.4-2.4 1.8.6a7.8 7.8 0 0 1 1.7-1l.3-1.9h2.8l.3 1.9a7.8 7.8 0 0 1 1.7 1l1.8-.6 1.4 2.4-1.4 1.1a8 8 0 0 1-.1 2Z"],
  sidebar: ["M4 4h16v16H4z", "M9 4v16"],
  spark: ["m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z", "m19 16 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z"],
  stop: ["M7 7h10v10H7z"],
  sun: ["M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z", "M12 2v2", "M12 20v2", "m4.9 4.9 1.4 1.4", "m17.7 17.7 1.4 1.4", "M2 12h2", "M20 12h2", "m4.9 19.1 1.4-1.4", "m17.7 6.3 1.4-1.4"],
  terminal: ["M4 5h16v14H4z", "m8 10 3 2-3 2", "M13 15h3"],
  volume: ["M4 9h4l5-4v14l-5-4H4z", "M16.5 8.5a5 5 0 0 1 0 7", "M19 6a8.5 8.5 0 0 1 0 12"],
  zoomIn: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Z", "m16 16 5 5", "M11 8v6", "M8 11h6"],
  zoomOut: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14Z", "m16 16 5 5", "M8 11h6"],
} as const;

export type IconName = keyof typeof paths;

type IconProps = SVGProps<SVGSVGElement> & { name: IconName; size?: number };

export function Icon({ name, size = 18, ...props }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {paths[name].map((path) => <path key={path} d={path} />)}
    </svg>
  );
}
