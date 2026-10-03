import React, { useLayoutEffect, useRef, useState } from "react";

const H = 64;      // height of the bar and diameter of the round button
const GAP = 12;    // space between the bar's end and the round button
const R = H / 2;

/* Outline of the dock: a pill (the sections), a circle (the "+") and the liquid neck that
   joins them, like two drops of glass merging. All three are drawn clockwise, so with the
   default nonzero fill they add up to a single shape. */
function dockPath(pillW) {
  const cx1 = pillW - R;               // centre of the pill's right end
  const cx2 = pillW + GAP + R;         // centre of the circle
  const a = (50 * Math.PI) / 180;      // where the neck leaves each round end
  const dx = R * Math.cos(a), dy = R * Math.sin(a);
  const k = 21;                        // how far the neck's curves pull inwards
  const tx = Math.sin(a) * k, ty = Math.cos(a) * k;
  const A = [cx1 + dx, R - dy], B = [cx2 - dx, R - dy];
  const f = (p) => `${p[0].toFixed(2)},${p[1].toFixed(2)}`;
  const flip = (p) => [p[0], H - p[1]];
  const C1 = [A[0] + tx, A[1] + ty], C2 = [B[0] - tx, B[1] + ty];
  const pill = `M${R},0 H${pillW - R} A${R},${R} 0 0 1 ${pillW - R},${H} H${R} A${R},${R} 0 0 1 ${R},0 Z`;
  const circle = `M${cx2 - R},${R} A${R},${R} 0 1 1 ${cx2 + R},${R} A${R},${R} 0 1 1 ${cx2 - R},${R} Z`;
  const neck = `M${f(A)} C${f(C1)} ${f(C2)} ${f(B)} L${f(flip(B))} C${f(flip(C2))} ${f(flip(C1))} ${f(flip(A))} Z`;
  return `${pill} ${circle} ${neck}`;
}

/* Floating bottom dock in liquid glass: `bar` is the row of sections, `button` the round
   "+" joined to it. The glass is a single element cut to the merged outline, so the blur
   flows through the neck without a seam. */
export default function LiquidDock({ bar, button }) {
  const barRef = useRef(null);
  const [pillW, setPillW] = useState(0);

  useLayoutEffect(() => {
    const el = barRef.current;
    if (!el) return undefined;
    const measure = () => setPillW(el.offsetWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const d = pillW ? dockPath(pillW) : null;
  const totalW = pillW + GAP + H;

  return (
    <div className="pointer-events-auto relative flex items-center" style={{ gap: GAP, height: H }}>
      {d && (
        <>
          {/* soft shadow under the whole shape (a filter on the glass itself would turn its blur off) */}
          <svg aria-hidden="true" width={totalW} height={H} viewBox={`0 0 ${totalW} ${H}`}
               className="absolute left-0 top-0 overflow-visible pointer-events-none">
            <defs>
              <filter id="dock-shadow" x="-20%" y="-60%" width="140%" height="240%">
                <feGaussianBlur stdDeviation="11" />
              </filter>
            </defs>
            <path d={d} transform="translate(0 10)" fill="rgba(40,10,50,0.24)" filter="url(#dock-shadow)" />
          </svg>
          <div aria-hidden="true" className="lg-goo absolute left-0 top-0 pointer-events-none"
               style={{ width: totalW, height: H, clipPath: `path('${d}')`, WebkitClipPath: `path('${d}')` }} />
          {/* light falling on the top of the glass */}
          <svg aria-hidden="true" width={totalW} height={H} viewBox={`0 0 ${totalW} ${H}`}
               className="absolute left-0 top-0 pointer-events-none">
            <defs>
              <linearGradient id="dock-sheen" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#fff" stopOpacity="0.22" />
                <stop offset="0.45" stopColor="#fff" stopOpacity="0.04" />
                <stop offset="1" stopColor="#fff" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d={d} fill="url(#dock-sheen)" />
          </svg>
        </>
      )}
      <div ref={barRef} className="relative">{bar}</div>
      <div className="relative">{button}</div>
    </div>
  );
}
