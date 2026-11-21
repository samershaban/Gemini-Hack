// Fallback Ogle drawn in SVG, used when WebGL is unavailable (blocked GPU, embedded browsers,
// hardware acceleration off). Same API and moods as EyeScene, so the stage never notices.

import { PALETTE, type EyeApi, type Mood } from './EyeScene';

const NS = 'http://www.w3.org/2000/svg';
const R = 66; // eyeball radius in viewBox units

// Lid edge heights as a fraction of R (matching the 3D lid angles: sin(angle)).
const LIDS: Record<Mood, { upper: number; lower: number }> = {
  idle: { upper: 0.7, lower: 0.84 },
  thinking: { upper: 0.58, lower: 0.8 },
  squint: { upper: 0.35, lower: 0.48 },
  busted: { upper: 0.3, lower: 0.41 },
  dizzy: { upper: 0.81, lower: 0.91 },
  smug: { upper: 0.41, lower: 0.68 },
};

const damp = (cur: number, target: number, rate: number, dt: number) =>
  cur + (target - cur) * (1 - Math.exp(-rate * dt));

function el<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>, parent?: Element) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  parent?.appendChild(e);
  return e;
}

/** Path of a lid: the part of the ball above an elliptical rim whose front edge sits at height h*R. */
const lidPath = (h: number) => {
  const e = Math.max(0.5, h * R);
  return `M ${-R - 10} ${-R - 10} H ${R + 10} V 0 H ${R} A ${R} ${e} 0 0 0 ${-R} 0 H ${-R - 10} Z`;
};
const rimPath = (h: number) => `M ${R} 0 A ${R} ${Math.max(0.5, h * R)} 0 0 0 ${-R} 0`;

export class FlatEye implements EyeApi {
  private svg: SVGSVGElement;
  private body: SVGGElement;
  private iris: SVGGElement;
  private pupil: SVGCircleElement;
  private spiral: SVGPathElement;
  private upperLid: SVGPathElement;
  private upperRim: SVGPathElement;
  private lowerLid: SVGPathElement;
  private lowerRim: SVGPathElement;
  private shadow: SVGEllipseElement;
  private raf = 0;
  private last = performance.now();

  private target = { x: 0, y: 0, suspicion: 0 };
  private cur = { x: 0, y: 0, suspicion: 0, upper: 0.7, lower: 0.84, dizzy: 0, zoom: 0, spin: 0 };
  private mood: Mood = 'idle';
  private t = 0;
  private blinkUntil = 0;
  private nextBlink = 2.5;
  private shake = 0;

  constructor(container: HTMLElement) {
    const svg = (this.svg = el('svg', { viewBox: '-150 -150 300 300', preserveAspectRatio: 'xMidYMid meet' }));
    svg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block';
    container.appendChild(svg);

    const defs = el('defs', {}, svg);
    const clip = el('clipPath', { id: 'ogle-ball' }, defs);
    el('circle', { r: R }, clip);

    this.shadow = el('ellipse', { cx: 0, cy: 112, rx: 76, ry: 10, fill: PALETTE.black, opacity: 0.16 }, svg);
    this.body = el('g', {}, svg);
    el('circle', { r: R + 7, fill: PALETTE.black }, this.body);
    el('circle', { r: R, fill: PALETTE.white }, this.body);

    const inBall = el('g', { 'clip-path': 'url(#ogle-ball)' }, this.body);
    this.iris = el('g', {}, inBall);
    el('circle', { r: 36, fill: PALETTE.black }, this.iris);
    el('circle', { r: 33, fill: PALETTE.yellow }, this.iris);
    el('circle', { r: 28, fill: PALETTE.orange }, this.iris);
    for (let i = 0; i < 14; i++) {
      const a = (i / 14) * Math.PI * 2;
      el('line', { x1: Math.cos(a) * 14, y1: Math.sin(a) * 14, x2: Math.cos(a) * 27, y2: Math.sin(a) * 27, stroke: PALETTE.yellow, 'stroke-width': 3, opacity: 0.7 }, this.iris);
    }
    this.spiral = el('path', { d: spiralPath(), fill: 'none', stroke: PALETTE.black, 'stroke-width': 5, 'stroke-linecap': 'round', opacity: 0 }, this.iris);
    this.pupil = el('circle', { r: 10, fill: PALETTE.black }, this.iris);
    el('circle', { cx: -20, cy: -24, r: 7, fill: PALETTE.white }, inBall);
    el('circle', { cx: -8, cy: -13, r: 3, fill: PALETTE.white }, inBall);

    const lid = (flip: boolean) => {
      const g = el('g', flip ? { transform: 'scale(1,-1)' } : {}, inBall);
      const path = el('path', { fill: PALETTE.orange }, g);
      const rim = el('path', { fill: 'none', stroke: PALETTE.black, 'stroke-width': 6 }, g);
      return [path, rim] as const;
    };
    [this.upperLid, this.upperRim] = lid(false);
    [this.lowerLid, this.lowerRim] = lid(true);


    this.tick(0); // draw the first frame now: rAF doesn't run in background tabs
    const loop = (now: number) => {
      // rAF timestamps can be earlier than `last` (background tabs): a negative step makes the easing blow up to NaN
      this.tick(Math.max(0, Math.min((now - this.last) / 1000, 0.05)));
      this.last = now;
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  setLook(x: number, y: number) {
    this.target.x = Math.max(-1, Math.min(1, x));
    this.target.y = Math.max(-1, Math.min(1, y));
  }
  setSuspicion(s: number) {
    this.target.suspicion = Math.max(0, Math.min(1, s));
  }
  setMood(m: Mood) {
    if (m === this.mood) return;
    if (m === 'busted') this.shake = 1;
    this.mood = m;
  }
  blink() {
    this.blinkUntil = this.t + 0.13;
  }

  private tick(dt: number) {
    this.t += dt;
    const { cur, target, mood } = this;
    const lids = LIDS[mood];

    let lx = target.x;
    let ly = target.y;
    if (mood === 'thinking') {
      lx = Math.sin(this.t * 1.7) * 0.7;
      ly = Math.sin(this.t * 0.9) * 0.15;
    } else if (mood === 'dizzy') {
      lx = Math.cos(this.t * 6) * 0.6;
      ly = Math.sin(this.t * 6) * 0.45;
    } else if (mood === 'busted') {
      lx = 0;
      ly = 0;
    }
    cur.x = damp(cur.x, lx, mood === 'thinking' ? 6 : 10, dt);
    cur.y = damp(cur.y, ly, 10, dt);
    cur.suspicion = damp(cur.suspicion, mood === 'dizzy' ? 0.1 : mood === 'busted' ? 1 : target.suspicion, 4, dt);

    if (mood !== 'busted' && this.t > this.nextBlink) {
      this.blink();
      this.nextBlink = this.t + 2 + Math.random() * 3.5;
    }
    const blinking = this.t < this.blinkUntil;
    const narrow = cur.suspicion * 0.15;
    cur.upper = damp(cur.upper, blinking ? 0 : lids.upper - narrow, blinking ? 40 : 12, dt);
    cur.lower = damp(cur.lower, blinking ? 0 : lids.lower - narrow * 0.6, blinking ? 40 : 12, dt);
    cur.dizzy = damp(cur.dizzy, mood === 'dizzy' ? 1 : 0, 5, dt);
    cur.zoom = damp(cur.zoom, mood === 'busted' ? 1 : mood === 'squint' ? 0.35 : 0, mood === 'busted' ? 9 : 3, dt);
    cur.spin = mood === 'dizzy' ? cur.spin + dt * 3 : damp(cur.spin, Math.round(cur.spin / (2 * Math.PI)) * 2 * Math.PI, 4, dt);
    this.shake = damp(this.shake, 0, 5, dt);

    this.iris.setAttribute('transform', `translate(${cur.x * 30} ${-cur.y * 24})`);
    this.pupil.setAttribute('r', String(9 + cur.suspicion * 13));
    this.spiral.setAttribute('opacity', String(cur.dizzy));
    this.spiral.setAttribute('transform', `rotate(${(this.t * 300) % 360})`);
    this.upperLid.setAttribute('d', lidPath(cur.upper));
    this.upperRim.setAttribute('d', rimPath(cur.upper));
    this.lowerLid.setAttribute('d', lidPath(cur.lower));
    this.lowerRim.setAttribute('d', rimPath(cur.lower));


    const bob = Math.sin(this.t * 1.8) * 5 * (1 - cur.zoom);
    const sh = this.shake * 8;
    const scale = 1 + cur.zoom * 1.0;
    const rot = Math.sin(cur.spin) * 0.35 * cur.dizzy * (180 / Math.PI);
    this.body.setAttribute(
      'transform',
      `translate(${(Math.random() - 0.5) * sh} ${-bob + (Math.random() - 0.5) * sh}) scale(${scale}) rotate(${rot})`,
    );
    this.shadow.setAttribute('rx', String(76 + bob * 0.8));
    this.shadow.setAttribute('opacity', String(0.16 * (1 - cur.zoom)));
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.svg.remove();
  }
}

function spiralPath() {
  let d = '';
  for (let i = 0; i <= 80; i++) {
    const a = (i / 80) * Math.PI * 6;
    const r = 2 + (i / 80) * 26;
    d += `${i ? 'L' : 'M'} ${(Math.cos(a) * r).toFixed(1)} ${(Math.sin(a) * r).toFixed(1)} `;
  }
  return d;
}
