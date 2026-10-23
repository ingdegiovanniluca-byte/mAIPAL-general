/* What each agent does with its eyes and body, by role and state (the prototype's roleMods):
   where it looks, how open its eyes are, hops and squashes, and how its surface moves.
   `mem` keeps the little bit of memory some roles need (when Cerca last "found" something). */

export function newMemory() {
  return { foundAt: -10, nextFound: 3 };
}

export function roleMods(beh, st, ts, mem) {
  const m = { amp: 1, speed: 1, freq: 1, bump: 0, look: null, eyeH: null, blink: null, lookSpeed: null, eyeSpeed: null, hop: 0, squash: 1 };
  const work = st === "think", idle = st === "idle";
  if (beh === "search") {
    m.freq = 1.1; m.speed = 1.15;
    if (work) {
      // reads line by line, then "finds" something and opens its eyes wide
      if (ts > mem.nextFound) { mem.foundAt = ts; mem.nextFound = ts + 2.4 + Math.random() * 2; }
      const f = ts - mem.foundAt;
      if (f < .7) { m.eyeH = 1.35; m.look = { x: 0, y: .1 }; m.bump = .03 * Math.max(0, 1 - f / .7); m.eyeSpeed = 14; }
      else { m.look = { x: Math.sin(ts * 2.6) * .95, y: .15 + .25 * Math.sin(ts * .55) }; m.eyeH = 1.05; m.lookSpeed = 8; }
    } else if (idle) { m.look = { x: Math.sin(ts * .9) * .8, y: Math.sin(ts * .37) * .4 }; m.lookSpeed = 4; }
  } else if (beh === "report") {
    m.amp = .55; m.speed = .75; m.freq = .85;
    if (work) {
      // scans a table: left to right, row after row
      const t = ts * .9, line = Math.floor(t) % 3, x = t % 1;
      m.look = { x: -.9 + 1.8 * Math.min(x / .85, 1), y: .45 - .45 * line }; m.lookSpeed = x > .85 ? 18 : 9; m.eyeH = .9;
    } else if (idle) { m.look = { x: 0, y: 0 }; m.eyeH = .95; }
  } else if (beh === "diary") {
    m.speed = .6; m.amp = 1.1;
    if (work) {
      // looks down and writes slowly, now and then closes its eyes to remember
      const cyc = ts % 6;
      if (cyc > 4.6) { m.blink = .05; m.look = { x: 0, y: .2 }; }
      else { m.look = { x: Math.sin(ts * 1.1) * .4, y: -.75 }; m.eyeH = .9; }
      m.lookSpeed = 3; m.eyeSpeed = 3;
    } else if (idle) { m.look = { x: Math.sin(ts * .4) * .3, y: -.35 }; m.lookSpeed = 2.5; }
  } else if (beh === "save") {
    m.speed = .8;
    if (work) {
      // takes something from above, swallows it squashing with closed eyes, bounces back pleased
      const c = (ts % 2.6) / 2.6;
      if (c < .3) { m.look = { x: 0, y: .9 }; m.eyeH = 1.25; m.squash = 1 + .05 * Math.sin(c / .3 * Math.PI); m.lookSpeed = 8; }
      else if (c < .5) { const t = (c - .3) / .2; m.squash = 1 - .15 * Math.sin(t * Math.PI); m.blink = .06; m.hop = -.04 * Math.sin(t * Math.PI); m.bump = .02 * Math.sin(t * Math.PI); }
      else if (c < .68) { const t = (c - .5) / .18; m.squash = 1 + .07 * Math.sin(t * Math.PI); m.hop = .05 * Math.sin(t * Math.PI); m.look = { x: 0, y: 0 }; }
      else { m.look = { x: Math.sin(ts * .8) * .2, y: -.1 }; m.eyeH = .95; }
    } else if (idle) { m.look = { x: Math.sin(ts * .5) * .4, y: .2 }; m.lookSpeed = 3; }
  } else if (beh === "task") {
    if (work) {
      // runs down a list and gives a little tick-nod at each item
      const per = .75, n = 4, cyc = ts % (per * (n + 1.2)), item = Math.floor(cyc / per), f = (cyc % per) / per;
      if (item < n) {
        m.look = { x: -.25 + .5 * Math.min(f / .6, 1), y: .65 - item * .42 }; m.lookSpeed = 10;
        if (f > .72) { const t = (f - .72) / .28; m.hop = -.035 * Math.sin(t * Math.PI); m.squash = 1 - .06 * Math.sin(t * Math.PI); m.eyeH = .85; }
      } else { m.look = { x: 0, y: 0 }; m.eyeH = 1.15; const t = (cyc - per * n) / (per * 1.2); m.hop = .06 * Math.sin(Math.min(t * 2, 1) * Math.PI); m.squash = 1 + .05 * Math.sin(Math.min(t * 2, 1) * Math.PI); }
    } else if (idle) { m.look = { x: 0, y: .3 }; }
  } else if (beh === "action") {
    m.speed = 1.35; m.freq = 1.15;
    if (work) {
      // hops, ready to go: stretches in the air, squashes when it lands
      const per = .62, f = (ts % per) / per, air = Math.sin(f * Math.PI);
      m.hop = .14 * air; m.squash = 1 + .08 * air - .13 * Math.max(0, 1 - air * 4.5);
      m.look = { x: Math.sin(ts * 1.3) * .3, y: .1 }; m.eyeH = 1.05; m.lookSpeed = 12;
    } else if (idle) { const f = (ts % 1.4) / 1.4; m.hop = .03 * Math.abs(Math.sin(f * Math.PI * 2)); m.look = { x: Math.sin(ts * 1.5) * .6, y: 0 }; m.lookSpeed = 6; }
  } else { // assistant (Help): thinks looking up and to the side
    if (work) { m.look = { x: .85 + Math.sin(ts * 2.2) * .2, y: .85 }; m.eyeH = .75; }
  }
  return m;
}
