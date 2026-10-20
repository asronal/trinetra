// TRINETRA — 3D world: terrain, sky, the sensor post and the air entities,
// seen through the camera on the post's mast (day or thermal) or from an
// overview camera. Positions come from the Python simulation; this file
// only draws.
//
// Axes: simulation east / north / up (metres) map to three.js x / -z / y.

import * as THREE from "../vendor/three.module.min.js";

const DEG = Math.PI / 180;
export const toV3 = (e, n, u, v = new THREE.Vector3()) => v.set(e, u, -n);

// ── Deterministic value noise, so the terrain is the same every run ──
function hash(x, y, seed) {
  let h = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263) ^ Math.imul(seed | 0, 1442695041);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}
function noise(x, y, seed) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi, seed), b = hash(xi + 1, yi, seed), c = hash(xi, yi + 1, seed), d = hash(xi + 1, yi + 1, seed);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
function fbm(x, y, seed, octaves = 5) {
  let sum = 0, amp = 0.5, f = 1, norm = 0;
  for (let i = 0; i < octaves; i++) { sum += amp * noise(x * f, y * f, seed + i * 17); norm += amp; f *= 2; amp *= 0.5; }
  return sum / norm;
}
const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

// Field colours give farmland its patchwork look from the mast and from above
const TERRAIN = {
  rural:    { fields: [0x3f6d1e, 0x56802a, 0x4a7724, 0x6b8530, 0x8a7f4a, 0x386419], high: 0x8c7a52, hills: 40, far: 220, ring: 260, seed: 11, trees: 1400, houses: 60 },
  urban:    { fields: [0x6f716a, 0x7d7c72, 0x66705a, 0x85827a, 0x5f6a52], high: 0x8f8a78, hills: 20, far: 90, ring: 160, seed: 23, trees: 450, houses: 900 },
  mountain: { fields: [0x5b6345, 0x6d6a50, 0x55603f, 0x7a735c], high: 0xeef2f6, hills: 90, far: 1500, ring: 2200, seed: 37, trees: 700, houses: 14 },
  coastal:  { fields: [0x6f8a4a, 0x84955a, 0x9c9a6a, 0x6a8344], high: 0x7d7a55, hills: 25, far: 140, ring: 200, seed: 41, trees: 500, houses: 110 },
};

export function terrainHeight(e, n, terrain) {
  const t = TERRAIN[terrain] || TERRAIN.rural;
  const r = Math.hypot(e, n);
  let h = (fbm(e / 1500, n / 1500, t.seed) - 0.45) * t.hills * smooth(500, 3500, r);
  h += Math.pow(fbm(e / 3200, n / 3200, t.seed + 5), 2.0) * t.far * smooth(3500, 8000, r);
  if (terrain === "coastal") h -= 40 * smooth(-1300, -2600, n);
  return h;
}

const SKY = {
  day:   { top: 0x2a68b2, horizon: 0xc3d9ea, fog: 0xc6d8e6, sunColor: 0xfff4e0, sun: 1.9, hemi: 0.95, sunEl: 42, sunAz: 140, exposure: 1.0, density: 0.000055, clouds: 0xffffff },
  dusk:  { top: 0x1c2552, horizon: 0xee9a5a, fog: 0xc98f6a, sunColor: 0xffa060, sun: 1.2, hemi: 0.5, sunEl: 3, sunAz: 255, exposure: 1.0, density: 0.00007, clouds: 0xf3b48a },
  night: { top: 0x020409, horizon: 0x0e1a2e, fog: 0x0b1422, sunColor: 0x9fb4d8, sun: 0.32, hemi: 0.24, sunEl: 38, sunAz: 205, exposure: 1.2, density: 0.00011, clouds: null },
};

// Thermal (white-hot) grey levels: warm things light, cold sky dark.
// The ground is warmer than the air by day and cooler at night.
const THERMAL = {
  day:   { sky: [0x050608, 0x34373a], ground: 0x8a8a8a, trees: 0x4a4a4a, houses: 0xa8a8a8, body: 0xbdbdbd, hot: 0xffffff, bird: 0xd6d6d6, ring: 0x3e3e3e },
  dusk:  { sky: [0x050608, 0x2c2e30], ground: 0x6c6c6c, trees: 0x404040, houses: 0x8a8a8a, body: 0xb5b5b5, hot: 0xffffff, bird: 0xd2d2d2, ring: 0x353535 },
  night: { sky: [0x020203, 0x1c1d1e], ground: 0x3e3e3e, trees: 0x4c4c4c, houses: 0x6a6a6a, body: 0xadadad, hot: 0xffffff, bird: 0xcfcfcf, ring: 0x262626 },
};

// Overview draws air entities oversized so they can be seen from kilometres away
const OVERVIEW_SCALE = { quad: 110, hexa: 60, fpv: 130, fixed_wing: 35, bird: 70, aircraft: 3 };

function std(color, extra = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.25, ...extra });
}
// A mesh carries its day material and a thermal one; setSensor() swaps them
function dual(mesh, thermalColor) {
  mesh.userData.day = mesh.material;
  mesh.userData.thermal = new THREE.MeshBasicMaterial({ color: thermalColor, transparent: mesh.material.transparent,
    opacity: mesh.material.transparent ? Math.min(1, mesh.material.opacity + 0.2) : 1 });
  return mesh;
}

function softTexture(draw, size = 128) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  draw(c.getContext("2d"), size);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
const glowTex = () => softTexture((g, s) => {
  const r = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.25, "rgba(255,255,255,0.45)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.fillRect(0, 0, s, s);
});
const cloudTex = (seed) => softTexture((g, s) => {
  for (let i = 0; i < 14; i++) {
    const x = s * (0.2 + 0.6 * hash(i, 1, seed)), y = s * (0.4 + 0.25 * hash(i, 2, seed)), rr = s * (0.12 + 0.16 * hash(i, 3, seed));
    const r = g.createRadialGradient(x, y, 0, x, y, rr);
    r.addColorStop(0, "rgba(255,255,255,0.55)"); r.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = r; g.beginPath(); g.arc(x, y, rr, 0, Math.PI * 2); g.fill();
  }
}, 256);
const grainTex = () => {
  const t = softTexture((g, s) => {
    const img = g.createImageData(s, s);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = 200 + hash(i, 7, 3) * 55;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255;
    }
    g.putImageData(img, 0, 0);
  }, 128);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(220, 220);
  return t;
};

let GLOW = null;
function buildModel(label, th) {
  GLOW = GLOW || glowTex();
  const g = new THREE.Group();
  const body = new THREE.Group();
  g.add(body);
  const rotors = [], wings = [], lights = [];
  const add = (geo, m, thermal, parent = body) => { const mesh = dual(new THREE.Mesh(geo, m), thermal); parent.add(mesh); return mesh; };
  const dark = std(0x1f2328), grey = std(0x4d535b), red = std(0xb03020);
  const disc = new THREE.MeshBasicMaterial({ color: 0x111111, transparent: true, opacity: 0.35, depthWrite: false });

  if (label === "quad" || label === "hexa" || label === "fpv") {
    const arms = label === "hexa" ? 6 : 4;
    const span = { quad: 0.35, hexa: 0.9, fpv: 0.25 }[label];
    add(new THREE.BoxGeometry(span * 0.3, span * 0.12, span * 0.3), dark, th.body);
    for (let i = 0; i < arms; i++) {
      const a = (i + 0.5) / arms * Math.PI * 2;
      const arm = add(new THREE.BoxGeometry(span / 2, span * 0.04, span * 0.04), grey, th.body);
      arm.position.set(Math.cos(a) * span / 4, 0, Math.sin(a) * span / 4);
      arm.rotation.y = -a;
      const motor = add(new THREE.CylinderGeometry(span * 0.05, span * 0.05, span * 0.08, 10), dark, th.hot);
      motor.position.set(Math.cos(a) * span / 2, span * 0.03, Math.sin(a) * span / 2);
      const rotor = add(new THREE.CylinderGeometry(span * 0.2, span * 0.2, 0.004, 18), disc, th.body);
      rotor.position.set(Math.cos(a) * span / 2, span * 0.08, Math.sin(a) * span / 2);
      rotors.push(rotor);
    }
    const nose = add(new THREE.BoxGeometry(span * 0.08, span * 0.06, span * 0.06), red, th.body);
    nose.position.set(0, 0, -span * 0.17);
    if (label === "fpv") body.rotation.x = -20 * DEG;       // racing drones fly nose-down
    if (label !== "fpv") lights.push([[-span / 2, 0, 0], 0xff3030], [[span / 2, 0, 0], 0x30ff60], [[0, span * 0.1, span * 0.15], 0xffffff, true]);
  } else if (label === "fixed_wing" || label === "aircraft") {
    const m = label === "aircraft" ? std(0xe8eaec) : grey;
    const fus = add(new THREE.CylinderGeometry(0.07, 0.04, 1.3, 12), m, th.body);
    fus.rotation.x = Math.PI / 2;
    add(new THREE.BoxGeometry(2.0, 0.025, 0.24), m, th.body);
    const tail = add(new THREE.BoxGeometry(0.62, 0.02, 0.13), m, th.body);
    tail.position.z = 0.58;
    const fin = add(new THREE.BoxGeometry(0.02, 0.2, 0.15), m, th.body);
    fin.position.set(0, 0.1, 0.58);
    const engine = add(new THREE.CylinderGeometry(0.05, 0.05, 0.12, 10), dark, th.hot);
    engine.rotation.x = Math.PI / 2;
    engine.position.z = -0.6;
    const prop = add(new THREE.CylinderGeometry(0.16, 0.16, 0.004, 16), disc, th.body);
    prop.rotation.x = Math.PI / 2;
    prop.position.z = -0.67;
    rotors.push(prop);
    lights.push([[-1.0, 0, 0], 0xff3030], [[1.0, 0, 0], 0x30ff60], [[0, 0.2, 0.6], 0xffffff, true]);
    if (label === "aircraft") g.scale.setScalar(15);
  } else {                                                    // bird
    const brown = std(0x4a3a2c, { metalness: 0 });
    const b = add(new THREE.SphereGeometry(0.1, 12, 8), brown, th.bird);
    b.scale.set(0.8, 0.7, 2.0);
    for (const side of [-1, 1]) {
      const pivot = new THREE.Group();
      pivot.position.x = side * 0.06;
      const w = add(new THREE.BoxGeometry(0.28, 0.01, 0.12), brown, th.body, pivot);
      w.position.x = side * 0.14;
      body.add(pivot);
      wings.push({ pivot, side });
    }
  }
  // Thermal only: hot motors and body blur into a bright blob through LWIR optics
  const span = { quad: 0.35, hexa: 0.9, fpv: 0.25, fixed_wing: 2.0, aircraft: 2.0, bird: 0.6 }[label];
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: 0xffffff, transparent: true,
    opacity: label === "bird" ? 0.7 : 0.95, depthWrite: false, blending: THREE.AdditiveBlending }));
  glow.scale.setScalar(span * 1.5);
  glow.visible = false;
  glow.userData.thermalGlow = true;
  body.add(glow);
  // Navigation lights: point sources that stay a few pixels wide at any range
  const lightObjs = lights.map(([p, color, strobe]) => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(p, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({ color, size: strobe ? 4 : 3, sizeAttenuation: false, fog: false }));
    pts.userData.strobe = !!strobe;
    body.add(pts);
    return pts;
  });
  return { group: g, rotors, wings, lights: lightObjs, glow, label };
}

export class World3D {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.scene = new THREE.Scene();
    this.eo = new THREE.PerspectiveCamera(50, 16 / 9, 0.25, 60000);
    this.eo.rotation.order = "YXZ";
    this.ov = new THREE.PerspectiveCamera(45, 16 / 9, 5, 80000);
    this.mode = "camera";
    this.sensor = "day";
    this.fov = 50;
    this.look = { az: 0, el: 2 };          // where the camera view points now
    this.target = { az: 0, el: 2 };        // where the post's camera is pointed
    this.orbit = { az: 205, el: 26, r: 4600 };
    this.ents = new Map();
    this.overviewOnly = [];
    this.dayOnly = [];
    this.built = null;
  }

  build(scn, cameraHeight, rings) {
    if (this.built === scn.id) return;
    this.built = scn.id;
    while (this.scene.children.length) this.scene.remove(this.scene.children[0]);
    this.ents.clear();
    this.overviewOnly = [];
    this.dayOnly = [];
    const look = SKY[scn.time_of_day] || SKY.day;
    const th = THERMAL[scn.time_of_day] || THERMAL.day;
    this.sky = look;
    this.th = th;
    this.cameraHeight = cameraHeight;
    this.renderer.toneMappingExposure = look.exposure;
    this.baseDensity = look.density + scn.fog * 0.0009;
    this.scene.fog = new THREE.FogExp2(look.fog, this.baseDensity);

    // Sky dome with day and thermal colours
    this.skyUniforms = { top: { value: new THREE.Color(look.top) }, horizon: { value: new THREE.Color(look.horizon) } };
    const dome = new THREE.Mesh(new THREE.SphereGeometry(30000, 32, 16), new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false, fog: false, uniforms: this.skyUniforms,
      vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
      fragmentShader: "uniform vec3 top; uniform vec3 horizon; varying vec3 vP; void main(){ float h = vP.y; vec3 c = h > 0.0 ? mix(horizon, top, pow(h, 0.45)) : horizon * 0.85; gl_FragColor = vec4(c, 1.0); }",
    }));
    this.scene.add(dome);

    // Lights and the sun
    this.scene.add(new THREE.HemisphereLight(look.top, 0x4a4030, look.hemi));
    const sun = new THREE.DirectionalLight(look.sunColor, look.sun);
    const sunDir = toV3(Math.sin(look.sunAz * DEG) * Math.cos(look.sunEl * DEG), Math.cos(look.sunAz * DEG) * Math.cos(look.sunEl * DEG), Math.sin(look.sunEl * DEG));
    sun.position.copy(sunDir.clone().multiplyScalar(10000));
    this.scene.add(sun);
    const night = scn.time_of_day === "night";
    const disc = new THREE.Mesh(new THREE.SphereGeometry(night ? 160 : 230, 16, 12), new THREE.MeshBasicMaterial({ color: look.sunColor, fog: false }));
    disc.position.copy(sunDir.clone().multiplyScalar(25000));
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex(), color: look.sunColor, fog: false, depthWrite: false,
      transparent: true, opacity: night ? 0.25 : 0.8, blending: THREE.AdditiveBlending }));
    glow.position.copy(sunDir.clone().multiplyScalar(24000));
    glow.scale.setScalar(night ? 2500 : 6500);
    this.scene.add(disc, glow);
    this.dayOnly.push(disc, glow);
    if (night) { const stars = this._stars(); this.scene.add(stars); this.dayOnly.push(stars); }
    if (look.clouds) this._clouds(look.clouds);

    this.scene.add(this._terrain(scn.terrain, th));
    this._horizonRing(scn.terrain, look, th);
    this._scatter(scn.terrain, th);
    this.scene.add(this._post(cameraHeight));
    this._rings(rings);
    this.applySensor();
  }

  _terrain(kind, th) {
    const t = TERRAIN[kind] || TERRAIN.rural;
    const size = 18000, seg = 380;
    const geo = new THREE.PlaneGeometry(size, size, seg, seg);
    geo.rotateX(-Math.PI / 2);
    const pos = geo.attributes.position;
    const day = new Float32Array(pos.count * 3), therm = new Float32Array(pos.count * 3);
    const ch = new THREE.Color(t.high), c = new THREE.Color(), f = new THREE.Color(), tg = new THREE.Color(th.ground);
    for (let i = 0; i < pos.count; i++) {
      const e = pos.getX(i), n = -pos.getZ(i);
      const h = terrainHeight(e, n, kind);
      pos.setY(i, h);
      // Fields: irregular cells ~250 m, each a crop or soil colour
      const cell = 250, jx = (fbm(e / 700, n / 700, t.seed + 3) - 0.5) * 160, jy = (fbm(e / 700, n / 700, t.seed + 4) - 0.5) * 160;
      const cx = Math.floor((e + jx) / cell), cy = Math.floor((n + jy) / cell);
      f.set(t.fields[Math.floor(hash(cx, cy, t.seed) * t.fields.length)]);
      const shade = 0.88 + fbm(e / 90, n / 90, t.seed + 9) * 0.24;
      c.copy(f).multiplyScalar(shade);
      const high = kind === "mountain" ? smooth(300, 900, h) : smooth(20, 90, h);
      c.lerp(ch, high);
      if (kind === "coastal" && h < -1) c.set(0xd8c89a);
      day.set([c.r, c.g, c.b], i * 3);
      // Thermal: fields differ a little in temperature; high ground is colder
      const k = (0.8 + hash(cx, cy, t.seed + 1) * 0.4) * (1 - 0.35 * high);
      therm.set([tg.r * k, tg.g * k, tg.b * k], i * 3);
    }
    geo.setAttribute("color", new THREE.BufferAttribute(day, 3));
    geo.computeVertexNormals();
    this.terrainGeo = geo;
    this.terrainColors = { day: new THREE.BufferAttribute(day, 3), thermal: new THREE.BufferAttribute(therm, 3) };
    const ground = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95, metalness: 0, map: grainTex() }));
    ground.userData.day = ground.material;
    ground.userData.thermal = new THREE.MeshBasicMaterial({ vertexColors: true });
    const g = new THREE.Group();
    g.add(ground);
    if (kind === "coastal") {
      const water = dual(new THREE.Mesh(new THREE.PlaneGeometry(60000, 60000),
        new THREE.MeshStandardMaterial({ color: 0x2a5d78, roughness: 0.25, metalness: 0.2 })), 0x2c2c2c);
      water.rotation.x = -Math.PI / 2;
      water.position.y = -6;
      g.add(water);
    }
    return g;
  }

  // Distant hills all round the horizon, so the view never ends at a flat edge
  _horizonRing(kind, look, th) {
    const t = TERRAIN[kind] || TERRAIN.rural;
    const N = 360, R = 15000, pos = [], idx = [];
    for (let i = 0; i <= N; i++) {
      const a = i / N * Math.PI * 2;
      let h = 80 + Math.pow(fbm(Math.cos(a) * 3 + 10, Math.sin(a) * 3 + 10, t.seed + 21), 1.6) * t.ring;
      if (kind === "coastal" && Math.cos(a) < -0.2) h = 0;              // open sea to the south
      const x = Math.sin(a) * R, z = -Math.cos(a) * R;
      pos.push(x, -60, z, x, h, z);
      if (i < N) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geo.setIndex(idx);
    const dayColor = new THREE.Color(look.horizon).lerp(new THREE.Color(kind === "mountain" ? 0x7a8696 : 0x6f7f74), 0.35);
    const ring = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: dayColor, fog: false, side: THREE.DoubleSide }));
    dual(ring, th.ring);
    this.scene.add(ring);
  }

  _clouds(color) {
    for (let i = 0; i < 26; i++) {
      const a = hash(i, 5, 77) * Math.PI * 2, r = 3000 + hash(i, 6, 77) * 11000;
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: cloudTex(i), color, transparent: true, opacity: 0.75, fog: false, depthWrite: false }));
      s.position.copy(toV3(Math.sin(a) * r, Math.cos(a) * r, 1400 + hash(i, 7, 77) * 1500));
      s.scale.set(2600 + hash(i, 8, 77) * 2600, 1000 + hash(i, 9, 77) * 700, 1);
      s.userData.day = s.material;
      s.userData.thermal = new THREE.SpriteMaterial({ map: s.material.map, color: 0x3a3a3a, transparent: true, opacity: 0.5, fog: false, depthWrite: false });
      this.scene.add(s);
    }
  }

  // Instanced meshes carry per-instance colours; thermal gets its own grey set
  _instanced(geo, count, thermalGrey) {
    const mesh = new THREE.InstancedMesh(geo, std(0xffffff, { metalness: 0 }), count);
    mesh.userData.day = mesh.material;
    mesh.userData.thermal = new THREE.MeshBasicMaterial({ color: 0xffffff });
    mesh.userData.thermalGrey = new THREE.Color(thermalGrey);
    return mesh;
  }

  _finishColors(mesh, rnd) {
    const day = mesh.instanceColor;
    const therm = new THREE.InstancedBufferAttribute(new Float32Array(day.count * 3), 3);
    const g = mesh.userData.thermalGrey;
    for (let i = 0; i < day.count; i++) {
      const k = 0.8 + rnd(i, 31) * 0.4;
      therm.setXYZ(i, g.r * k, g.g * k, g.b * k);
    }
    mesh.userData.colors = { day, thermal: therm };
  }

  _scatter(kind, th) {
    const t = TERRAIN[kind] || TERRAIN.rural;
    const rnd = (i, k) => hash(i, k, t.seed + 500);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), col = new THREE.Color();
    // Trees, in loose clumps
    const treeGeo = new THREE.ConeGeometry(2.6, 9, 7);
    treeGeo.translate(0, 4.5, 0);
    const trees = this._instanced(treeGeo, t.trees, th.trees);
    for (let i = 0; i < t.trees; i++) {
      const clump = Math.floor(i / 12);
      const r = 220 + rnd(clump, 1) * 6500, a = rnd(clump, 2) * Math.PI * 2;
      const e = Math.sin(a) * r + (rnd(i, 21) - 0.5) * 140, n = Math.cos(a) * r + (rnd(i, 22) - 0.5) * 140;
      const h = terrainHeight(e, n, kind);
      const k = (kind === "coastal" && h < 0) ? 0 : 0.7 + rnd(i, 3) * 0.8;
      m.compose(toV3(e, n, h, p), q, s.set(k, k, k));
      trees.setMatrixAt(i, m);
      trees.setColorAt(i, col.set(kind === "mountain" ? 0x2f4a33 : 0x355a2a).multiplyScalar(0.75 + rnd(i, 4) * 0.5));
    }
    this._finishColors(trees, rnd);
    this.scene.add(trees);
    // Buildings, in villages (or one spread-out town)
    const boxGeo = new THREE.BoxGeometry(1, 1, 1);
    boxGeo.translate(0, 0.5, 0);
    const houses = this._instanced(boxGeo, t.houses, th.houses);
    for (let i = 0; i < t.houses; i++) {
      const village = Math.floor(i / (kind === "urban" ? 40 : 10));
      const r = 450 + rnd(village, 11) * 5000, a = rnd(village, 12) * Math.PI * 2;
      const spread = kind === "urban" ? 420 : 160;
      const e = Math.sin(a) * r + (rnd(i, 23) - 0.5) * spread, n = Math.cos(a) * r + (rnd(i, 24) - 0.5) * spread;
      const h = terrainHeight(e, n, kind);
      const w = 8 + rnd(i, 13) * 18, d = 8 + rnd(i, 14) * 18;
      const ht = (kind === "coastal" && h < 0) ? 0 : kind === "urban" ? 6 + rnd(i, 15) * 22 : 4 + rnd(i, 15) * 4;
      q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), rnd(i, 16) * Math.PI);
      m.compose(toV3(e, n, h - 0.5, p), q, s.set(w, ht, d));
      houses.setMatrixAt(i, m);
      houses.setColorAt(i, col.set([0xb8ab94, 0x9a9384, 0xc9c2b4, 0x8c7b6a, 0xa59c8c][Math.floor(rnd(i, 17) * 5)]));
    }
    q.identity();
    this._finishColors(houses, rnd);
    this.scene.add(houses);
  }

  _post(height) {
    const g = new THREE.Group();
    const steel = std(0x8a9097), olive = std(0x4f5a3a, { metalness: 0 });
    const shelter = new THREE.Mesh(new THREE.BoxGeometry(4, 2.6, 3), olive);
    shelter.position.set(-3.5, 1.3, 1.5);
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.18, height, 10), steel);
    mast.position.y = height / 2;
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.35, 0.4), std(0x2b2f34));
    head.position.y = height + 0.2;
    const radar = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.8, 0.12), steel);
    radar.position.set(0, height - 0.9, 0);
    g.add(shelter, mast, head, radar);
    this.radarHead = radar;
    this.postGroup = g;
    return g;
  }

  _rings(rings) {
    const mk = (r, color, dashed) => {
      const pts = [];
      for (let i = 0; i <= 128; i++) {
        const a = i / 128 * Math.PI * 2;
        pts.push(toV3(Math.sin(a) * r, Math.cos(a) * r, 4));
      }
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      const m = dashed
        ? new THREE.LineDashedMaterial({ color, dashSize: 60, gapSize: 50, depthTest: false, transparent: true, opacity: 0.9 })
        : new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.9 });
      const line = new THREE.Line(geo, m);
      if (dashed) line.computeLineDistances();
      line.renderOrder = 10;
      line.visible = false;
      this.scene.add(line);
      this.overviewOnly.push(line);
    };
    mk(rings.engage_m, 0xff5a4a, false);
    mk(rings.r50_m, 0xf0a63a, true);
  }

  _stars() {
    const n = 1800, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const a = hash(i, 1, 9) * Math.PI * 2, z = 0.03 + hash(i, 2, 9) * 0.97, r = Math.sqrt(1 - z * z);
      pos.set([Math.cos(a) * r * 25000, z * 25000, Math.sin(a) * r * 25000], i * 3);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    return new THREE.Points(geo, new THREE.PointsMaterial({ color: 0xdfe8ff, size: 1.6, sizeAttenuation: false, fog: false }));
  }

  // ── Day / thermal ──
  setSensor(sensor) {
    if (this.sensor === sensor) return;
    this.sensor = sensor;
    this.applySensor();
  }

  applySensor(root = this.scene) {
    const thermal = this.sensor === "thermal" && this.mode === "camera";
    root.traverse((o) => {
      if (o.userData.day) o.material = thermal ? o.userData.thermal : o.userData.day;
      if (o.userData.colors) o.instanceColor = thermal ? o.userData.colors.thermal : o.userData.colors.day;
    });
    if (root !== this.scene || !this.th) return;
    if (this.terrainGeo) {
      this.terrainGeo.setAttribute("color", thermal ? this.terrainColors.thermal : this.terrainColors.day);
    }
    this.skyUniforms.top.value.set(thermal ? this.th.sky[0] : this.sky.top);
    this.skyUniforms.horizon.value.set(thermal ? this.th.sky[1] : this.sky.horizon);
    this.scene.fog.color.set(thermal ? this.th.sky[1] : this.sky.fog);
    this.thermalOn = thermal;
    for (const o of this.dayOnly) o.visible = !thermal;
    for (const e of this.ents.values()) {
      for (const l of e.lights) l.visible = !thermal;
      e.glow.visible = thermal;
    }
    this.renderer.toneMapping = thermal ? THREE.NoToneMapping : THREE.ACESFilmicToneMapping;
  }

  // ── Per-update sync from the simulation state ──
  sync(entities, now) {
    const seen = new Set();
    for (const s of entities) {
      seen.add(s.id);
      let o = this.ents.get(s.id);
      if (!o) {
        o = buildModel(s.label, this.th || THERMAL.day);
        o.p = new THREE.Vector3(); o.v = new THREE.Vector3(); o.trail = [];
        const tg = new THREE.BufferGeometry();
        tg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(3 * 240), 3));
        tg.setDrawRange(0, 0);
        o.trailLine = new THREE.Line(tg, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.5, depthTest: false }));
        o.trailLine.renderOrder = 9;
        o.trailT = -1;
        o.phase = hash(s.id.length, s.id.charCodeAt(s.id.length - 1), 5) * 1000;
        this.scene.add(o.group, o.trailLine);
        this.ents.set(s.id, o);
        this.applySensor(o.group);
        for (const l of o.lights) l.visible = !this.thermalOn;
        o.glow.visible = !!this.thermalOn;
      }
      o.p.set(s.e, s.n, s.u);
      o.v.set(s.ve, s.vn, s.vu);
      o.t0 = now;
      o.hostile = s.hostile;
      if (now - o.trailT > 1000) {
        o.trailT = now;
        o.trail.push(toV3(s.e, s.n, s.u));
        if (o.trail.length > 240) o.trail.shift();
        const arr = o.trailLine.geometry.attributes.position;
        o.trail.forEach((v, i) => arr.setXYZ(i, v.x, v.y, v.z));
        arr.needsUpdate = true;
        o.trailLine.geometry.setDrawRange(0, o.trail.length);
        o.trailLine.geometry.computeBoundingSphere();
      }
    }
    for (const [id, o] of this.ents) {
      if (!seen.has(id)) {
        this.scene.remove(o.group, o.trailLine);
        this.ents.delete(id);
      }
    }
  }

  setMode(mode) {
    this.mode = mode;
    for (const o of this.overviewOnly) o.visible = mode === "overview";
    this.applySensor();
  }

  setTarget(az, el) { this.target.az = az; this.target.el = el; }
  setFov(fov) { this.fov = fov; }
  setFogBoost(on) {
    if (!this.scene.fog) return;
    const base = this.baseDensity * (this.thermalOn ? 0.45 : 1);       // thermal sees further through haze
    this.scene.fog.density = base + (on ? 0.0012 : 0);
  }

  camera() { return this.mode === "overview" ? this.ov : this.eo; }

  resize(w, h) {
    this.renderer.setSize(w, h, false);
    for (const c of [this.eo, this.ov]) { c.aspect = w / h; c.updateProjectionMatrix(); }
  }

  // Screen position of a world point in the active camera, or null if behind it.
  project(e, n, u, w, h) {
    const v = toV3(e, n, u).project(this.camera());
    if (v.z > 1) return null;
    return { x: (v.x + 1) / 2 * w, y: (1 - v.y) / 2 * h, inFront: v.z < 1 };
  }

  frame(now, dt) {
    for (const o of this.ents.values()) {
      // Dead-reckon from the last update so motion is smooth at 60 fps
      const age = Math.min(0.6, (now - o.t0) / 1000);
      const e = o.p.x + o.v.x * age, n = o.p.y + o.v.y * age, u = o.p.z + o.v.z * age;
      toV3(e, n, u, o.group.position);
      if (Math.hypot(o.v.x, o.v.y) > 0.3) o.group.rotation.y = -Math.atan2(o.v.x, o.v.y);
      const base = o.label === "aircraft" ? 15 : 1;
      o.group.scale.setScalar(base * (this.mode === "overview" ? OVERVIEW_SCALE[o.label] : 1));
      for (const r of o.rotors) r.rotation.y += dt * 60;
      for (const w of o.wings) w.pivot.rotation.z = w.side * Math.sin(now / 1000 * 9 + o.phase) * 0.6;
      for (const l of o.lights) {
        if (l.userData.strobe) l.visible = !this.thermalOn && Math.floor((now + o.phase) / 120) % 9 === 0;
      }
      o.trailLine.visible = this.mode === "overview";
      o.trailLine.material.color.set(o.hostile === true ? 0xff5a4a : o.hostile === false ? 0x6fb6ff : 0xffffff);
    }
    if (this.radarHead) this.radarHead.rotation.y = now / 1000 * Math.PI * 2;
    if (this.postGroup) {
      this.postGroup.visible = this.mode === "overview";      // the camera is mounted on the mast
      this.postGroup.scale.setScalar(12);
    }

    // The camera view slews towards where the post's camera is pointed
    const daz = ((this.target.az - this.look.az + 540) % 360) - 180;
    const k = Math.min(1, dt * 4);
    this.look.az = (this.look.az + daz * k + 360) % 360;
    this.look.el += (this.target.el - this.look.el) * k;
    this.eo.position.set(0, this.cameraHeight, 0);           // same height the simulation aims from
    this.eo.rotation.y = -this.look.az * DEG;
    this.eo.rotation.x = this.look.el * DEG;
    this.eo.fov += (this.fov - this.eo.fov) * Math.min(1, dt * 6);
    this.eo.updateProjectionMatrix();

    const o = this.orbit;
    const r = o.r, a = o.az * DEG, el = o.el * DEG;
    this.ov.position.set(Math.sin(a) * Math.cos(el) * r, Math.sin(el) * r, -Math.cos(a) * Math.cos(el) * r);
    this.ov.lookAt(0, 0, 0);

    this.renderer.render(this.scene, this.camera());
  }
}
