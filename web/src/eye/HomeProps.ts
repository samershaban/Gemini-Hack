// Start-page props around Ogle, drawn entirely in code (no image files), in the same flat,
// thick-outline orange / yellow / black style:
//   - a slowly turning game-show sunburst behind everything
//   - three floating playing cards that flip to show TRUTH, TRUTH, LIE
//   - poker chips drifting up through the background
//   - twinkling sparkles
// Everything pops in once (staggered) and respects prefers-reduced-motion.

import {
  Color3,
  DynamicTexture,
  Effect,
  Mesh,
  MeshBuilder,
  Scene,
  ShaderMaterial,
  StandardMaterial,
  TransformNode,
  Vector4,
  type Observer,
} from '@babylonjs/core';
import { PALETTE } from './EyeScene';

const CHIP_COUNT = 9;
const SPARKLE_COUNT = 10;
const CARD_WORDS = ['TRUTH', 'LIE', 'TRUTH'];
const FONT = "'Fredoka', ui-rounded, system-ui, sans-serif";

Effect.ShadersStore['sunburstVertexShader'] = /* glsl */ `
precision highp float;
attribute vec3 position;
uniform mat4 worldViewProjection;
varying vec2 vPos;
void main() {
  vPos = position.xy;
  gl_Position = worldViewProjection * vec4(position, 1.0);
}`;

Effect.ShadersStore['sunburstFragmentShader'] = /* glsl */ `
precision highp float;
varying vec2 vPos;
uniform float time;
uniform vec3 cBase;
uniform vec3 cRay;
const float PI = 3.14159265;
void main() {
  float angle = atan(vPos.y, vPos.x) + time * 0.06;
  float ray = step(0.5, fract(angle * 18.0 / (2.0 * PI)));
  // rays fade out toward the centre so Ogle sits on a clean spot
  float fade = smoothstep(1.2, 4.5, length(vPos));
  gl_FragColor = vec4(mix(cBase, cRay, ray * fade), 1.0);
}`;

const damp = (cur: number, target: number, rate: number, dt: number) =>
  cur + (target - cur) * (1 - Math.exp(-rate * dt));

/** 0 -> 1 with a springy overshoot, for the pop-in. */
const popIn = (x: number) => {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  return 1 + Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * ((2 * Math.PI) / 3));
};

function flatMaterial(scene: Scene, name: string, texture: DynamicTexture) {
  const material = new StandardMaterial(name, scene);
  material.disableLighting = true;
  material.emissiveTexture = texture;
  material.opacityTexture = texture; // rounded corners and star points come from the alpha
  material.backFaceCulling = true;
  return material;
}

function roundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Card face: white with a big word, or the orange back with a question mark. */
function drawCard(texture: DynamicTexture, word: string | null) {
  const ctx = texture.getContext() as unknown as CanvasRenderingContext2D;
  const { width, height } = texture.getSize();
  ctx.clearRect(0, 0, width, height);
  // hard offset shadow, like the buttons
  roundedRect(ctx, 22, 22, width - 34, height - 34, 34);
  ctx.fillStyle = PALETTE.black;
  ctx.fill();
  roundedRect(ctx, 10, 10, width - 34, height - 34, 34);
  ctx.fillStyle = word ? PALETTE.white : PALETTE.orange;
  ctx.fill();
  ctx.lineWidth = 14;
  ctx.strokeStyle = PALETTE.black;
  ctx.stroke();
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const centerX = (width - 24) / 2 + 10;
  const centerY = (height - 24) / 2 + 10;
  if (word) {
    const isLie = word === 'LIE';
    ctx.font = `700 ${isLie ? 112 : 62}px ${FONT}`;
    ctx.lineWidth = 12;
    ctx.strokeStyle = PALETTE.black;
    ctx.strokeText(word, centerX, centerY);
    ctx.fillStyle = isLie ? PALETTE.orange : PALETTE.yellow;
    ctx.fillText(word, centerX, centerY);
    // little corner pips
    ctx.font = `700 40px ${FONT}`;
    ctx.fillStyle = PALETTE.black;
    ctx.fillText(isLie ? '✕' : '✓', 58, 62);
    ctx.fillText(isLie ? '✕' : '✓', width - 82, height - 86);
  } else {
    ctx.font = `700 190px ${FONT}`;
    ctx.lineWidth = 14;
    ctx.strokeStyle = PALETTE.black;
    ctx.strokeText('?', centerX, centerY + 6);
    ctx.fillStyle = PALETTE.yellow;
    ctx.fillText('?', centerX, centerY + 6);
  }
  texture.update();
}

/** Chip texture: left half is the round face, right half is the striped edge. */
function drawChip(texture: DynamicTexture, mainColor: string, dashColor: string) {
  const ctx = texture.getContext() as unknown as CanvasRenderingContext2D;
  const size = texture.getSize().height;
  const radius = size / 2;
  ctx.fillStyle = PALETTE.black;
  ctx.fillRect(0, 0, size * 2, size);
  // face
  ctx.beginPath();
  ctx.arc(radius, radius, radius - 10, 0, Math.PI * 2);
  ctx.fillStyle = mainColor;
  ctx.fill();
  ctx.lineWidth = 22;
  ctx.strokeStyle = dashColor;
  ctx.setLineDash([28, 26]);
  ctx.beginPath();
  ctx.arc(radius, radius, radius - 34, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.lineWidth = 8;
  ctx.strokeStyle = PALETTE.black;
  ctx.beginPath();
  ctx.arc(radius, radius, radius - 58, 0, Math.PI * 2);
  ctx.stroke();
  // edge stripes
  for (let i = 0; i < 12; i++) {
    ctx.fillStyle = i % 2 === 0 ? mainColor : dashColor;
    ctx.fillRect(size + (i * size) / 12, 10, size / 12, size - 20);
  }
  texture.update();
}

function drawSparkle(texture: DynamicTexture) {
  const ctx = texture.getContext() as unknown as CanvasRenderingContext2D;
  const size = texture.getSize().width;
  const c = size / 2;
  ctx.clearRect(0, 0, size, size);
  ctx.beginPath();
  for (let i = 0; i < 8; i++) {
    const r = i % 2 === 0 ? c - 8 : c * 0.28;
    const a = (i * Math.PI) / 4 - Math.PI / 2;
    ctx.lineTo(c + Math.cos(a) * r, c + Math.sin(a) * r);
  }
  ctx.closePath();
  ctx.fillStyle = PALETTE.white;
  ctx.fill();
  ctx.lineWidth = 7;
  ctx.strokeStyle = PALETTE.black;
  ctx.stroke();
  texture.update();
}

interface Card {
  node: TransformNode;
  frontTexture: DynamicTexture;
  backTexture: DynamicTexture;
  word: string;
  showingFront: boolean;
  flip: number; // current rotation toward the target (0 back, PI front)
  phase: number;
  delay: number;
  home: { x: number; y: number };
}

interface Chip {
  mesh: Mesh;
  x: number;
  y: number;
  z: number;
  speed: number;
  spin: number;
  tilt: number;
}

interface Sparkle {
  mesh: Mesh;
  phase: number;
  speed: number;
}

export interface HomeProps {
  dispose(): void;
}

export function addHomeProps(scene: Scene): HomeProps {
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const motion = reducedMotion ? 0.15 : 1;
  const engine = scene.getEngine();
  const camera = scene.activeCamera!;
  const root = new TransformNode('homeProps', scene);

  // ---- sunburst ----
  const sunburst = MeshBuilder.CreateDisc('sunburst', { radius: 30, tessellation: 96 }, scene);
  const sunburstMaterial = new ShaderMaterial('sunburst', scene, { vertex: 'sunburst', fragment: 'sunburst' }, {
    attributes: ['position'],
    uniforms: ['worldViewProjection', 'time', 'cBase', 'cRay'],
  });
  sunburstMaterial.setColor3('cBase', Color3.FromHexString(PALETTE.yellow));
  sunburstMaterial.setColor3('cRay', Color3.FromHexString('#ffe27a'));
  sunburst.material = sunburstMaterial;
  sunburst.position.z = 9;
  sunburst.parent = root;

  // ---- cards ----
  const cards: Card[] = CARD_WORDS.map((word, i) => {
    const node = new TransformNode(`card${i}`, scene);
    node.parent = root;
    const make = (name: string, rotated: boolean) => {
      const texture = new DynamicTexture(name, { width: 300, height: 420 }, scene, true);
      texture.hasAlpha = true;
      const plane = MeshBuilder.CreatePlane(name, { width: 1.0, height: 1.4 }, scene);
      plane.material = flatMaterial(scene, name + 'Mat', texture);
      plane.parent = node;
      if (rotated) plane.rotation.y = Math.PI; // the face that shows after a half turn
      return texture;
    };
    const backTexture = make(`card${i}Back`, false);
    const frontTexture = make(`card${i}Front`, true);
    drawCard(backTexture, null);
    drawCard(frontTexture, word);
    node.scaling.setAll(0);
    return { node, frontTexture, backTexture, word, showingFront: false, flip: 0, phase: i * 2.1, delay: 0.55 + i * 0.18, home: { x: 0, y: 0 } };
  });

  // card text uses Fredoka: redraw once the font has loaded
  document.fonts?.load(`700 74px ${FONT}`).then(() => {
    for (const card of cards) {
      drawCard(card.backTexture, null);
      drawCard(card.frontTexture, card.word);
    }
  });

  // ---- chips ----
  const chipColors: [string, string][] = [
    [PALETTE.orange, PALETTE.white],
    [PALETTE.black, PALETTE.yellow],
    [PALETTE.white, PALETTE.orange],
  ];
  const chipMaterials = chipColors.map(([main, dash], i) => {
    const texture = new DynamicTexture(`chip${i}`, { width: 512, height: 256 }, scene, true);
    drawChip(texture, main, dash);
    const material = new StandardMaterial(`chip${i}Mat`, scene);
    material.disableLighting = true;
    material.emissiveTexture = texture;
    return material;
  });
  const faceUV = [new Vector4(0, 0, 0.5, 1), new Vector4(0.5, 0, 1, 1), new Vector4(0, 0, 0.5, 1)];
  const chips: Chip[] = [];
  for (let i = 0; i < CHIP_COUNT; i++) {
    const mesh = MeshBuilder.CreateCylinder(`chip${i}`, { diameter: 0.62, height: 0.1, tessellation: 40, faceUV }, scene);
    mesh.material = chipMaterials[i % chipMaterials.length];
    mesh.parent = root;
    chips.push({
      mesh,
      x: 0,
      y: -6 + Math.random() * 12,
      z: 2 + Math.random() * 4,
      speed: 0.35 + Math.random() * 0.4,
      spin: (Math.random() - 0.5) * 3,
      tilt: Math.random() * Math.PI,
    });
  }

  // ---- sparkles ----
  const sparkleTexture = new DynamicTexture('sparkle', { width: 128, height: 128 }, scene, true);
  sparkleTexture.hasAlpha = true;
  drawSparkle(sparkleTexture);
  const sparkleMaterial = flatMaterial(scene, 'sparkleMat', sparkleTexture);
  const sparkles: Sparkle[] = [];
  for (let i = 0; i < SPARKLE_COUNT; i++) {
    const mesh = MeshBuilder.CreatePlane(`sparkle${i}`, { size: 0.32 }, scene);
    mesh.material = sparkleMaterial;
    mesh.parent = root;
    sparkles.push({ mesh, phase: Math.random() * 10, speed: 1.5 + Math.random() * 2 });
  }

  // ---- layout: spread props to fit the screen shape ----
  // On tall phone screens the camera backs off so Ogle is about half the screen wide
  // (EyeScene puts it at 6.2, which fills a phone). Recomputed every frame (cheap).
  const viewDistance = () => {
    const aspect = engine.getAspectRatio(camera);
    return Math.max(6.2, 2.1 / (Math.tan(camera.fov / 2) * aspect));
  };
  // visible half-size of the view at depth z
  const halfSizeAt = (z: number) => {
    const halfHeight = Math.tan(camera.fov / 2) * (z + viewDistance());
    return { halfHeight, halfWidth: halfHeight * engine.getAspectRatio(camera) };
  };
  const layout = () => {
    const { halfWidth, halfHeight } = halfSizeAt(0);
    const wide = halfWidth > halfHeight * 1.1;
    const spots = wide
      ? [
          { x: -halfWidth * 0.62, y: 0.55 },
          { x: halfWidth * 0.62, y: 0.85 },
          { x: halfWidth * 0.5, y: -1.25 },
        ]
      : [
          // tall screens: an arc of cards above Ogle, clear of the title and the buttons
          { x: -halfWidth * 0.6, y: halfHeight * 0.46 },
          { x: 0, y: halfHeight * 0.54 },
          { x: halfWidth * 0.6, y: halfHeight * 0.46 },
        ];
    cards.forEach((card, i) => {
      card.home = spots[i];
    });
    for (const sparkle of sparkles) {
      const range = halfSizeAt(1.5);
      sparkle.mesh.position.set((Math.random() * 2 - 1) * range.halfWidth * 0.9, (Math.random() * 2 - 1) * range.halfHeight * 0.85, 1.5);
    }
    for (const chip of chips) {
      chip.x = (Math.random() * 2 - 1) * halfSizeAt(chip.z).halfWidth * 0.95;
    }
  };
  layout();
  const cardScale = () => (halfSizeAt(0).halfWidth > halfSizeAt(0).halfHeight * 1.1 ? 1 : 0.62);
  addEventListener('resize', layout);

  // ---- animation ----
  let time = 0;
  let nextFlipAt = 2.2;
  let nextCard = 0;
  const observer: Observer<Scene> | null = scene.onBeforeRenderObservable.add(() => {
    const dt = Math.min(engine.getDeltaTime() / 1000, 0.05);
    time += dt;
    const t = time * motion;
    // runs after EyeScene's own update each frame, so this wins over its default distance
    camera.position.z = -viewDistance();

    sunburstMaterial.setFloat('time', t);

    // flip one card at a time: back -> word, then back again
    if (time > nextFlipAt) {
      const card = cards[nextCard % cards.length];
      card.showingFront = !card.showingFront;
      if (!card.showingFront) nextCard++;
      nextFlipAt = time + (card.showingFront ? 1.6 : 0.9);
    }

    const scale = cardScale();
    for (const card of cards) {
      const appear = reducedMotion ? 1 : popIn((time - card.delay) / 0.7);
      card.node.scaling.setAll(appear * scale);
      card.flip = damp(card.flip, card.showingFront ? Math.PI : 0, 7, dt);
      card.node.position.set(
        card.home.x + Math.sin(t * 0.7 + card.phase) * 0.12,
        card.home.y + Math.sin(t * 1.3 + card.phase) * 0.16,
        0.4,
      );
      card.node.rotation.y = card.flip + Math.sin(t * 0.9 + card.phase) * 0.18;
      card.node.rotation.z = Math.sin(t * 0.6 + card.phase) * 0.12;
    }

    for (const chip of chips) {
      const { halfHeight } = halfSizeAt(chip.z);
      chip.y += chip.speed * dt * motion;
      if (chip.y > halfHeight + 1) {
        chip.y = -halfHeight - 1;
        chip.x = (Math.random() * 2 - 1) * halfSizeAt(chip.z).halfWidth * 0.95;
      }
      chip.mesh.position.set(chip.x + Math.sin(t + chip.tilt) * 0.2, chip.y, chip.z);
      chip.mesh.rotation.x = chip.tilt + t * chip.spin * 0.6;
      chip.mesh.rotation.z = t * chip.spin;
      chip.mesh.scaling.setAll(reducedMotion ? 1 : popIn((time - 0.3) / 0.8));
    }

    for (const sparkle of sparkles) {
      const twinkle = Math.max(0, Math.sin(t * sparkle.speed + sparkle.phase));
      sparkle.mesh.scaling.setAll(reducedMotion ? 0.6 : twinkle * twinkle);
      sparkle.mesh.rotation.z = t * 0.8 + sparkle.phase;
    }
  });

  return {
    dispose() {
      removeEventListener('resize', layout);
      if (observer) scene.onBeforeRenderObservable.remove(observer);
      root.dispose(false, true);
    },
  };
}
