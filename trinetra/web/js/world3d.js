// TRINETRA — 3D world: terrain, sky, the sensor post and the air entities,
// seen through the day (EO) camera on the post's mast or from an overview
// camera. Positions come from the Python simulation; this file only draws.
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

const TERRAIN = {
  rural:    { low: 0x5f7d34, mid: 0x7d8a45, high: 0x8c7a52, hills: 40, far: 220, seed: 11, trees: 900, houses: 40 },
  urban:    { low: 0x6d7068, mid: 0x7f7f74, high: 0x8f8a78, hills: 20, far: 90, seed: 23, trees: 250, houses: 650 },
  mountain: { low: 0x5d6447, mid: 0x7b7563, high: 0xe9eef3, hills: 90, far: 1500, seed: 37, trees: 500, houses: 12 },
  coastal:  { low: 0xcdbb88, mid: 0x6f8a4a, high: 0x7d7a55, hills: 25, far: 140, seed: 41, trees: 350, houses: 80 },
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
  day:   { top: 0x2c6cb5, horizon: 0xbdd5e8, fog: 0xc4d6e4, sunColor: 0xfff4e0, sun: 2.4, hemi: 1.1, sunEl: 42, sunAz: 140, exposure: 1.0, density: 0.000055 },
  dusk:  { top: 0x1c2552, horizon: 0xee9a5a, fog: 0xc98f6a, sunColor: 0xffa060, sun: 1.2, hemi: 0.5, sunEl: 3, sunAz: 255, exposure: 1.0, density: 0.00007 },
  night: { top: 0x020409, horizon: 0x0e1a2e, fog: 0x0b1422, sunColor: 0x9fb4d8, sun: 0.18, hemi: 0.12, sunEl: 38, sunAz: 205, exposure: 1.2, density: 0.00011 },
};

// Overview draws air entities oversized so they can be seen from kilometres away
const OVERVIEW_SCALE = { quad: 110, hexa: 60, fpv: 130, fixed_wing: 35, bird: 70, aircraft: 3 };

function mat(color, extra = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.25, ...extra });
}

function buildModel(label) {
  const g = new THREE.Group();
  const body = new THREE.Group();
  g.add(body);
  const rotors = [], wings = [];
  const dark = mat(0x1f2328), grey = mat(0x4d535b), red = mat(0xb03020);
  const disc = new THREE.MeshBasicMaterial({ color: 0x111111, transparent: true, opacity: 0.35, depthWrite: false });

  if (label === "quad" || label === "hexa" || label === "fpv") {
    const arms = label === "hexa" ? 6 : 4;
    const span = { quad: 0.35, hexa: 0.9, fpv: 0.25 }[label];
    body.add(new THREE.Mesh(new THREE.BoxGeometry(span * 0.3, span * 0.12, span * 0.3), dark));
    for (let i = 0; i < arms; i++) {
      const a = (i + 0.5) / arms * Math.PI * 2;
      const arm = new THREE.Mesh(new THREE.BoxGeometry(span / 2, span * 0.04, span * 0.04), grey);
      arm.position.set(Math.cos(a) * span / 4, 0, Math.sin(a) * span / 4);
      arm.rotation.y = -a;
      body.add(arm);
      const rotor = new THREE.Mesh(new THREE.CylinderGeometry(span * 0.2, span * 0.2, 0.004, 18), disc);
      rotor.position.set(Math.cos(a) * span / 2, span * 0.08, Math.sin(a) * span / 2);
      body.add(rotor);
      rotors.push(rotor);
    }
    const nose = new THREE.Mesh(new THREE.BoxGeometry(span * 0.08, span * 0.06, span * 0.06), red);
    nose.position.set(0, 0, -span * 0.17);
    body.add(nose);
    if (label === "fpv") body.rotation.x = -20 * DEG;       // racing drones fly nose-down
  } else if (label === "fixed_wing" || label === "aircraft") {
    const m = label === "aircraft" ? mat(0xe8eaec) : grey;
    const fus = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.04, 1.3, 12), m);
    fus.rotation.x = Math.PI / 2;
    body.add(fus);
    body.add(new THREE.Mesh(new THREE.BoxGeometry(2.0, 0.025, 0.24), m));
    const tail = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.02, 0.13), m);
    tail.position.z = 0.58;
    body.add(tail);
    const fin = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.2, 0.15), m);
    fin.position.set(0, 0.1, 0.58);
    body.add(fin);
    const prop = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.004, 16), disc);
    prop.rotation.x = Math.PI / 2;
    prop.position.z = -0.66;
    body.add(prop);
    rotors.push(prop);
    if (label === "aircraft") g.scale.setScalar(15);
  } else {                                                    // bird
    const brown = mat(0x4a3a2c, { metalness: 0 });
    const b = new THREE.Mesh(new THREE.SphereGeometry(0.1, 12, 8), brown);
    b.scale.set(0.8, 0.7, 2.0);
    body.add(b);
    for (const side of [-1, 1]) {
      const pivot = new THREE.Group();
      pivot.position.x = side * 0.06;
      const w = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.01, 0.12), brown);
      w.position.x = side * 0.14;
      pivot.add(w);
      body.add(pivot);
      wings.push({ pivot, side });
    }
  }
  return { group: g, rotors, wings, label };
}

function skyDome(look) {
  const geo = new THREE.SphereGeometry(30000, 32, 16);
  const m = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color(look.top) }, horizon: { value: new THREE.Color(look.horizon) } },
    vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }",
    fragmentShader: "uniform vec3 top; uniform vec3 horizon; varying vec3 vP; void main(){ float h = vP.y; vec3 c = h > 0.0 ? mix(horizon, top, pow(h, 0.45)) : horizon * 0.85; gl_FragColor = vec4(c, 1.0); }",
  });
  return new THREE.Mesh(geo, m);
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
    this.fov = 50;
    this.look = { az: 0, el: 2 };          // what the EO camera shows now
    this.target = { az: 0, el: 2 };        // where the post's camera is pointed
    this.orbit = { az: 205, el: 26, r: 4600 };
    this.ents = new Map();
    this.overviewOnly = [];
    this.built = null;
  }

  build(scn, cameraHeight, rings) {
    const key = scn.id;
    if (this.built === key) return;
    this.built = key;
    while (this.scene.children.length) this.scene.remove(this.scene.children[0]);
    this.ents.clear();
    this.overviewOnly = [];
    const look = SKY[scn.time_of_day] || SKY.day;
    this.look_ = look;
    this.cameraHeight = cameraHeight;
    this.renderer.toneMappingExposure = look.exposure;
    this.baseDensity = look.density + scn.fog * 0.0009;
    this.scene.fog = new THREE.FogExp2(look.fog, this.baseDensity);
    this.scene.background = new THREE.Color(look.horizon);
    this.scene.add(skyDome(look));

    // Lights
    this.scene.add(new THREE.HemisphereLight(look.top, 0x4a4030, look.hemi));
    const sun = new THREE.DirectionalLight(look.sunColor, look.sun);
    const sunDir = new THREE.Vector3();
    toV3(Math.sin(look.sunAz * DEG) * Math.cos(look.sunEl * DEG), Math.cos(look.sunAz * DEG) * Math.cos(look.sunEl * DEG), Math.sin(look.sunEl * DEG), sunDir);
    sun.position.copy(sunDir.clone().multiplyScalar(10000));
    this.scene.add(sun);
    const disc = new THREE.Mesh(new THREE.SphereGeometry(scn.time_of_day === "night" ? 160 : 230, 16, 12),
      new THREE.MeshBasicMaterial({ color: look.sunColor, fog: false }));
    disc.position.copy(sunDir.clone().multiplyScalar(25000));
    this.scene.add(disc);
    if (scn.time_of_day === "night") this.scene.add(this._stars());

    this.scene.add(this._terrain(scn.terrain));
    this._scatter(scn.terrain);
    this.scene.add(this._post(cameraHeight));
    this._rings(rings);
  }

  _terrain(kind) {
    const t = TERRAIN[kind] || TERRAIN.rural;
    const size = 18000, seg = 260;
    const geo = new THREE.PlaneGeometry(size, size, seg, seg);
    geo.rotateX(-Math.PI / 2);
    const pos = geo.attributes.position;
    const colors = new Float32Array(pos.count * 3);
    const cl = new THREE.Color(t.low), cm = new THREE.Color(t.mid), ch = new THREE.Color(t.high), c = new THREE.Color();
    for (let i = 0; i < pos.count; i++) {
      const e = pos.getX(i), n = -pos.getZ(i);
      const h = terrainHeight(e, n, kind);
      pos.setY(i, h);
      const field = fbm(e / 220, n / 220, t.seed + 99);          // field / patch variation
      const hn = kind === "mountain" ? smooth(250, 900, h) : smooth(-10, 60, h);
      c.copy(cl).lerp(cm, field * 0.8).lerp(ch, hn);
      if (kind === "coastal" && h < -1) c.set(0xd8c89a);
      colors.set([c.r, c.g, c.b], i * 3);
    }
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    const ground = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.95, metalness: 0 }));
    const g = new THREE.Group();
    g.add(ground);
    if (kind === "coastal") {
      const water = new THREE.Mesh(new THREE.PlaneGeometry(60000, 60000),
        new THREE.MeshStandardMaterial({ color: 0x2a5d78, roughness: 0.3, metalness: 0.1 }));
      water.rotation.x = -Math.PI / 2;
      water.position.y = -6;
      g.add(water);
    }
    return g;
  }

  _scatter(kind) {
    const t = TERRAIN[kind] || TERRAIN.rural;
    const rnd = (i, k) => hash(i, k, t.seed + 500);
    // Trees: give the eye a sense of scale and distance
    const treeGeo = new THREE.ConeGeometry(2.6, 9, 7);
    treeGeo.translate(0, 4.5, 0);
    const trees = new THREE.InstancedMesh(treeGeo, mat(kind === "mountain" ? 0x2f4a33 : 0x355a2a, { metalness: 0 }), t.trees);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
    for (let i = 0; i < t.trees; i++) {
      const r = 250 + rnd(i, 1) * 6000, a = rnd(i, 2) * Math.PI * 2;
      const e = Math.sin(a) * r, n = Math.cos(a) * r, h = terrainHeight(e, n, kind);
      if (kind === "coastal" && h < 0) { m.makeScale(0, 0, 0); trees.setMatrixAt(i, m); continue; }
      const k = 0.7 + rnd(i, 3) * 0.8;
      m.compose(toV3(e, n, h, p), q, s.set(k, k, k));
      trees.setMatrixAt(i, m);
    }
    this.scene.add(trees);
    // Buildings
    const boxGeo = new THREE.BoxGeometry(1, 1, 1);
    boxGeo.translate(0, 0.5, 0);
    const houses = new THREE.InstancedMesh(boxGeo, mat(0x9a9384, { metalness: 0 }), t.houses);
    for (let i = 0; i < t.houses; i++) {
      const r = 450 + rnd(i, 11) * (kind === "urban" ? 4500 : 5000), a = rnd(i, 12) * Math.PI * 2;
      const e = Math.sin(a) * r, n = Math.cos(a) * r, h = terrainHeight(e, n, kind);
      if (kind === "coastal" && h < 0) { m.makeScale(0, 0, 0); houses.setMatrixAt(i, m); continue; }
      const w = 8 + rnd(i, 13) * 18, d = 8 + rnd(i, 14) * 18;
      const ht = kind === "urban" ? 6 + rnd(i, 15) * 16 : 4 + rnd(i, 15) * 4;
      q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), rnd(i, 16) * Math.PI);
      m.compose(toV3(e, n, h - 0.5, p), q, s.set(w, ht, d));
      houses.setMatrixAt(i, m);
    }
    this.scene.add(houses);
  }

  _post(height) {
    const g = new THREE.Group();
    const steel = mat(0x8a9097), olive = mat(0x4f5a3a, { metalness: 0 });
    const shelter = new THREE.Mesh(new THREE.BoxGeometry(4, 2.6, 3), olive);
    shelter.position.set(-3.5, 1.3, 1.5);
    g.add(shelter);
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.18, height, 10), steel);
    mast.position.y = height / 2;
    g.add(mast);
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.35, 0.4), mat(0x2b2f34));
    head.position.y = height + 0.2;
    g.add(head);
    const radar = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.8, 0.12), steel);
    radar.position.set(0, height - 0.9, 0);
    g.add(radar);
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

  // ── Per-update sync from the simulation state ──
  sync(entities, now) {
    const seen = new Set();
    for (const s of entities) {
      seen.add(s.id);
      let o = this.ents.get(s.id);
      if (!o) {
        o = buildModel(s.label);
        o.p = new THREE.Vector3(); o.v = new THREE.Vector3(); o.trail = [];
        const tg = new THREE.BufferGeometry();
        tg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(3 * 240), 3));
        tg.setDrawRange(0, 0);
        o.trailLine = new THREE.Line(tg, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.5, depthTest: false }));
        o.trailLine.renderOrder = 9;
        o.trailT = -1;
        this.scene.add(o.group, o.trailLine);
        this.ents.set(s.id, o);
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
  }

  setTarget(az, el) { this.target.az = az; this.target.el = el; }
  setFov(fov) { this.fov = fov; }
  setFogBoost(on) { if (this.scene.fog) this.scene.fog.density = this.baseDensity + (on ? 0.0012 : 0); }

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
    // Entities: dead-reckon from the last update so motion is smooth at 60 fps
    for (const o of this.ents.values()) {
      const age = Math.min(0.6, (now - o.t0) / 1000);
      const e = o.p.x + o.v.x * age, n = o.p.y + o.v.y * age, u = o.p.z + o.v.z * age;
      toV3(e, n, u, o.group.position);
      const sp = Math.hypot(o.v.x, o.v.y);
      if (sp > 0.3) o.group.rotation.y = -Math.atan2(o.v.x, o.v.y);
      const base = o.label === "aircraft" ? 15 : 1;
      o.group.scale.setScalar(base * (this.mode === "overview" ? OVERVIEW_SCALE[o.label] : 1));
      for (const r of o.rotors) r.rotation.y += dt * 60;
      for (const w of o.wings) w.pivot.rotation.z = w.side * Math.sin(now / 1000 * 9 + o.p.x) * 0.6;
      o.trailLine.visible = this.mode === "overview";
      o.trailLine.material.color.set(o.hostile === true ? 0xff5a4a : o.hostile === false ? 0x6fb6ff : 0xffffff);
    }
    if (this.radarHead) this.radarHead.rotation.y = now / 1000 * Math.PI * 2;
    if (this.postGroup) {
      this.postGroup.visible = this.mode === "overview";      // the day camera is mounted on the mast
      this.postGroup.scale.setScalar(12);
    }

    // EO camera slews towards where the post's camera is pointed
    let daz = ((this.target.az - this.look.az + 540) % 360) - 180;
    const k = Math.min(1, dt * 4);
    this.look.az = (this.look.az + daz * k + 360) % 360;
    this.look.el += (this.target.el - this.look.el) * k;
    this.eo.position.set(0, this.cameraHeight, 0);      // same height the simulation aims from
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
