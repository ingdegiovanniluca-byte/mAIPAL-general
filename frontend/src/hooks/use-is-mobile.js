import { useEffect, useState } from "react";

// The app's one threshold: below it the mobile layout, from it the desktop split (chat on the
// left, the section on the right) - no layout in between. Tailwind's `md`/`lg` are set to the
// same width (tailwind.config.js), so JS-driven layout decisions (pixel math CSS media queries
// can't express) stay in lockstep with the CSS `md:` classes used everywhere else.
export const MOBILE_BREAKPOINT = 1100;

export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== "undefined" && window.innerWidth < MOBILE_BREAKPOINT
  );
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return isMobile;
}
