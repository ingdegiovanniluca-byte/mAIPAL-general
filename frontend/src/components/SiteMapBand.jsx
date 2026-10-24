import React, { useEffect, useRef, useState } from "react";

/* The commessa's site on a colour map, as a band across the diary under its figures - never
   taller than that. The map is OpenFreeMap's "Liberty" style (OpenStreetMap's data drawn like
   Google Maps: yellow main roads, light grey blocks, green parks; free, no key), flat (no 3D
   buildings), with MapLibre - it comes in its own chunk, only when a diary with a site is opened.
   The bar under it is dragged like a sheet's: up to hide the map, down to bring it back; a tap
   closes it or opens it again. One finger keeps scrolling the page (two zoom; with a mouse it
   also moves). The dot is green, with how many, when someone is on site now; orange otherwise. */

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

export default function SiteMapBand({ geo, onSite = 0, className = "" }) {
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
      const touch = window.matchMedia?.("(pointer: coarse)").matches;
      const m = new maplibregl.Map({
        container: box.current, style: STYLE, center: [lon, lat], zoom: ZOOM,
        attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false, touchPitch: false,
        scrollZoom: false, dragPan: !touch, cooperativeGestures: false,
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

  const settle = (next) => { setMode(next); keep(next); setH(heightOf(next)); };

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
