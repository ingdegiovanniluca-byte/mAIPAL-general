/* Augmented reality on a QR label: from points of the label found in the camera's image to where the label is
   (position and tilt), so a 3D model can be drawn on it and follow it.

   The label is a plane: its points (in cm, center of the label = 0, x to the right, y down) and where they are
   in the image give a homography; with the camera's focal length the homography gives the rotation and the
   position of the label in front of the camera (the classic planar pose: H = K [r1 r2 t]).

   Also the label's geometry: where the QR and the 4 corner squares (ArUco markers, mode "frame") are printed. */

// ---------------------------------------------------------------- small linear algebra
function solve(A, b) {
  // Gaussian elimination with partial pivoting (A: n x n, b: n) -> x, or null if singular
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    if (Math.abs(M[p][c]) < 1e-12) return null;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = c + 1; r < n; r++) {
      const k = M[r][c] / M[c][c];
      for (let j = c; j <= n; j++) M[r][j] -= k * M[c][j];
    }
  }
  const x = new Array(n).fill(0);
  for (let r = n - 1; r >= 0; r--) {
    let s = M[r][n];
    for (let j = r + 1; j < n; j++) s -= M[r][j] * x[j];
    x[r] = s / M[r][r];
  }
  return x;
}

function normalizer(pts) {
  // Hartley normalization: centroid at 0, mean distance sqrt(2)
  const n = pts.length;
  const mx = pts.reduce((s, p) => s + p[0], 0) / n, my = pts.reduce((s, p) => s + p[1], 0) / n;
  const d = pts.reduce((s, p) => s + Math.hypot(p[0] - mx, p[1] - my), 0) / n || 1;
  const k = Math.SQRT2 / d;
  return { apply: (p) => [(p[0] - mx) * k, (p[1] - my) * k], T: [[k, 0, -k * mx], [0, k, -k * my], [0, 0, 1]] };
}

const mul3 = (A, B) => A.map((row) => [0, 1, 2].map((j) => row[0] * B[0][j] + row[1] * B[1][j] + row[2] * B[2][j]));
const inv3 = (m) => {
  const [a, b, c] = m[0], [d, e, f] = m[1], [g, h, i] = m[2];
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (Math.abs(det) < 1e-15) return null;
  return [[A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
          [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
          [C / det, -(a * h - b * g) / det, (a * e - b * d) / det]];
};

/** Homography (3x3) taking the plane's points `world` ([x, y]) to the image points `image` ([u, v]); at least 4. */
export function homography(world, image) {
  if (world.length < 4 || world.length !== image.length) return null;
  const nw = normalizer(world), ni = normalizer(image);
  const W = world.map(nw.apply), I = image.map(ni.apply);
  // h33 = 1: 8 unknowns, least squares by the normal equations
  const AtA = Array.from({ length: 8 }, () => new Array(8).fill(0)), Atb = new Array(8).fill(0);
  const add = (row, v) => {
    for (let r = 0; r < 8; r++) {
      Atb[r] += row[r] * v;
      for (let c = 0; c < 8; c++) AtA[r][c] += row[r] * row[c];
    }
  };
  W.forEach(([x, y], k) => {
    const [u, v] = I[k];
    add([x, y, 1, 0, 0, 0, -u * x, -u * y], u);
    add([0, 0, 0, x, y, 1, -v * x, -v * y], v);
  });
  const h = solve(AtA, Atb);
  if (!h) return null;
  const Hn = [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1]];
  const TiInv = inv3(ni.T);
  if (!TiInv) return null;
  return mul3(mul3(TiInv, Hn), nw.T);   // de-normalized
}

export function project(H, [x, y]) {
  const w = H[2][0] * x + H[2][1] * y + H[2][2];
  return [(H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w];
}

const norm = (v) => Math.hypot(v[0], v[1], v[2]);
const scale = (v, k) => [v[0] * k, v[1] * k, v[2] * k];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

/** The label's pose in front of the camera (camera axes: x right, y down, z forward), from the homography and the
    camera's focal length in pixels (f) and center (cx, cy). -> {r1, r2, r3, t} (columns of the rotation, translation
    in the same unit as the label's points) or null. */
export function poseFromHomography(H, f, cx, cy) {
  const col = (j) => [H[0][j], H[1][j], H[2][j]];
  const kinv = ([u, v, w]) => [(u - cx * w) / f, (v - cy * w) / f, w];
  const a1 = kinv(col(0)), a2 = kinv(col(1)), a3 = kinv(col(2));
  let lam = 2 / (norm(a1) + norm(a2));
  if (!Number.isFinite(lam) || lam === 0) return null;
  if (a3[2] * lam < 0) lam = -lam;          // the label is in front of the camera
  let r1 = scale(a1, lam), r2 = scale(a2, lam);
  const t = scale(a3, lam);
  // the nearest rotation (Gram-Schmidt: r1, then r2 made perpendicular, r3 = r1 x r2)
  r1 = scale(r1, 1 / norm(r1));
  r2 = r2.map((x, i) => x - dot(r1, r2) * r1[i]);
  r2 = scale(r2, 1 / norm(r2));
  const r3 = cross(r1, r2);
  return { r1, r2, r3, t };
}

/** The camera's focal length in pixels for a frame w x h: phones' main camera, about 69° on the long side. */
export function focalPx(w, h, longSideFovDeg = 69) {
  return Math.max(w, h) / (2 * Math.tan((longSideFovDeg * Math.PI) / 360));
}

/** Average distance (px) between the image points and the label's points projected with the homography. */
export function reprojectionError(H, world, image) {
  if (!world.length) return Infinity;
  return world.reduce((s, p, k) => { const q = project(H, p); return s + Math.hypot(q[0] - image[k][0], q[1] - image[k][1]); }, 0) / world.length;
}

/** The 4x4 matrix (column-major, for three.js) placing an object on the label. The object's axes on the label:
    x to the right, y up along the label, z out of the label towards who looks at it. three.js' camera looks
    down -z with y up: the camera axes are flipped on y and z. */
export function labelMatrix({ r1, r2, r3, t }) {
  const C = (v) => [v[0], -v[1], -v[2]];
  const c1 = C(r1), c2 = C(scale(r2, -1)), c3 = C(scale(r3, -1)), tt = C(t);
  return [c1[0], c1[1], c1[2], 0, c2[0], c2[1], c2[2], 0, c3[0], c3[1], c3[2], 0, tt[0], tt[1], tt[2], 1];
}

// ---------------------------------------------------------------- the label's geometry (cm, center = 0, y down)
/** The QR's own corners (without its white margin) on a label printed `printedCm` wide, for a QR of `modules` modules:
    the image printed has a margin of 2 modules on each side. Order: top-left, top-right, bottom-right, bottom-left. */
export function qrCorners(printedCm, modules) {
  const s = (printedCm * modules) / (modules + 4);
  const h = s / 2;
  return [[-h, -h], [h, -h], [h, h], [-h, h]];
}

/* The AR label (mode "frame"), side S: the QR in the middle (from 22% to 78%, with its margin), four ArUco markers
   in the corners (20% of the side, ids 0 1 2 3 clockwise from the top left), the name above and the code below. */
export const FRAME = { qrFrom: 0.22, qrTo: 0.78, marker: 0.2, markerAt: [[0.01, 0.01], [0.79, 0.01], [0.79, 0.79], [0.01, 0.79]] };

/** A marker's 4 corners (its black square, clockwise from its top left) on the frame label of side S. The marker
    image (js-aruco2's SVG) is 10 units with the black square from 1 to 9. */
export function markerCorners(id, S) {
  const [mx, my] = FRAME.markerAt[id];
  const m = FRAME.marker * S, x0 = mx * S + 0.1 * m - S / 2, y0 = my * S + 0.1 * m - S / 2, k = 0.8 * m;
  return [[x0, y0], [x0 + k, y0], [x0 + k, y0 + k], [x0, y0 + k]];
}

/** The QR's corners on the frame label of side S. */
export function frameQrCorners(S, modules) {
  return qrCorners((FRAME.qrTo - FRAME.qrFrom) * S, modules);
}
