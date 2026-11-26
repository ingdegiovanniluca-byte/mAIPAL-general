// The augmented reality's math (arPose.js): from where the label's points fall in the image back to where the label
// is (position, tilt), on poses made up here and projected like a phone camera would.
import { homography, poseFromHomography, focalPx, reprojectionError, labelMatrix, qrCorners, markerCorners, frameQrCorners, project } from "./arPose";

const rot = (ax, ay, az) => {
  const [c1, s1, c2, s2, c3, s3] = [Math.cos(ax), Math.sin(ax), Math.cos(ay), Math.sin(ay), Math.cos(az), Math.sin(az)];
  const m = (A, B) => A.map((r) => [0, 1, 2].map((j) => r[0] * B[0][j] + r[1] * B[1][j] + r[2] * B[2][j]));
  return m([[c3, -s3, 0], [s3, c3, 0], [0, 0, 1]], m([[c2, 0, s2], [0, 1, 0], [-s2, 0, c2]], [[1, 0, 0], [0, c1, -s1], [0, s1, c1]]));
};
const W = 1280, H = 720, f = focalPx(W, H), cx = W / 2, cy = H / 2;
const shoot = (R, t, world) => world.map(([x, y]) => {
  const X = R[0][0] * x + R[0][1] * y + t[0], Y = R[1][0] * x + R[1][1] * y + t[1], Z = R[2][0] * x + R[2][1] * y + t[2];
  return [(f * X) / Z + cx, (f * Y) / Z + cy];
});

test("the AR label's points give back its pose (position within 1%, tilt within 1°)", () => {
  const world = [0, 1, 2, 3].flatMap((id) => markerCorners(id, 10)).concat(frameQrCorners(10, 33));
  for (const [ax, ay, az, t] of [[0, 0, 0, [0, 0, 30]], [0.4, -0.3, 0.5, [2, -1, 45]], [-0.5, 0.4, 2.5, [-3, 2, 80]], [0.3, 0.6, -3, [5, 4, 60]]]) {
    const R = rot(ax, ay, az);
    const img = shoot(R, t, world);
    const Hm = homography(world, img);
    expect(reprojectionError(Hm, world, img)).toBeLessThan(0.01);
    const p = poseFromHomography(Hm, f, cx, cy);
    expect(Math.hypot(p.t[0] - t[0], p.t[1] - t[1], p.t[2] - t[2]) / t[2]).toBeLessThan(0.01);
    const cos = p.r3[0] * R[0][2] + p.r3[1] * R[1][2] + p.r3[2] * R[2][2];
    expect(Math.acos(Math.min(1, cos)) * (180 / Math.PI)).toBeLessThan(1);
  }
});

test("the QR alone (4 corners) is enough", () => {
  const world = qrCorners(5, 29), R = rot(0.3, -0.2, 1), t = [1, -1, 25];
  const p = poseFromHomography(homography(world, shoot(R, t, world)), f, cx, cy);
  expect(Math.abs(p.t[2] - 25)).toBeLessThan(0.1);
});

test("the object's matrix puts the label's center where the camera sees it", () => {
  const world = qrCorners(5, 29), R = rot(0.2, 0.3, 0.4), t = [3, -2, 40];
  const Hm = homography(world, shoot(R, t, world));
  const m = labelMatrix(poseFromHomography(Hm, f, cx, cy));
  // the center (0,0,0) of the object -> camera space (three.js: y up, looking down -z) -> pixel
  const [x, y, z] = [m[12], m[13], m[14]];
  expect(z).toBeLessThan(0);
  const u = (f * x) / -z + cx, v = (-f * y) / -z + cy;
  const [eu, ev] = project(Hm, [0, 0]);
  expect(Math.hypot(u - eu, v - ev)).toBeLessThan(0.01);
});

test("the AR label's layout: 4 markers in the corners, the QR in the middle", () => {
  const m0 = markerCorners(0, 10), m2 = markerCorners(2, 10);
  expect(m0[0][0]).toBeCloseTo(-4.7, 5);                  // 0.01*10 + 0.1*2 - 5 (the black square, inside its white margin)
  expect(m2[2][0]).toBeCloseTo(4.7, 5);
  const q = frameQrCorners(10, 33);
  expect(q[1][0] - q[0][0]).toBeCloseTo((5.6 * 33) / 37, 5);   // the QR's own size, without its margin
});
