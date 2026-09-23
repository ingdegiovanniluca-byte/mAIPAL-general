import { useEffect, useState } from "react";

// Matches Tailwind's own `md` breakpoint (768px) and the mobile-adaptation spec's own
// threshold, so JS-driven layout decisions (pixel math CSS media queries can't express)
// stay in lockstep with the CSS `md:` classes used everywhere else.
const MOBILE_BREAKPOINT = 768;

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
