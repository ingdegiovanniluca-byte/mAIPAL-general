import React, { useCallback, useId, useRef, useState } from "react";

const H = 64;      // height of the bar and diameter of the round button
const GAP = 12;    // space between the bar and the round button
const R = H / 2;

/* Outline of a liquid-glass pair: a circle and a block (a pill, or a taller card with
   corners of the same radius) joined by a neck, like two drops of glass merging.
   `blockH` is the block's height (>= H); the circle sits level with its last row.
   Every piece is drawn clockwise, so with the default nonzero fill they add up to a
   single shape. Mirrored with `circleLeft`; with `circleTop` the circle sits level with the
   block's FIRST row instead (the chat composer: voice button up top, a taller text block). */
export function liquidPath(W, blockH = H, circleLeft = false, circleTop = false) {
  if (circleTop) return flipY(liquidPath(W, blockH, circleLeft), Math.max(H, blockH));
  const bh = Math.max(H, blockH);
  const cy = bh - R;                                   // circle's (and neck's) centre line
  const a = (50 * Math.PI) / 180;                      // where the neck leaves each round end
  const dx = R * Math.cos(a), dy = R * Math.sin(a);
  const k = 21;                                        // how far the neck's curves pull inwards
  const tx = Math.sin(a) * k, ty = Math.cos(a) * k;
  const f = (x, y) => `${x.toFixed(2)},${y.toFixed(2)}`;
  // the block from b0 to b1, the circle centred on cc; computed for the circle on the
  // right and mirrored afterwards
  const b0 = 0, b1 = W - H - GAP, cc = W - R;
  const block = `M${b0 + R},0 H${b1 - R} A${R},${R} 0 0 1 ${b1},${R} V${bh - R} A${R},${R} 0 0 1 ${b1 - R},${bh} `
    + `H${b0 + R} A${R},${R} 0 0 1 ${b0},${bh - R} V${R} A${R},${R} 0 0 1 ${b0 + R},0 Z`;
  const circle = [[cc - R, cy, "M"], [cc + R, cy, "A"], [cc - R, cy, "A"]];
  // neck: from the block's right end to the circle; on a taller card its top edge meets the
  // card's straight side, so it ends there with a vertical tangent instead of on an arc
  const A = bh > H ? [b1, cy - 22] : [b1 - R + dx, cy - dy];
  const C1 = bh > H ? [b1, cy - 8] : [A[0] + tx, A[1] + ty];
  const B = [cc - dx, cy - dy];
  const C2 = [B[0] - tx, B[1] + ty];
  const Ab = [b1 - R + dx, cy + dy], C1b = [Ab[0] + tx, Ab[1] - ty];
  const Bb = [B[0], cy + dy], C2b = [C2[0], 2 * cy - C2[1]];
  const mx = (x) => (circleLeft ? W - x : x);
  // mirroring flips the drawing direction of every piece alike, so the union still holds
  const P = (p) => f(mx(p[0]), p[1]);
  const sweep = circleLeft ? 0 : 1;
  const neck = `M${P(A)} C${P(C1)} ${P(C2)} ${P(B)} L${P(Bb)} C${P(C2b)} ${P(C1b)} ${P(Ab)} Z`;
  const circ = `M${f(mx(circle[0][0]), cy)} A${R},${R} 0 1 ${sweep} ${f(mx(circle[1][0]), cy)} A${R},${R} 0 1 ${sweep} ${f(mx(circle[2][0]), cy)} Z`;
  if (!circleLeft) return `${block} ${circ} ${neck}`;
  const m = (x) => (W - x).toFixed(2);
  const blockMirrored = `M${m(b0 + R)},0 H${m(b1 - R)} A${R},${R} 0 0 0 ${m(b1)},${R} V${bh - R} A${R},${R} 0 0 0 ${m(b1 - R)},${bh} `
    + `H${m(b0 + R)} A${R},${R} 0 0 0 ${m(b0)},${bh - R} V${R} A${R},${R} 0 0 0 ${m(b0 + R)},0 Z`;
  return `${blockMirrored} ${circ} ${neck}`;
}

/* Upside-down copy of a path made of M/L/H/V/C/A/Z commands: y -> height - y, and every
   arc's sweep flag flipped. Every piece turns the other way alike, so a union stays one. */
function flipY(d, height) {
  const tokens = d.match(/[MLHVCAZ]|-?\d*\.?\d+/g) || [];
  const arity = { M: 2, L: 2, H: 1, V: 1, C: 6, A: 7, Z: 0 };
  const out = [];
  let cmd = null, i = 0;
  for (const t of tokens) {
    if (/[A-Z]/.test(t)) { cmd = t; i = 0; out.push(t); continue; }
    const n = arity[cmd], j = i % n;
    let v = parseFloat(t);
    if (cmd === "V" || ((cmd === "M" || cmd === "L" || cmd === "C") && j % 2 === 1) || (cmd === "A" && j === 6)) v = height - v;
    else if (cmd === "A" && j === 4) v = v ? 0 : 1;
    out.push(cmd === "A" && j >= 2 && j <= 4 ? String(v) : v.toFixed(2));
    i += 1;
  }
  return out.join(" ");
}

/* The glass itself, cut to `d`: a soft shadow and the blurred frosted layer (no rim). A single element, so the blur flows through the neck without a seam (a CSS
   filter on it would turn the backdrop blur off - hence the shadow in its own SVG). */
export function LiquidGlass({ d, width, height }) {
  const uid = useId().replace(/:/g, "");
  if (!d || !width) return null;
  return (
    <>
      <svg aria-hidden="true" width={width} height={height} viewBox={`0 0 ${width} ${height}`}
           className="absolute left-0 top-0 overflow-visible pointer-events-none">
        <defs>
          <filter id={`ls-${uid}`} x="-20%" y="-60%" width="140%" height="240%">
            <feGaussianBlur stdDeviation="11" />
          </filter>
        </defs>
        <path d={d} transform="translate(0 10)" fill="rgba(60,10,40,0.16)" filter={`url(#ls-${uid})`} />
      </svg>
      <div aria-hidden="true" className="lg-goo absolute left-0 top-0 pointer-events-none"
           style={{ width, height, clipPath: `path('${d}')`, WebkitClipPath: `path('${d}')` }} />
    </>
  );
}

/* Size of an element, kept up to date: returns a callback ref (works when the element
   mounts later, or is swapped) and its { w, h }. */
export function useMeasure() {
  const [size, setSize] = useState({ w: 0, h: 0 });
  const roRef = useRef(null);
  const ref = useCallback((el) => {
    if (roRef.current) { roRef.current.disconnect(); roRef.current = null; }
    if (!el) return;
    const measure = () => setSize((s) => (s.w === el.offsetWidth && s.h === el.offsetHeight ? s : { w: el.offsetWidth, h: el.offsetHeight }));
    measure();
    roRef.current = new ResizeObserver(measure);
    roRef.current.observe(el);
  }, []);
  return [ref, size];
}

/* Floating bottom dock in liquid glass: `bar` is the row of sections, `button` the round
   "+" joined to it. */
export default function LiquidDock({ bar, button }) {
  const [barRef, { w: pillW }] = useMeasure();
  const totalW = pillW + GAP + H;
  return (
    <div className="pointer-events-auto relative flex items-center" style={{ gap: GAP, height: H }}>
      {pillW > 0 && <LiquidGlass d={liquidPath(totalW)} width={totalW} height={H} />}
      <div ref={barRef} className="relative">{bar}</div>
      <div className="relative">{button}</div>
    </div>
  );
}

export const LIQUID_H = H;
export const LIQUID_GAP = GAP;
