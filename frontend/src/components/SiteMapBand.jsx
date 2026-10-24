import React, { useCallback, useEffect, useRef, useState } from "react";
import { Crosshair, Navigation } from "lucide-react";

/* The commessa's site on a colour map (OpenStreetMap), as a band across the diary under its
   figures. The bar under it is dragged like a sheet's: up to hide the map, down to open it
   more; a tap closes it or opens it again. Small, it is a picture of where the site is (one
   finger keeps scrolling the page, two zoom); opened wide it is a map to move around, with a
   button back to the site and one to get there. The dot is green, with how many, when someone
   is on site now. Leaflet comes in its own chunk, only when a diary with a site is opened. */

const BAND = 120;                                  // the band as it opens (px)
const bigH = () => Math.round(Math.min(440, window.innerHeight * 0.55));
const KEY = "maipal.diary.map";                     // closed | band | big, kept on this device
const read = () => { try { return localStorage.getItem(KEY) || "band"; } catch { return "band"; } };
const keep = (v) => { try { localStorage.setItem(KEY, v); } catch { /* private mode */ } };
const heightOf = (mode) => (mode === "closed" ? 0 : mode === "big" ? bigH() : BAND);

function pinHtml(onSite) {
  const busy = onSite > 0;
  return `<div style="position:relative;width:24px;height:24px">
    ${busy ? '<span class="sitemap-pulse"></span>' : ""}
    <span style="position:absolute;inset:3px;border-radius:50%;border:3px solid #fff;background:${busy ? "#2FBF71" : "#F2701E"};box-shadow:0 3px 8px rgba(30,10,25,.45)"></span>
    ${busy ? `<span style="position:absolute;right:-8px;top:-8px;min-width:17px;height:17px;padding:0 4px;border-radius:9px;background:#fff;color:#1E7D4B;font:700 10.5px/17px sans-serif;text-align:center;box-shadow:0 2px 5px rgba(0,0,0,.25)">${onSite}</span>` : ""}
  </div>`;
}

export default function SiteMapBand({ geo, onSite = 0, className = "" }) {
  const box = useRef(null);
  const map = useRef(null);
  const marker = useRef(null);
  const [mode, setMode] = useState(read);
  const [h, setH] = useState(() => heightOf(read()));
  const [dragging, setDragging] = useState(false);
  const drag = useRef(null);
  const lastOpen = useRef(read() === "closed" ? "band" : read());
  const lat = geo?.lat, lon = geo?.lon;

  const fit = useCallback(() => { map.current?.invalidateSize(); }, []);
  const recenter = useCallback(() => {
    if (map.current && lat != null) map.current.setView([lat, lon], mode === "big" ? 16 : 15, { animate: true });
  }, [lat, lon, mode]);

  // the map, once, when the band first has room
  useEffect(() => {
    if (lat == null || map.current || h === 0) return undefined;
    let gone = false;
    (async () => {
      const L = (await import("leaflet")).default;
      await import("leaflet/dist/leaflet.css");
      if (gone || !box.current || map.current) return;
      const m = L.map(box.current, { zoomControl: false, scrollWheelZoom: false, attributionControl: true, tap: false });
      m.attributionControl.setPrefix(false);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(m);
      m.setView([lat, lon], 15);
      marker.current = L.marker([lat, lon], { keyboard: false, icon: L.divIcon({ className: "", html: pinHtml(onSite), iconSize: [24, 24], iconAnchor: [12, 12] }) }).addTo(m);
      map.current = m;
      setTimeout(fit, 50);
    })();
    return () => { gone = true; };
  }, [lat, lon, h, onSite, fit]);
  useEffect(() => () => { map.current?.remove(); map.current = null; }, []);

  // the site moved, or someone arrived / left
  useEffect(() => {
    if (!map.current || lat == null) return;
    marker.current?.setLatLng([lat, lon]);
    import("leaflet").then(({ default: L }) => marker.current?.setIcon(L.divIcon({ className: "", html: pinHtml(onSite), iconSize: [24, 24], iconAnchor: [12, 12] })));
    map.current.setView([lat, lon], map.current.getZoom());
  }, [lat, lon, onSite]);

  // small: one finger scrolls the page (the map only zooms with two); wide (or with a mouse): it moves too
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const touch = window.matchMedia?.("(pointer: coarse)").matches;
    if (mode === "big" || !touch) m.dragging.enable(); else m.dragging.disable();
    const t = setTimeout(() => { fit(); if (mode !== "closed") m.setView([lat, lon], m.getZoom()); }, 280);
    return () => clearTimeout(t);
  }, [mode, h, lat, lon, fit]);

  const settle = (next) => {
    setMode(next); keep(next);
    if (next !== "closed") lastOpen.current = next;
    setH(heightOf(next));
  };

  // the bar: drag (snaps to closed / band / wide) or tap (closes, or opens again)
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
    if (d.moved) { setH(Math.max(0, Math.min(bigH(), d.h + dy))); requestAnimationFrame(fit); }
  };
  const up = () => {
    const d = drag.current;
    drag.current = null;
    setDragging(false);
    if (!d) return;
    if (!d.moved) { settle(mode === "closed" ? lastOpen.current : "closed"); return; }
    const big = bigH();
    const snaps = [["closed", 0], ["band", BAND], ["big", big]];
    const [next] = snaps.reduce((best, s) => (Math.abs(s[1] - h) < Math.abs(best[1] - h) ? s : best));
    settle(next);
  };

  if (lat == null) return null;
  return (
    <div className={`relative ${className}`} data-testid="site-map">
      <div className="relative overflow-hidden" style={{ height: h, transition: dragging ? "none" : "height 240ms cubic-bezier(.2,.8,.2,1)" }}>
        <div ref={box} className="absolute inset-0 sitemap" data-testid="site-map-canvas" />
        {mode === "big" && h > 160 && (
          <div className="absolute right-3 bottom-3 z-[500] flex flex-col gap-2">
            <button type="button" onClick={recenter} aria-label="Torna al cantiere" data-testid="site-map-center"
              className="h-10 w-10 rounded-full bg-white/85 text-[#3A2433] flex items-center justify-center shadow-md active:scale-95">
              <Crosshair size={18} />
            </button>
            <a href={`https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`} target="_blank" rel="noreferrer"
              aria-label="Naviga fino al cantiere" data-testid="site-map-navigate"
              className="h-10 w-10 rounded-full bg-white/85 text-[#3A2433] flex items-center justify-center shadow-md active:scale-95">
              <Navigation size={17} />
            </a>
          </div>
        )}
      </div>
      {/* the bar, like a sheet's: drag it up to hide the map, down to open it more */}
      <button type="button" aria-label={mode === "closed" ? "Mostra la mappa" : "Nascondi la mappa"} data-testid="site-map-handle"
        onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
        className="block w-full pt-2 pb-2.5 cursor-grab active:cursor-grabbing touch-none">
        <span className="block w-10 h-1 rounded-full bg-white/45 mx-auto" />
      </button>
    </div>
  );
}
