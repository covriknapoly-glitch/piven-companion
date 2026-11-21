import { useEffect, useLayoutEffect, useRef, useState } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

export function CodeModeActivation({ enabled }: { enabled: boolean }) {
  const previous = useRef(enabled);
  const [animating, setAnimating] = useState(false);

  useLayoutEffect(() => {
    if (enabled === previous.current) return;
    previous.current = enabled;
    setAnimating(enabled && !window.matchMedia(REDUCED_MOTION).matches);
  }, [enabled]);

  useEffect(() => {
    if (!animating) return;
    const motion = window.matchMedia(REDUCED_MOTION);
    const cancel = () => setAnimating(false);
    motion.addEventListener("change", cancel);
    return () => motion.removeEventListener("change", cancel);
  }, [animating]);

  if (!enabled || !animating) return null;
  return <i className="code-mode-activation" aria-hidden="true" onAnimationEnd={() => setAnimating(false)} />;
}
