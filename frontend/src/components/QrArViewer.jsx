import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader";
import jsQR from "jsqr";
import aruco from "js-aruco2";
import { X, Loader2 } from "lucide-react";
import { API } from "@/lib/api";
import { homography, poseFromHomography, focalPx, reprojectionError, labelMatrix, qrCorners, markerCorners, frameQrCorners } from "@/lib/arPose";

/* Augmented reality on a QR label: the camera, the label found in each frame (its QR's corners - mode "qr" - or
   also the 4 squares in its corners - mode "frame", steadier), and the QR's 3D model or photo drawn on it, so it
   follows the label when the label (or the phone) moves.

   Loaded only when "Vedi in realtà aumentata" is tapped (its own bundle: three.js, the QR reader, the markers' reader). */

// the frame is read at most this wide (speed; the pose is computed at full size): the AR label's small squares need
// more pixels (they hold from farther away), the QR alone is read close anyway
const DETECT_MAX = { frame: 1024, qr: 720 };
const LOST_MS = 450;             // the object stays this long after the label is lost (a blurred frame)
const MAX_REPROJ_PX = 6;         // points that don't fit a plane: not the label

export default function QrArViewer({ ar, onClose }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const [state, setState] = useState("starting");   // starting | searching | tracking | error
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let stopped = false, raf = 0, stream = null, renderer = null;
    const video = videoRef.current, canvas = canvasRef.current;
    const debug = (window.__arDebug = { tracked: false, source: null, frames: 0, detections: 0 });

    const fail = (msg) => { if (!stopped) { setError(msg); setState("error"); } };

    (async () => {
      // ---- the camera (the back one)
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } } });
      } catch (e) {
        fail(e?.name === "NotAllowedError"
          ? "Hai negato la fotocamera: consentila a questo sito nelle impostazioni del browser e riprova."
          : "Non riesco ad aprire la fotocamera di questo telefono.");
        return;
      }
      if (stopped) { stream.getTracks().forEach((t) => t.stop()); return; }
      video.srcObject = stream;
      await video.play().catch(() => {});
      await new Promise((r) => (video.videoWidth ? r() : video.addEventListener("loadedmetadata", r, { once: true })));
      const vw = video.videoWidth, vh = video.videoHeight;
      const f = focalPx(vw, vh), cx = vw / 2, cy = vh / 2;

      // ---- the 3D view: a camera like the phone's, the object on the label
      renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
      renderer.setPixelRatio(1);
      renderer.setSize(vw, vh, false);
      renderer.outputEncoding = THREE.sRGBEncoding;
      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera((2 * Math.atan(vh / 2 / f) * 180) / Math.PI, vw / vh, 0.5, 100000);
      scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.0));
      const sun = new THREE.DirectionalLight(0xffffff, 0.9);
      sun.position.set(30, 60, 80);
      scene.add(sun);
      const anchor = new THREE.Group();          // = the label (its pose, from the camera)
      anchor.matrixAutoUpdate = false;
      anchor.visible = false;
      scene.add(anchor);
      const placed = new THREE.Group();          // the administrator's position, rotation and scale on the label
      const [ox, oy, oz] = ar.offset_cm || [0, 0, 0], [rx, ry, rz] = (ar.rot_deg || [0, 0, 0]).map((d) => (d * Math.PI) / 180);
      placed.position.set(ox, oy, oz);
      placed.rotation.set(rx, ry, rz);
      anchor.add(placed);

      // ---- what is shown: the model (GLB, in meters -> cm) or the photo (a panel of width_cm)
      try {
        const url = `${API}/${ar.url}`;
        if (ar.kind === "model") {
          const gltf = await new Promise((res, rej) => {
            const loader = new GLTFLoader();
            loader.setWithCredentials(true);
            loader.load(url, res, undefined, rej);
          });
          gltf.scene.scale.setScalar(100 * (ar.scale || 1));
          placed.add(gltf.scene);
        } else {
          const tex = await new Promise((res, rej) => {
            const l = new THREE.TextureLoader();
            l.setCrossOrigin("use-credentials");
            l.load(url, res, undefined, rej);
          });
          tex.encoding = THREE.sRGBEncoding;
          const w = ar.width_cm || 20, h = (w * tex.image.height) / tex.image.width;
          const panel = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide, transparent: true }));
          panel.position.z = 0.2;                 // (just off the label)
          placed.add(panel);
        }
      } catch (e) {
        fail("Non riesco a caricare il contenuto in realtà aumentata (modello o foto). Controlla la connessione e riprova.");
        return;
      }
      if (stopped) return;
      setLoading(false);
      setState("searching");

      // ---- each frame: find the label, its pose, the object on it
      const det = document.createElement("canvas");
      const k = Math.min(1, (DETECT_MAX[ar.label] || 720) / Math.max(vw, vh));
      det.width = Math.round(vw * k); det.height = Math.round(vh * k);
      const ctx = det.getContext("2d", { willReadFrequently: true });
      // (a strict reading: with the dictionary's default tolerance, pieces of the QR itself read as markers)
      const markers = ar.label === "frame" ? new aruco.AR.Detector({ dictionaryName: "ARUCO_MIP_36h12", maxHammingDistance: 2 }) : null;
      const S = ar.label_cm, mods = ar.qr_modules || 29;
      const qrWorld = ar.label === "frame" ? frameQrCorners(S, mods) : qrCorners(S, mods);
      const code = (ar.code || "").toUpperCase();
      let lastSeen = 0, frameNo = 0;
      const pos = new THREE.Vector3(), quat = new THREE.Quaternion(), scl = new THREE.Vector3();
      const sPos = new THREE.Vector3(), sQuat = new THREE.Quaternion();
      let smoothed = false;

      const step = () => {
        if (stopped) return;
        raf = requestAnimationFrame(step);
        if (video.readyState < 2) return;
        frameNo++;
        debug.frames = frameNo;
        ctx.drawImage(video, 0, 0, det.width, det.height);
        const img = ctx.getImageData(0, 0, det.width, det.height);
        const world = [], image = [];
        // the QR: every frame in mode "qr"; in mode "frame" every 4th (more points when it is near enough to be read -
        // the 4 squares alone are enough, and they hold from farther away than the QR can be read)
        if (!markers || frameNo % 4 === 1) {
          const q = jsQR(img.data, det.width, det.height, { inversionAttempts: "dontInvert" });
          if (q && (q.data || "").toUpperCase().replace(/[\s-]/g, "").includes(code)) {
            const L = q.location;
            [L.topLeftCorner, L.topRightCorner, L.bottomRightCorner, L.bottomLeftCorner].forEach((c, i) => { world.push(qrWorld[i]); image.push([c.x / k, c.y / k]); });
          }
        }
        if (markers) {
          const best = {};   // one per id (0-3): the surest reading
          for (const m of markers.detectImage(det.width, det.height, img.data)) {
            if (m.id <= 3 && (!best[m.id] || m.hammingDistance < best[m.id].hammingDistance)) best[m.id] = m;
          }
          Object.values(best).forEach((m) => markerCorners(m.id, S).forEach((p, i) => { world.push(p); image.push([m.corners[i].x / k, m.corners[i].y / k]); }));
        }
        const now = performance.now();
        let found = false;
        if (world.length >= 4) {
          const H = homography(world, image);
          const pose = H && poseFromHomography(H, f, cx, cy);
          const err = H ? reprojectionError(H, world, image) : Infinity;
          if (pose && err <= MAX_REPROJ_PX * Math.max(1, 1 / k)) {
            found = true;
            lastSeen = now;
            debug.detections++;
            debug.source = markers && world.length > 4 ? "markers" : "qr";
            debug.err = err;
            debug.points = world.length;
            const m = new THREE.Matrix4().fromArray(labelMatrix(pose));
            m.decompose(pos, quat, scl);
            if (!smoothed) { sPos.copy(pos); sQuat.copy(quat); smoothed = true; }
            else {
              // steadier with more points (the frame label) - quicker to follow when it moves a lot
              const jump = sPos.distanceTo(pos) / Math.max(1, pos.length());
              const a = Math.min(1, (markers ? 0.55 : 0.35) + jump * 4);
              sPos.lerp(pos, a);
              sQuat.slerp(quat, a);
            }
            anchor.matrix.compose(sPos, sQuat, new THREE.Vector3(1, 1, 1));
            anchor.matrixWorldNeedsUpdate = true;
            // (for the tests: where the label's center is drawn, in video pixels)
            const c = new THREE.Vector3(0, 0, 0).applyMatrix4(anchor.matrix).project(camera);
            debug.center = [((c.x + 1) / 2) * vw, ((1 - c.y) / 2) * vh];
            debug.distance_cm = sPos.length();
          }
        }
        const visible = found || now - lastSeen < LOST_MS;
        if (!visible) smoothed = false;
        anchor.visible = visible;
        debug.tracked = visible;
        setState((s) => (s === "error" ? s : visible ? "tracking" : "searching"));
        renderer.render(scene, camera);
      };
      step();
    })();

    return () => {
      stopped = true;
      cancelAnimationFrame(raf);
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (renderer) renderer.dispose();
    };
  }, [ar]);

  const hint = ar.label === "frame"
    ? "Inquadra l'etichetta AR: il QR e i 4 riquadri agli angoli"
    : "Inquadra il QR da vicino, dritto e con buona luce";

  return (
    <div className="fixed inset-0 z-[100] bg-black" data-testid="qr-ar">
      <video ref={videoRef} playsInline muted autoPlay className="absolute inset-0 h-full w-full object-cover" />
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full object-cover pointer-events-none" />
      <div className="absolute top-0 left-0 right-0 p-4 flex items-start justify-between gap-3 bg-gradient-to-b from-black/60 to-transparent">
        <div className="text-white text-sm leading-snug pt-1.5" data-testid="qr-ar-status">
          {state === "error" ? error
            : loading ? <span className="inline-flex items-center gap-2"><Loader2 size={15} className="animate-spin" /> Preparo la realtà aumentata…</span>
            : state === "tracking" ? "Agganciato all'etichetta" : hint}
        </div>
        <button type="button" onClick={onClose} aria-label="Chiudi la realtà aumentata" data-testid="qr-ar-close"
          className="h-10 w-10 shrink-0 rounded-full bg-white/20 backdrop-blur flex items-center justify-center text-white"><X size={18} /></button>
      </div>
    </div>
  );
}
