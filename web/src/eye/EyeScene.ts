// "Ogle", the Eye. Original mascot, drawn entirely in code (no external assets).
// Flat, high-contrast cartoon eyeball: white ball, orange lids, black outlines, floating brow.
//
// Public API (all smoothed internally, safe to call every frame):
//   setLook(x, y)     -1..1, where the Eye looks (face position, pointer...)
//   setSuspicion(s)   0..1, dilates the pupil and lowers the brow
//   setMood(m)        idle | thinking | squint | busted | dizzy | smug
//   blink()

import {
  Color3,
  Color4,
  Effect,
  Engine,
  FreeCamera,
  Mesh,
  MeshBuilder,
  Scene,
  ShaderMaterial,
  StandardMaterial,
  TransformNode,
  Vector3,
} from '@babylonjs/core';

export type Mood = 'idle' | 'thinking' | 'squint' | 'busted' | 'dizzy' | 'smug';

export const PALETTE = {
  orange: '#ff7a00',
  yellow: '#ffd23f',
  black: '#111111',
  white: '#ffffff',
};
const c3 = (hex: string) => Color3.FromHexString(hex);

Effect.ShadersStore['ogleVertexShader'] = /* glsl */ `
precision highp float;
attribute vec3 position;
attribute vec3 normal;
uniform mat4 worldViewProjection;
uniform mat4 worldView;
varying vec3 vN;
varying vec3 vVN;
void main() {
  vN = normal;
  vVN = normalize(mat3(worldView) * normal);
  gl_Position = worldViewProjection * vec4(position, 1.0);
}`;

Effect.ShadersStore['ogleFragmentShader'] = /* glsl */ `
precision highp float;
varying vec3 vN;
varying vec3 vVN;
uniform float pupil;   // 0..1 dilation
uniform float dizzy;   // 0..1 spiral blend
uniform float time;
uniform vec3 cWhite;
uniform vec3 cShade;
uniform vec3 cIris;
uniform vec3 cIris2;
uniform vec3 cBlack;

const float PI = 3.14159265;

void main() {
  vec3 n = normalize(vN);
  float r = acos(clamp(-n.z, -1.0, 1.0));   // angle from the eye's forward axis (-z)
  float a = atan(n.y, n.x);

  // flat two-band toon shading on the eyeball white, light from upper-left in view space
  vec3 vn = normalize(vVN);
  float lit = dot(vn, normalize(vec3(-0.5, 0.6, -0.6)));
  vec3 col = lit > -0.15 ? cWhite : cShade;

  float irisR = 0.50;
  float pupilR = mix(0.13, 0.33, clamp(pupil, 0.0, 1.0));

  if (r < irisR + 0.045) col = cBlack;                 // chunky iris outline
  if (r < irisR) {
    float spokes = step(0.5, fract(a * 14.0 / (2.0 * PI)));
    vec3 iris = mix(cIris, cIris2, spokes * smoothstep(pupilR, irisR, r) * 0.9);
    if (r > irisR - 0.07) iris = cIris2;               // inner ring
    col = iris;
  }
  if (r < pupilR) col = cBlack;

  // dizzy: a spinning spiral takes over the iris
  if (dizzy > 0.001 && r < irisR) {
    float s = fract(a / (2.0 * PI) + r * 5.0 - time * 1.6);
    vec3 spiral = s < 0.5 ? cBlack : cIris2;
    col = mix(col, spiral, dizzy);
  }

  // glints are fixed in view space so they stay put as the eye rolls
  float g1 = length(vn.xy - vec2(-0.30, 0.36));
  float g2 = length(vn.xy - vec2(-0.12, 0.20));
  if (vn.z < 0.0 && (g1 < 0.11 || g2 < 0.045)) col = cWhite;

  gl_FragColor = vec4(col, 1.0);
}`;

// Lid angle a puts the lid's edge at screen height ~sin(a) * radius (iris edge is ~0.48).
const LIDS: Record<Mood, { upper: number; lower: number; browY: number; browTilt: number }> = {
  idle: { upper: 0.78, lower: 1.0, browY: 1.4, browTilt: 0 },
  thinking: { upper: 0.62, lower: 0.92, browY: 1.32, browTilt: 0.12 },
  squint: { upper: 0.36, lower: 0.5, browY: 1.1, browTilt: 0.22 },
  busted: { upper: 0.3, lower: 0.42, browY: 1.02, browTilt: 0.3 },
  dizzy: { upper: 0.95, lower: 1.15, browY: 1.55, browTilt: -0.15 },
  smug: { upper: 0.42, lower: 0.75, browY: 1.38, browTilt: -0.2 },
};

const damp = (cur: number, target: number, rate: number, dt: number) =>
  cur + (target - cur) * (1 - Math.exp(-rate * dt));

export class EyeScene {
  private engine: Engine;
  private scene: Scene;
  private camera: FreeCamera;
  private rig: TransformNode;
  private ball: Mesh;
  private ballMat: ShaderMaterial;
  private upperLid: Mesh;
  private lowerLid: Mesh;
  private brow: Mesh;
  private shadow: Mesh;

  private target = { x: 0, y: 0, suspicion: 0 };
  private cur = { x: 0, y: 0, suspicion: 0, upper: 0.78, lower: 1.0, browY: 1.4, browTilt: 0, dizzy: 0, zoom: 0, spin: 0 };
  private mood: Mood = 'idle';
  private t = 0;
  private blinkUntil = 0;
  private nextBlink = 2.5;
  private shake = 0;

  constructor(canvas: HTMLCanvasElement) {
    this.engine = new Engine(canvas, true, { preserveDrawingBuffer: true, stencil: true }, true);
    const scene = (this.scene = new Scene(this.engine));
    scene.clearColor = Color4.FromHexString(PALETTE.yellow + 'ff');

    this.camera = new FreeCamera('cam', new Vector3(0, 0.1, -6.2), scene);
    this.camera.setTarget(new Vector3(0, 0.1, 0));
    this.camera.fov = 0.75;

    const flat = (name: string, hex: string) => {
      const m = new StandardMaterial(name, scene);
      m.disableLighting = true;
      m.emissiveColor = c3(hex);
      return m;
    };

    this.rig = new TransformNode('rig', scene);

    // ground shadow: a flat ellipse, shrinks as Ogle bobs up
    this.shadow = MeshBuilder.CreateDisc('shadow', { radius: 1, tessellation: 48 }, scene);
    const shMat = flat('shadowMat', PALETTE.black);
    shMat.alpha = 0.16;
    this.shadow.material = shMat;
    this.shadow.position.set(0, -1.75, 0.6);
    this.shadow.scaling.set(1.15, 0.16, 1);

    // eyeball
    this.ball = MeshBuilder.CreateSphere('ball', { diameter: 2, segments: 64 }, scene);
    this.ball.parent = this.rig;
    this.ballMat = new ShaderMaterial('ogle', scene, { vertex: 'ogle', fragment: 'ogle' }, {
      attributes: ['position', 'normal'],
      uniforms: ['worldViewProjection', 'worldView', 'pupil', 'dizzy', 'time', 'cWhite', 'cShade', 'cIris', 'cIris2', 'cBlack'],
    });
    this.ballMat.setColor3('cWhite', c3(PALETTE.white));
    this.ballMat.setColor3('cShade', c3('#ffe9c7'));
    this.ballMat.setColor3('cIris', c3(PALETTE.orange));
    this.ballMat.setColor3('cIris2', c3(PALETTE.yellow));
    this.ballMat.setColor3('cBlack', c3(PALETTE.black));
    this.ball.material = this.ballMat;

    // outline: inverted hull (a bigger black sphere showing only its back faces). Babylon's
    // renderOutline paints over the lids, and the hull also outlines the lids' silhouette.
    const hull = MeshBuilder.CreateSphere('hull', { diameter: 2.28, segments: 48, sideOrientation: Mesh.BACKSIDE }, scene);
    hull.material = flat('hullMat', PALETTE.black);
    hull.parent = this.rig;

    // lids: hemispheres slightly larger than the ball, hinged at its center.
    // rotation.x = 0 covers its half of the eye (closed); positive rotates back (open).
    const lidMat = flat('lidMat', PALETTE.orange);
    lidMat.backFaceCulling = false;
    const rimMat = flat('rimMat', PALETTE.black);
    const mkLid = (name: string, flip: boolean) => {
      const hinge = new TransformNode(name + 'Hinge', scene);
      hinge.parent = this.rig;
      if (flip) hinge.rotation.z = Math.PI;
      const lid = MeshBuilder.CreateSphere(name, { diameter: 2.12, segments: 48, slice: 0.5 }, scene);
      lid.parent = hinge;
      lid.material = lidMat;
      // The outline renderer floods double-sided meshes, so draw the lid's edge as a torus in the
      // rim plane (XZ, y=0). The lid's silhouette is already covered by the ball's outline.
      const rim = MeshBuilder.CreateTorus(name + 'Rim', { diameter: 2.12, thickness: 0.1, tessellation: 64 }, scene);
      rim.parent = lid;
      rim.material = rimMat;
      return lid;
    };
    this.upperLid = mkLid('upperLid', false);
    this.lowerLid = mkLid('lowerLid', true);

    // brow: a chunky floating bar that carries most of the expression
    this.brow = MeshBuilder.CreateCapsule('brow', { radius: 0.13, height: 1.5, tessellation: 24 }, scene);
    this.brow.material = flat('browMat', PALETTE.black);
    this.brow.parent = this.rig;
    this.brow.rotation.z = Math.PI / 2;
    this.brow.position.set(0, 1.4, -0.7);

    scene.onBeforeRenderObservable.add(() => this.tick(this.engine.getDeltaTime() / 1000));
    this.engine.runRenderLoop(() => scene.render());
    window.addEventListener('resize', this.onResize);
  }

  private onResize = () => this.engine.resize();

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
  getMood() {
    return this.mood;
  }
  blink() {
    this.blinkUntil = this.t + 0.13;
  }

  private tick(dt: number) {
    dt = Math.min(dt, 0.05);
    this.t += dt;
    const { cur, target, mood } = this;
    const lids = LIDS[mood];

    // where to look: thinking scans the room, dizzy rolls in circles, otherwise follow target
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
      ly = 0; // dead stare at the player
    }
    cur.x = damp(cur.x, lx, mood === 'thinking' ? 6 : 10, dt);
    cur.y = damp(cur.y, ly, 10, dt);
    cur.suspicion = damp(cur.suspicion, mood === 'dizzy' ? 0.1 : mood === 'busted' ? 1 : target.suspicion, 4, dt);

    // blinks (not while busted: no blinking during the stare-down)
    if (mood !== 'busted' && this.t > this.nextBlink) {
      this.blink();
      this.nextBlink = this.t + 2 + Math.random() * 3.5;
    }
    const blinking = this.t < this.blinkUntil;
    // suspicion narrows the lids a little on its own
    const narrow = cur.suspicion * 0.18;
    cur.upper = damp(cur.upper, blinking ? 0.02 : lids.upper - narrow, blinking ? 40 : 12, dt);
    cur.lower = damp(cur.lower, blinking ? 0.02 : lids.lower - narrow * 0.6, blinking ? 40 : 12, dt);
    cur.browY = damp(cur.browY, lids.browY - cur.suspicion * 0.12, 8, dt);
    cur.browTilt = damp(cur.browTilt, lids.browTilt + cur.suspicion * 0.1, 8, dt);
    cur.dizzy = damp(cur.dizzy, mood === 'dizzy' ? 1 : 0, 5, dt);
    cur.zoom = damp(cur.zoom, mood === 'busted' ? 1 : mood === 'squint' ? 0.35 : 0, mood === 'busted' ? 9 : 3, dt);

    this.ball.rotation.y = -cur.x * 0.55;
    this.ball.rotation.x = cur.y * 0.42;
    this.upperLid.rotation.x = cur.upper;
    this.lowerLid.rotation.x = cur.lower;

    // brow follows the gaze a touch, tilts with mood
    this.brow.position.y = cur.browY + Math.sin(this.t * 2.2) * 0.02;
    this.brow.position.x = cur.x * 0.12;
    this.brow.rotation.z = Math.PI / 2 + cur.browTilt + (mood === 'dizzy' ? Math.sin(this.t * 5) * 0.25 : 0);

    // body: idle bob, dizzy wobble, busted shake
    const bob = Math.sin(this.t * 1.8) * 0.08 * (1 - cur.zoom);
    this.shake = damp(this.shake, 0, 5, dt);
    const sh = this.shake * 0.12;
    this.rig.position.set((Math.random() - 0.5) * sh, bob + (Math.random() - 0.5) * sh, 0);
    cur.spin = mood === 'dizzy' ? cur.spin + dt * 3 : damp(cur.spin, Math.round(cur.spin / (2 * Math.PI)) * 2 * Math.PI, 4, dt);
    this.rig.rotation.z = Math.sin(cur.spin) * 0.35 * cur.dizzy;

    this.shadow.scaling.x = 1.15 - bob * 0.8;
    this.shadow.visibility = 1 - cur.zoom;

    this.camera.position.z = -6.2 + cur.zoom * 3.1;

    this.ballMat.setFloat('pupil', cur.suspicion);
    this.ballMat.setFloat('dizzy', cur.dizzy);
    this.ballMat.setFloat('time', this.t);
  }

  dispose() {
    window.removeEventListener('resize', this.onResize);
    this.engine.stopRenderLoop();
    this.scene.dispose();
    this.engine.dispose();
  }
}
