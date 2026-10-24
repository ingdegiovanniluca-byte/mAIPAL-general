import React, { useEffect, useRef, useState } from "react";
import { Navigation, X } from "lucide-react";

/* The commessa's site on a colour map, as a band across the diary under its figures - never
   taller than that. The map is OpenFreeMap's "Liberty" style (OpenStreetMap's data drawn like
   Google Maps: yellow main roads, light grey blocks, green parks; free, no key), flat (no 3D
   buildings), with MapLibre - it comes in its own chunk, only when a diary with a site is opened.
   The bar under it is dragged like a sheet's: up to hide the map, down to bring it back; a tap
   closes it or opens it again. One finger moves the map, two zoom it. The dot is green, with how
   many, when someone is on site now, orange otherwise: tapped, a small card says so (who, since
   when), with the address and a button to get there. */

const BAND = 90;                                   // the band's height, its largest (px)
const STYLE = "https://tiles.openfreemap.org/styles/liberty";
const ZOOM = 14.5;
const KEY = "maipal.diary.map";                     // closed | band, kept on this device
const read = () => { try { return localStorage.getItem(KEY) === "closed" ? "closed" : "band"; } catch { return "band"; } };
const keep = (v) => { try { localStorage.setItem(KEY, v); } catch { /* private mode */ } };
const heightOf = (mode) => (mode === "closed" ? 0 : BAND);

function paintPin(el, onSite) {
  const busy = onSite > 0;
  el.style.cssText = "position:relative;width:24px;height:24px";
  el.innerHTML = `${busy ? '<span class="sitemap-pulse"></span>' : ""}
    <span style="position:absolute;inset:3px;border-radius:50%;border:3px solid #fff;background:${busy ? "#2FBF71" : "#F2701E"};box-shadow:0 3px 8px rgba(30,10,25,.45)"></span>
    ${busy ? `<span style="position:absolute;right:-8px;top:-8px;min-width:17px;height:17px;padding:0 4px;border-radius:9px;background:#fff;color:#1E7D4B;font:700 10.5px/17px sans-serif;text-align:center;box-shadow:0 2px 5px rgba(0,0,0,.25)">${onSite}</span>` : ""}`;
}

const hhmm = (iso) => { try { return new Date(iso).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };

export default function SiteMapBand({ geo, onSite: people = [], address = "", className = "" }) {
  const onSite = people.length;
  const [info, setInfo] = useState(false);
  const box = useRef(null);
  const map = useRef(null);
  const pin = useRef(null);
  const [mode, setMode] = useState(read);
  const [h, setH] = useState(() => heightOf(read()));
  const [dragging, setDragging] = useState(false);
  const drag = useRef(null);
  const lat = geo?.lat, lon = geo?.lon;

  // the map, once, when the band first has room (it keeps its size: the band only uncovers it)
  useEffect(() => {
    if (lat == null || map.current || h === 0) return undefined;
    let gone = false;
    (async () => {
      const maplibregl = (await import("maplibre-gl")).default;
      await import("maplibre-gl/dist/maplibre-gl.css");
      if (gone || !box.current || map.current) return;
      const m = new maplibregl.Map({
        container: box.current, style: STYLE, center: [lon, lat], zoom: ZOOM,
        attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false, touchPitch: false,
        scrollZoom: false, dragPan: true, cooperativeGestures: false,
      });
      m.touchZoomRotate.disableRotation();
      // flat and clean, like Google's at this size: no 3D buildings, no bus stops and shop icons
      m.on("style.load", () => {
        for (const l of m.getStyle().layers || []) {
          if (l.type === "fill-extrusion") m.removeLayer(l.id);
          else if (l.id.startsWith("poi")) m.setLayoutProperty(l.id, "visibility", "none");
        }
      });
      // the credits only as their ⓘ (on a narrow screen MapLibre opens them, covering the band)
      m.once("load", () => box.current?.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show"));
      const el = document.createElement("div");
      paintPin(el, onSite);
      // the dot tells what it means; a tap anywhere else on the map closes that
      el.style.cursor = "pointer";
      el.setAttribute("role", "button");
      el.setAttribute("aria-label", "Chi c'è in cantiere");
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        setInfo((v) => {
          // opening, the map slides so the dot stands at the right, beside the card
          if (!v) m.easeTo({ center: [lon, lat], offset: [Math.max(0, (box.current?.clientWidth || 0) / 2 - 48), 14], duration: 400 });
          return !v;
        });
      });
      m.on("click", () => setInfo(false));
      pin.current = new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(m);
      map.current = m;
    })();
    return () => { gone = true; };
  }, [lat, lon, h, onSite]);
  useEffect(() => () => { map.current?.remove(); map.current = null; }, []);

  // the site moved, or someone arrived / left
  useEffect(() => {
    if (!map.current || lat == null) return;
    pin.current?.setLngLat([lon, lat]);
    if (pin.current) paintPin(pin.current.getElement(), onSite);
    map.current.jumpTo({ center: [lon, lat] });
  }, [lat, lon, onSite]);

  const settle = (next) => { setMode(next); keep(next); setH(heightOf(next)); if (next === "closed") setInfo(false); };

  // the bar: drag (up to the band's height at most, then it snaps open or closed) or tap
  const down = (e) => {
    e.currentTarget.setPointerCapture?.(e.pointerId);
    drag.current = { y: e.clientY, h, moved: false };
    setDragging(true);
  };
  const move = (e) => {
    const d = drag.current;
    if (!d) return;
    const dy = e.clientY - d.y;
    if (Math.abs(dy) > 5) d.moved = true;
    if (d.moved) setH(Math.max(0, Math.min(BAND, d.h + dy)));
  };
  const up = () => {
    const d = drag.current;
    drag.current = null;
    setDragging(false);
    if (!d) return;
    if (!d.moved) { settle(mode === "closed" ? "band" : "closed"); return; }
    settle(h > BAND / 2 ? "band" : "closed");
  };

  if (lat == null) return null;
  return (
    <div className={`relative ${className}`} data-testid="site-map">
      <div className="relative overflow-hidden" style={{ height: h, transition: dragging ? "none" : "height 240ms cubic-bezier(.2,.8,.2,1)" }}>
        <div ref={box} className="absolute inset-x-0 top-0 sitemap" style={{ height: BAND }} data-testid="site-map-canvas" />
        {info && (
          <div className="absolute left-2 top-2 z-[5] w-[calc(100%-104px)] max-w-[360px] glass-panel !rounded-2xl px-3 py-2 flex items-start gap-2.5 text-white" data-testid="site-map-info">
            <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: onSite ? "#2FBF71" : "#F2701E", boxShadow: `0 0 0 3px ${onSite ? "rgba(47,191,113,.3)" : "rgba(242,112,30,.3)"}` }} />
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] font-semibold leading-tight">{onSite ? `In cantiere ora: ${onSite}` : "Nessuno in cantiere ora"}</div>
              <div className="text-[11.5px] text-white/75 leading-snug truncate">
                {onSite ? people.map((p) => `${(p.name || "").split(" ")[0]} dalle ${hhmm(p.since)}`).join(" · ") : (address || "Il pallino è il cantiere")}
              </div>
              <div className="text-[10.5px] text-white/55 leading-snug truncate">{onSite ? (address || "") : "Diventa verde quando qualcuno è arrivato"}</div>
            </div>
            <a href={`https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`} target="_blank" rel="noreferrer" data-testid="site-map-navigate"
              aria-label="Naviga fino al cantiere" className="h-8 w-8 shrink-0 rounded-full bg-white/15 flex items-center justify-center"><Navigation size={14} /></a>
            <button type="button" onClick={() => setInfo(false)} aria-label="Chiudi" className="h-8 w-6 shrink-0 flex items-center justify-center text-white/70"><X size={14} /></button>
          </div>
        )}
      </div>
      {/* the bar, like a sheet's: drag it up to hide the map, down to bring it back */}
      <button type="button" aria-label={mode === "closed" ? "Mostra la mappa" : "Nascondi la mappa"} data-testid="site-map-handle"
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
        className="block w-full pt-2 pb-2.5 cursor-grab active:cursor-grabbing touch-none">
        <span className="block w-10 h-1 rounded-full bg-white/45 mx-auto" />
      </button>
    </div>
  );
}
