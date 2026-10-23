import React, { useEffect, useRef } from "react";
import * as THREE from "three";
import { VERT, FRAG } from "./shaders";
import { AGENTS, MATS, STATES, EYES } from "./config";
import { roleMods, newMemory } from "./behaviour";

/* The chat agent as a 3D drop (the "Gocce Agenti" prototype, Three.js r128 like the prototype so
   colours and lights stay the same): one renderer, kept while the agent changes - the drop
   melts into the new agent's colours, eyes and accessory. It only animates while on screen and
   the app is in front; with "reduce motion" it barely moves. If WebGL can't start, onFail. */

const HAT_PY = .34;

// the vertex shader's shape() in JS: fits the hard hat on the head (change one, change the other)
function shapeAt(py, tip) {
  const k = Math.min(Math.max((py + .25) / 1.25, 0), 1), s = k * k * (3 - 2 * k);
  const taper = 1 - tip * .9 * s * s, rr = Math.sqrt(Math.max(0, 1 - py * py)) * taper;
  const up = Math.max(py, 0);
  return { r: rr, y: py + tip * .55 * up * up * up - .14 * tip };
}

function makeUniforms() {
  return {
    uPhase: { value: 0 }, uAmp: { value: .03 }, uFreq: { value: 1.4 }, uTip: { value: .7 }, uScale: { value: 1 },
    uA: { value: new THREE.Color() }, uB: { value: new THREE.Color() }, uSwirl: { value: 0 }, uGlow: { value: 1 }, uSpec: { value: 1 },
    uShine: { value: 80 }, uRim: { value: 1 }, uIrid: { value: 0 }, uMilk: { value: 0 }, uMetal: { value: 0 }, uHue: { value: 0 },
    uBlink: { value: 1 }, uEyeH: { value: 1 }, uLook: { value: new THREE.Vector2(0, 0) }, uGlasses: { value: 0 }, uHat: { value: 0 }, uHatY: { value: HAT_PY },
    uMask: { value: 0 }, uClip: { value: 0 }, uClipY: { value: .82 }, uShK: { value: 0 }, uShR: { value: .2 },
    uShA: { value: new THREE.Vector3() }, uShB: { value: new THREE.Vector3() }, uEyeR: { value: new THREE.Vector2(.075, .13) }, uCut: { value: 0 }, uLid: { value: 1 },
  };
}

// a small photo studio, only for the hard hat's soft reflections
function makeEnv(r, trash) {
  const es = new THREE.Scene();
  const g = new THREE.SphereGeometry(10, 32, 16); const cols = []; const pos = g.attributes.position;
  for (let i = 0; i < pos.count; i++) { const t = (pos.getY(i) / 10 + 1) / 2; const c = new THREE.Color().setRGB(.08 + .55 * t * t, .07 + .5 * t * t, .1 + .5 * t * t); cols.push(c.r, c.g, c.b); }
  g.setAttribute("color", new THREE.Float32BufferAttribute(cols, 3));
  const sky = new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide });
  es.add(new THREE.Mesh(g, sky)); trash.push(g, sky);
  const pnl = (w, h, x, y, z, v) => {
    const pg = new THREE.PlaneGeometry(w, h), pm = new THREE.MeshBasicMaterial({ color: new THREE.Color(v, v, v), side: THREE.DoubleSide });
    const m = new THREE.Mesh(pg, pm); m.position.set(x, y, z); m.lookAt(0, 0, 0); es.add(m); trash.push(pg, pm);
  };
  pnl(5, 3, -4, 5, 4, 2.2); pnl(2, 5, 6, 1, 2, 1.2); pnl(6, 1, 0, -3, 6, .5);
  const pm = new THREE.PMREMGenerator(r); const tex = pm.fromScene(es, .03).texture; pm.dispose();
  trash.push(tex);
  return tex;
}

// the hard hat: turned shell, three ribs, strap with buckles, peak
function buildHat(trash) {
  const root = new THREE.Group(), tilt = new THREE.Group(); root.add(tilt);
  const keep = (x) => { trash.push(x); return x; };
  const phys = (c, r) => keep(new THREE.MeshPhysicalMaterial({ color: c, roughness: r, clearcoat: .6, clearcoatRoughness: .25, envMapIntensity: .5 }));
  const yel = phys(0xf5c000, .4), yelRib = phys(0xe8a800, .36), strap = phys(0xf3d46a, .62), buckle = phys(0xe9bf3c, .45), slot = phys(0x7a5a0c, .7);
  const prof = (t) => ({ r: Math.cos(t) * (1 + .04 * Math.sin(t * 2)), y: Math.pow(Math.sin(t), .85) });
  const pts = []; for (let i = 0; i <= 28; i++) { const p = prof(i / 28 * Math.PI / 2); pts.push(new THREE.Vector2(p.r, p.y)); }
  const shell = new THREE.Group();
  shell.add(new THREE.Mesh(keep(new THREE.LatheGeometry(pts, 72)), yel));
  const capPts = []; for (let i = 0; i <= 24; i++) { const p = prof(.5 + i / 24 * (Math.PI / 2 - .5)); capPts.push(new THREE.Vector2(p.r, p.y)); }
  const capG = keep(new THREE.LatheGeometry(capPts, 64));
  const r0 = new THREE.Mesh(capG, yelRib); r0.scale.set(.17, 1.035, 1.035); shell.add(r0);
  for (const sx of [-.37, .37]) { const r1 = new THREE.Mesh(capG, yelRib); r1.scale.set(.14, .966, .96); r1.position.x = sx; shell.add(r1); }
  const band = new THREE.Mesh(keep(new THREE.CylinderGeometry(1.025, 1.03, .15, 80, 1, true)), strap); band.position.y = .1; shell.add(band);
  const fG = keep(new THREE.BoxGeometry(.16, .16, .035)), sG = keep(new THREE.BoxGeometry(.075, .075, .04));
  for (const ph of [-1.3, -.55, .55, 1.3]) {
    const g = new THREE.Group(); g.position.set(1.045 * Math.sin(ph), .1, 1.045 * Math.cos(ph)); g.rotation.y = ph;
    g.add(new THREE.Mesh(fG, buckle));
    const s = new THREE.Mesh(sG, slot); s.position.z = .004; g.add(s);
    shell.add(g);
  }
  const brimShape = new THREE.Shape(); const N = 96;
  for (let i = 0; i <= N; i++) { const a = i / N * Math.PI * 2; const f = 1.05 + .36 * Math.pow(Math.max(0, Math.sin(a)), 1.7); const x = Math.cos(a) * f, z = Math.sin(a) * f; if (i) brimShape.lineTo(x, z); else brimShape.moveTo(x, z); }
  const brimG = keep(new THREE.ExtrudeGeometry(brimShape, { depth: .04, bevelEnabled: true, bevelThickness: .022, bevelSize: .028, bevelSegments: 4, curveSegments: 96 }));
  brimG.rotateX(Math.PI / 2); brimG.translate(0, .03, 0);
  const pa = brimG.attributes.position;
  for (let i = 0; i < pa.count; i++) { const r = Math.hypot(pa.getX(i), pa.getZ(i)); if (r > 1.1) pa.setY(i, pa.getY(i) - (r - 1.1) * (r - 1.1) * (.5 + 1.0 * Math.max(0, pa.getZ(i)) / r)); }
  brimG.computeVertexNormals();
  const brimWrap = new THREE.Group(); brimWrap.add(new THREE.Mesh(brimG, yel));
  tilt.add(shell, brimWrap);
  return { root, tilt, shell, brimWrap };
}

function fitHat(h, tip) {
  const b = shapeAt(HAT_PY, tip), top = shapeAt(1, tip).y;
  let R = b.r * 1.03 + .03; const H = (top - b.y) * 1.08 + .1;
  // widen the shell until the whole head fits inside
  for (let it = 0; it < 40; it++) {
    let ok = true;
    for (let py = HAT_PY; py <= 1; py += .03) {
      const s = shapeAt(py, tip), hh = (s.y - b.y) / H; if (hh >= 1) { ok = false; break; }
      const dr = R * Math.pow(Math.max(0, 1 - Math.pow(hh, 1 / .85)), .5) * .98; if (s.r > dr - .03) { ok = false; break; }
    }
    if (ok) break; R *= 1.015;
  }
  h.shell.scale.set(R, H, R * 1.04); h.brimWrap.scale.set(R, 1, R * 1.04);
  h.root.userData.y = b.y - .04;
}

function applyAcc(sc, ag) {
  const A = ag.acc || "", u = sc.uniforms;
  u.uGlasses.value = A === "occhiali" ? 1 : 0; u.uMask.value = A === "mascherina" ? 1 : 0;
  const hatOn = A === "caschetto";
  u.uHat.value = hatOn ? 1 : 0; u.uHatY.value = HAT_PY; u.uClip.value = 0; u.uShK.value = 0;
  sc.hat.root.visible = hatOn;
  if (hatOn) { fitHat(sc.hat, ag.tip); sc.hat.root.position.y = sc.hat.root.userData.y; }
}

const lerp = (a, b, t) => a + (b - a) * t;

export default function AgentDrop({ agent = "cerca", state = "idle", size = 120, onFail, className = "" }) {
  const canvasRef = useRef(null);
  const live = useRef({ agent, state });
  live.current.agent = agent;
  live.current.state = state;

  useEffect(() => {
    const canvas = canvasRef.current;
    const trash = [];
    let r;
    try {
      r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: false });
    } catch (e) {
      onFail && onFail();
      return undefined;
    }
    r.setClearColor(0x000000, 0);
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    r.setSize(size, size, false);
    const scene = new THREE.Scene();
    const cam = new THREE.PerspectiveCamera(32, 1, .1, 50); cam.position.set(0, 0.15, 5.6);
    const uniforms = makeUniforms();
    const mat = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, uniforms, extensions: { derivatives: true } });
    const geo = new THREE.SphereGeometry(1, 112, 112);
    trash.push(mat, geo);
    const pivot = new THREE.Group(); pivot.position.y = -0.05; pivot.add(new THREE.Mesh(geo, mat)); scene.add(pivot);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3050, .45));
    const dl = new THREE.DirectionalLight(0xfff4e6, .75); dl.position.set(-2, 3, 3); scene.add(dl);
    scene.environment = makeEnv(r, trash);
    const hat = buildHat(trash); hat.root.visible = false; pivot.add(hat.root);
    const sc = { uniforms, hat, hatOff: 0, hatVel: 0 };

    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const mot = reduced ? .35 : 1;
    let cur = AGENTS[live.current.agent] || AGENTS.cerca;
    applyAcc(sc, cur);
    const A = new THREE.Color(cur.a), B = new THREE.Color(cur.b);
    const tgtA = new THREE.Color(), tgtB = new THREE.Color();
    const lv = { amp: .035, speed: .35, freq: 1.4, swirl: .3, glow: 1, scale: 1, spec: 1.3, shine: 90, rim: 1, glowM: 1, irid: .15, milk: 0, metal: 0 };
    const eyeP = { ...(EYES[cur.eye] || EYES.normali) };
    const look = { x: 0, y: 0 }; const mem = newMemory();
    let last = performance.now(), phase = 0, swirl = 0, hue = 0, level = 0, levelT = 0, nextSyl = 0;
    let nextBlink = last + 1500, blinkStart = -1e9, doubleBlink = false, nextGlance = 0, glance = { x: 0, y: 0 }, eyeH = 1;
    let hopS = 0, sqS = 1, prevHop = 0, prevHv = 0, lastDraw = 0;
    uniforms.uTip.value = cur.tip;

    let raf = 0, onScreen = true, failed = false;
    const frame = (now) => {
      raf = 0;
      if (failed || !onScreen || document.hidden) return;
      raf = requestAnimationFrame(frame);
      const stateKey = live.current.state in STATES ? live.current.state : "idle";
      // at rest 30 frames a second are enough (battery); working or listening, all of them
      if (stateKey === "idle" && now - lastDraw < 32) return;
      lastDraw = now;
      const next = AGENTS[live.current.agent] || AGENTS.cerca;
      if (next !== cur) { cur = next; applyAcc(sc, cur); }
      // dt never negative nor too big: otherwise on some browsers the drop vanishes or the eyes drift
      const dt = Math.min(Math.max((now - last) / 1000, 0), .05); last = Math.max(now, last);
      const S = STATES[stateKey], M = MATS[cur.mat] || MATS.vetro, k = 1 - Math.exp(-dt * 5);
      // "speaks": the app has no voice of its own, so a simulated level, as in the prototype
      if (stateKey === "speak") {
        if (now > nextSyl) { levelT = Math.random() < .18 ? 0.05 : 0.35 + Math.random() * .65; nextSyl = now + 90 + Math.random() * 160; }
      } else levelT = 0;
      level = lerp(level, levelT, 1 - Math.exp(-dt * 14));
      const tAmp = (S.amp + (stateKey === "speak" ? .07 * level : 0)) * cur.wav;
      const tGlow = S.glow + (stateKey === "speak" ? .7 * level : 0);
      const tScale = S.scale + (stateKey === "speak" ? .05 * level : 0);
      const ts = now / 1000;
      const R = roleMods(cur.beh, stateKey, ts, mem);
      lv.amp = lerp(lv.amp, tAmp * R.amp + R.bump, k * 1.5); lv.speed = lerp(lv.speed, S.speed * R.speed, k); lv.freq = lerp(lv.freq, S.freq * R.freq, k);
      lv.swirl = lerp(lv.swirl, S.swirl, k); lv.glowM = lerp(lv.glowM, tGlow, k); lv.scale = lerp(lv.scale, tScale, k * 1.6);
      for (const key of ["spec", "shine", "rim", "irid", "milk", "metal"]) lv[key] = lerp(lv[key], M[key], k);
      lv.glow = lerp(lv.glow, M.glow * cur.glw, k);
      A.lerp(tgtA.set(cur.a), k); B.lerp(tgtB.set(cur.b), k);

      phase += dt * lv.speed * mot; swirl += dt * lv.swirl * mot; hue += dt * .05 * mot * (stateKey === "think" ? 4 : 1);
      const breathe = 1 + Math.sin(ts * 1.6 * mot) * .012;
      const u = uniforms;
      u.uPhase.value = phase; u.uAmp.value = lv.amp; u.uFreq.value = lv.freq; u.uTip.value = lerp(u.uTip.value, cur.tip, k); u.uScale.value = lv.scale * breathe;
      u.uA.value.copy(A); u.uB.value.copy(B); u.uSwirl.value = swirl; u.uGlow.value = lv.glow * lv.glowM;
      u.uSpec.value = lv.spec; u.uShine.value = lv.shine; u.uRim.value = lv.rim; u.uIrid.value = lv.irid; u.uMilk.value = lv.milk; u.uMetal.value = lv.metal; u.uHue.value = hue;
      // eyes: blinking, gaze, expression by state
      if (now > nextBlink) { blinkStart = now; nextBlink = now + 2200 + Math.random() * 3200; if (Math.random() < .2) doubleBlink = true; }
      let bl = 1; const bt = (now - blinkStart) / 160;
      if (bt >= 0 && bt < 1) bl = Math.abs(Math.cos(bt * Math.PI));
      else if (doubleBlink && bt >= 1.3 && bt < 2.3) bl = Math.abs(Math.cos((bt - 1.3) * Math.PI));
      else if (bt >= 2.3) doubleBlink = false;
      if (R.blink !== null) bl = Math.min(bl, R.blink);
      if (reduced) bl = 1;
      let lookT;
      if (R.look) lookT = R.look;
      else if (stateKey === "think") lookT = { x: .9 + Math.sin(ts * 2.2) * .25, y: .9 };
      else if (stateKey === "listen") lookT = { x: 0, y: .15 };
      else if (stateKey === "speak") lookT = { x: Math.sin(ts * .9) * .25, y: .05 };
      else { if (now > nextGlance) { glance = { x: (Math.random() * 2 - 1) * .9, y: (Math.random() * 2 - 1) * .5 }; nextGlance = now + 1400 + Math.random() * 2600; } lookT = glance; }
      const ls = R.lookSpeed || 10;
      look.x = lerp(look.x, lookT.x, 1 - Math.exp(-dt * ls)); look.y = lerp(look.y, lookT.y, 1 - Math.exp(-dt * ls));
      let eyeHT = stateKey === "listen" ? 1.15 : stateKey === "think" ? .8 : stateKey === "speak" ? 1 + .08 * level : 1;
      if (R.eyeH !== null) eyeHT = R.eyeH;
      eyeH = lerp(eyeH, eyeHT, 1 - Math.exp(-dt * (R.eyeSpeed || 5)));
      const E = EYES[cur.eye] || EYES.normali;
      eyeP.rx = lerp(eyeP.rx, E.rx, k); eyeP.ry = lerp(eyeP.ry, E.ry, k); eyeP.cut = lerp(eyeP.cut, E.cut, k); eyeP.lid = lerp(eyeP.lid, E.lid, k);
      u.uEyeR.value.set(eyeP.rx, eyeP.ry); u.uCut.value = eyeP.cut < .004 ? 0 : eyeP.cut; u.uLid.value = eyeP.lid;
      u.uBlink.value = bl; u.uEyeH.value = eyeH; u.uLook.value.set(look.x, look.y);
      const sway = stateKey === "think" ? .28 : .16;
      pivot.rotation.y = (Math.sin(ts * .6) * sway + look.x * .12) * mot;
      pivot.rotation.x = (-look.y * .08) * mot;
      pivot.rotation.z = Math.sin(ts * .7) * .05 * mot;
      hopS = lerp(hopS, R.hop, 1 - Math.exp(-dt * 22)); sqS = lerp(sqS, R.squash, 1 - Math.exp(-dt * 22));
      const sq = 1 + (sqS - 1) * mot;
      pivot.scale.set(1 / Math.sqrt(sq), sq, 1 / Math.sqrt(sq));
      pivot.position.y = -0.05 + Math.sin(ts * 1.1 * mot) * .04 * (R.hop ? 0.3 : 1) + hopS * mot - (1 - sq) * .55;
      // the hard hat follows the drop on a spring: lags when it hops, bobs when it speaks
      {
        const scl = u.uScale.value, hv = (hopS - prevHop) / Math.max(dt, 1e-3); prevHop = hopS;
        const tgt = (stateKey === "speak" ? level * .045 : 0) + (stateKey === "listen" ? .012 : 0);
        sc.hatVel += ((tgt - sc.hatOff) * 160 - sc.hatVel * 13) * dt - (hv - prevHv) * .5; prevHv = hv; sc.hatOff += sc.hatVel * dt;
        const off = sc.hatOff * mot;
        if (hat.root.visible) {
          hat.root.scale.setScalar(scl); hat.root.position.y = (hat.root.userData.y || 0) * scl + off;
          hat.tilt.rotation.z = (-sc.hatVel * .25 + Math.sin(ts * .7 - .5) * .02) * mot; hat.tilt.rotation.x = (sc.hatVel * .12) * mot;
        }
      }
      r.render(scene, cam);
    };
    const kick = () => { if (!raf && onScreen && !document.hidden && !failed) { last = performance.now(); raf = requestAnimationFrame(frame); } };
    const io = typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; kick(); })
      : null;
    io?.observe(canvas);
    const onVis = () => kick();
    document.addEventListener("visibilitychange", onVis);
    const onLost = (e) => { e.preventDefault(); failed = true; onFail && onFail(); };
    canvas.addEventListener("webglcontextlost", onLost);
    kick();

    return () => {
      failed = true;
      if (raf) cancelAnimationFrame(raf);
      io?.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      canvas.removeEventListener("webglcontextlost", onLost);
      for (const x of trash) x.dispose?.();
      r.dispose();
      r.forceContextLoss?.();
    };
  }, [size]); // eslint-disable-line react-hooks/exhaustive-deps

  const ag = AGENTS[agent] || AGENTS.cerca;
  return (
    <div className={`relative ${className}`} style={{ width: size, height: size }}>
      {/* the soft coloured shadow under the drop */}
      <div aria-hidden="true" className="absolute left-1/2 -translate-x-1/2 rounded-full transition-[background] duration-500"
        style={{ bottom: "13%", width: "34%", height: "5%", filter: "blur(8px)", opacity: .8,
          background: `radial-gradient(closest-side, ${ag.a}80, transparent)` }} />
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full block" />
    </div>
  );
}
