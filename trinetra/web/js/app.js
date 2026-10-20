// TRINETRA — trainer page. The Python simulation is the source of truth:
// this page draws its state (streamed ~10 times a second) and sends the
// trainee's decisions back. Nothing is scored here.

import { World3D } from "./world3d.js";
import { RadarView } from "./radar.js";

const $ = (id) => document.getElementById(id);
const ZOOMS = [{ label: "Wide", fov: 46 }, { label: "×4", fov: 11.5 }, { label: "×15", fov: 3.1 },
               { label: "×40", fov: 1.15 }, { label: "×100", fov: 0.46 }];
const TYPES = [["quad", "Quadcopter"], ["hexa", "Hexacopter"], ["fixed_wing", "Fixed-wing drone"],
               ["fpv", "FPV racing drone"], ["bird", "Bird"], ["aircraft", "Aircraft"]];
const TYPE_NAME = Object.fromEntries(TYPES);
const RESPONSES = [
  ["monitor", "Keep watching", ""], ["alert_qrt", "Alert reaction team", ""],
  ["hand_off", "Hand over", "to the next unit"], ["ignore", "Ignore", ""],
  ["simulated_soft_kill", "Soft kill", "simulated jam / takeover"], ["simulated_hard_kill", "Hard kill", "simulated, click twice"],
];
const RESP_NAME = Object.fromEntries(RESPONSES.map(([k, v]) => [k, v]));
const STATUS_TEXT = { unknown: "Not identified", hostile: "Hostile", not_hostile: "Not hostile", down: "Down" };
const STATUS_VAR = { unknown: "--amber", hostile: "--red", not_hostile: "--blue", down: "--muted" };
const DEGRADE_TEXT = {
  "radar:jamming": "Radar jammed", "radar:dropout": "Radar signal lost", "radar:noise": "Radar noisy",
  "ir:noise": "Heat camera noisy", "ir:dropout": "Heat camera lost", "ir:fog": "Fog",
  "eo:jamming": "Day camera jammed", "eo:dropout": "Day camera lost", "eo:noise": "Day camera noisy",
  "eo:glare": "Sun glare", "eo:fog": "Fog",
};
const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
const compass = (b) => COMPASS[Math.floor((((b % 360) + 360) % 360 + 22.5) / 45) % 8];
const km = (m) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`);
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const ICON = {
  quad: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="5" cy="5" r="3"/><circle cx="19" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><path d="M7 7l3 3m4 0l3-3M7 17l3-3m4 0l3 3"/><rect x="10" y="10" width="4" height="4" rx="1"/></svg>',
  hexa: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="3.5" r="2.3"/><circle cx="12" cy="20.5" r="2.3"/><circle cx="4" cy="8" r="2.3"/><circle cx="20" cy="8" r="2.3"/><circle cx="4" cy="16" r="2.3"/><circle cx="20" cy="16" r="2.3"/><circle cx="12" cy="12" r="2.2"/></svg>',
  fixed_wing: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 3v18M2 10h20M8 19h8"/></svg>',
  fpv: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="6" cy="7" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="6" cy="17" r="2.5"/><circle cx="18" cy="17" r="2.5"/><path d="M8 9l8 6m0-6l-8 6"/><path d="M12 3l2 3h-4z" fill="currentColor"/></svg>',
  bird: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M2 9c4-1 7 1 10 5 3-4 6-6 10-5"/></svg>',
  aircraft: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 2c1 0 1.5 1 1.5 2v5l8 4v2l-8-2v5l2.5 2v1.5L12 20l-4 1.5V20l2.5-2v-5l-8 2v-2l8-4V4c0-1 .5-2 1.5-2z"/></svg>',
};

// ── Page state ──
let st = null, stamp = 0;
let scenarios = [], chosen = null, lastStart = null;
const pending = new Map();            // contact id -> type picked but not yet submitted
let hardArmed = { id: null, until: 0 };
let endArmed = 0;
let lastMsg = 0, zoomI = 0, view = "camera";
let actionsKey = "", scoreShown = false;

async function post(action) {
  try {
    const r = await fetch("/api/action", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(action) });
    return await r.json();
  } catch (e) {
    toast("Could not reach the simulator. Is it still running?", "error");
    return { ok: false };
  }
}

// ── Start screen ──
async function loadMenu() {
  scenarios = await (await fetch("/api/scenarios")).json();
  const list = $("scenario-list");
  list.innerHTML = "";
  for (const s of scenarios) {
    const b = document.createElement("button");
    b.className = "scn";
    b.innerHTML = `<h3>${s.title}</h3><p>${s.briefing}</p>
      <div class="chips"><span class="chip">${s.terrain}</span><span class="chip">${s.time_of_day}</span>${s.duration_s ? `<span class="chip">${mmss(s.duration_s)}</span>` : ""}</div>`;
    b.addEventListener("click", () => {
      chosen = s.file;
      [...list.children].forEach((c) => c.classList.toggle("sel", c === b));
      $("start-btn").disabled = false;
    });
    list.appendChild(b);
  }
  if (!chosen && list.firstElementChild) list.firstElementChild.click();
}
$("start-btn").addEventListener("click", async () => {
  const mode = document.querySelector('input[name="mode"]:checked').value;
  lastStart = { scenario: chosen, mode };
  pending.clear(); scoreShown = false; alerted.clear();
  await post({ type: "start", ...lastStart });
});

// ── 3D world, radar ──
const world = new World3D($("gl"));
const radar = new RadarView($("radar"), (id) => select(id));
const overlay = $("overlay"), octx = overlay.getContext("2d");
const stage = $("stage");
new ResizeObserver(() => {
  const w = stage.clientWidth, h = stage.clientHeight;
  if (!w || !h) return;
  world.resize(w, h);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  overlay.width = Math.round(w * dpr); overlay.height = Math.round(h * dpr);
}).observe(stage);

function select(id) { post({ type: "select", track_id: id }); }

// ── Stream ──
const es = new EventSource("/api/stream");
es.onmessage = (ev) => { st = JSON.parse(ev.data); stamp = performance.now(); onState(); };
es.onerror = () => setGuide({ warn: true, step: "Offline", text: "Lost the connection to the simulator. Check that the terminal running TRINETRA is still open." });

function onState() {
  const menu = st.status === "menu";
  $("menu").hidden = !menu;
  $("app").hidden = menu;
  if (menu) {
    $("briefing").hidden = true; $("score").hidden = true;
    if (!scenarios.length) loadMenu();
    return;
  }
  world.build(st.scenario, st.camera.height_m, { engage_m: st.rules.engage_m, r50_m: st.radar.r50_m });
  const factor = st.status === "running" ? st.speed : 0;
  world.sync(st.entities.map((e) => ({ ...e, ve: e.ve * factor, vn: e.vn * factor, vu: e.vu * factor })), stamp);
  world.setTarget(st.camera.az, st.camera.el);
  world.setFogBoost(st.degradations.some((d) => d.kind === "fog"));
  renderTopbar();
  setGuide(guidance());
  renderContacts();
  renderActions();
  renderCounters();
  renderAlert();
  for (const m of st.messages) if (m.id > lastMsg) { lastMsg = m.id; toast(m.text, m.kind); }
  renderBriefing();
  renderScore();
}

// ── Top bar ──
const speedSeg = $("speed-seg");
function renderTopbar() {
  $("mission-title").textContent = st.scenario.title;
  $("mission-title").title = st.scenario.title;
  $("mode-chip").textContent = st.mode === "guided" ? "Guided" : "Standard";
  $("clock").textContent = `${mmss(st.t)} / ${mmss(st.duration)}`;
  $("pause-btn").textContent = st.status === "paused" ? "Resume" : "Pause";
  $("instructor").checked = st.instructor;
  const chips = st.degradations.map((d) => DEGRADE_TEXT[`${d.sensor}:${d.kind}`] || `${d.sensor} ${d.kind}`);
  $("status-chips").innerHTML = [...new Set(chips)].map((c) => `<span class="chip bad">${c}</span>`).join("");
  if (speedSeg.childElementCount !== st.speeds.length) {
    speedSeg.innerHTML = st.speeds.map((s) => `<button data-speed="${s}">${s}×</button>`).join("");
  }
  [...speedSeg.children].forEach((b) => b.classList.toggle("on", Number(b.dataset.speed) === st.speed));
  if (endArmed && performance.now() > endArmed) { endArmed = 0; $("end-btn").textContent = "End mission"; }
}
speedSeg.addEventListener("click", (e) => { const s = e.target.dataset.speed; if (s) post({ type: "speed", value: Number(s) }); });
$("pause-btn").addEventListener("click", () => post({ type: "pause" }));
$("instructor").addEventListener("change", (e) => post({ type: "instructor", on: e.target.checked }));
$("end-btn").addEventListener("click", () => {
  if (endArmed && performance.now() < endArmed) { endArmed = 0; $("end-btn").textContent = "End mission"; post({ type: "end" }); return; }
  endArmed = performance.now() + 3000;
  $("end-btn").textContent = "Click again to end";
});
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && st && ["running", "paused"].includes(st.status) && !(e.target instanceof HTMLInputElement)) {
    e.preventDefault(); post({ type: "pause" });
  }
});

// ── Guidance ──
function movement(t) {
  if (t.closing > 1) return `coming closer at ${Math.round(t.closing)} m/s`;
  if (t.closing < -1) return `moving away`;
  return `crossing at ${Math.round(t.speed)} m/s`;
}
function cue(t) {
  if (t.speed > 45) return "Hint: very fast, more like an aircraft.";
  if (t.closing > 8) return `Hint: it is flying straight at you at ${Math.round(t.closing)} m/s, which birds rarely do.`;
  if (t.speed < 12 && Math.abs(t.closing) < 6) return "Hint: slow and not heading for you, which could be a bird.";
  return "";
}
function ruleHint(t) {
  const R = st.rules;
  if (t.hostile === false) return "Rule: not hostile → Keep watching or Ignore.";
  if (t.range > R.engage_m) return "Rule: hostile and more than 1 km away → Alert reaction team.";
  if (t.closing > R.approach_mps) return "Rule: hostile, inside 1 km and coming closer → Soft kill. Hard kill only if that fails.";
  return "Rule: hostile, inside 1 km but not coming closer → Hand over.";
}
function guidance() {
  const guided = st.mode === "guided";
  if (st.status === "briefing") return { step: "Briefing", text: "Read the briefing, then press Begin mission." };
  if (st.status === "done") return { step: "Finished", text: "Mission complete. See your score." };
  if (st.status === "paused") return { step: "Paused", text: "Press Resume (or Space) to continue." };
  const tr = st.tracks, sel = tr.find((t) => t.id === st.selected);
  if (!tr.length) {
    if (st.radar.status !== "ok") return { warn: true, step: "Radar down", text: "The radar cannot see right now. Keep the camera on the last direction you saw a threat (drag the view) until it recovers." };
    return { step: "Watch", text: "No contacts yet. They will appear on the radar (right) as numbered circles." };
  }
  if (!sel) {
    const todo = tr.find((t) => t.status === "unknown") || tr.find((t) => t.status === "hostile" && !t.actions.length);
    if (todo) return { step: "Select", text: `Contact ${todo.id} is ${km(todo.range)} to the ${todo.direction}${todo.status === "unknown" ? " and not identified yet" : ""}. Click it on the radar or in the Contacts list.` };
    return { step: "Watch", text: "Every contact is handled. Keep watching for new ones." };
  }
  if (sel.status === "down") return { step: "Done", text: `Contact ${sel.id} is down. Select the next contact.` };
  if (!sel.label && !pending.get(sel.id)) {
    if (!st.camera.locked && sel.range > st.camera.lock_range_m) {
      return { step: "1 · Identify", text: `Contact ${sel.id} is ${km(sel.range)} away, too far for the camera to lock on (it locks inside ${km(st.camera.lock_range_m)}). Judge it from the radar for now, or wait. ${guided ? cue(sel) : ""}` };
    }
    const zoomTip = zoomI < 3 ? " Zoom in (×40 or ×100) to see it clearly." : "";
    return { step: "1 · Identify", text: `Look at Contact ${sel.id} in the middle of the camera view.${zoomTip} What is it? Pick a type below. ${guided ? cue(sel) : ""}` };
  }
  if (sel.hostile === null || sel.hostile === undefined) return { step: "2 · Threat?", text: `Is Contact ${sel.id} a threat? Choose Hostile or Not hostile.` };
  if (!sel.actions.length) return { step: "3 · Respond", text: guided ? ruleHint(sel) : `Choose what to do about Contact ${sel.id}.` };
  const kills = sel.actions.some((a) => a.includes("kill"));
  if (sel.hostile && sel.range <= st.rules.engage_m && sel.closing > st.rules.approach_mps && !kills) {
    return { warn: true, step: "Act now", text: `Contact ${sel.id} is inside 1 km and coming closer.${guided ? " Rule: Soft kill." : ""}` };
  }
  const other = tr.find((t) => t.id !== sel.id && t.status === "unknown");
  if (other) return { step: "Next", text: `Contact ${other.id} is not identified yet. Select it.` };
  if (sel.hostile && sel.range > st.rules.engage_m) return { step: "Watch", text: `Keep watching Contact ${sel.id}. If it comes inside 1 km and keeps closing, engage it.` };
  return { step: "Watch", text: `Keep watching for new contacts.` };
}
function setGuide(g) {
  $("guide").classList.toggle("warn", !!g.warn);
  $("guide-step").textContent = g.step;
  $("guide-text").textContent = g.text;
}

// ── Contacts list ──
const contactEls = new Map();
function renderContacts() {
  const box = $("contacts");
  $("contacts-count").textContent = st.tracks.length ? `${st.tracks.length} on radar` : "";
  if (!st.tracks.length) {
    if (!box.querySelector(".none")) box.innerHTML = '<div class="none">Nothing on the radar yet.</div>';
    contactEls.clear();
    return;
  }
  box.querySelector(".none")?.remove();
  const ids = new Set(st.tracks.map((t) => t.id));
  for (const [id, el] of contactEls) if (!ids.has(id)) { el.remove(); contactEls.delete(id); }
  for (const t of st.tracks) {
    let el = contactEls.get(t.id);
    if (!el) {
      el = document.createElement("button");
      el.className = "contact";
      el.innerHTML = '<span class="num"></span><span class="line1"><b></b><span class="st"></span></span><span class="line2"></span>';
      el.addEventListener("click", () => select(t.id));
      contactEls.set(t.id, el);
      box.appendChild(el);
    }
    el.classList.toggle("sel", t.id === st.selected);
    const num = el.querySelector(".num");
    num.textContent = t.id;
    num.style.background = css(STATUS_VAR[t.status]);
    el.querySelector("b").textContent = `Contact ${t.id}`;
    const stEl = el.querySelector(".st");
    stEl.className = `st ${t.status}`;
    stEl.textContent = t.label && t.status !== "down" ? `${TYPE_NAME[t.label]}${t.hostile ? ", hostile" : ""}` : STATUS_TEXT[t.status];
    const last = t.actions.length ? ` · ${RESP_NAME[t.actions[t.actions.length - 1]]}` : "";
    el.querySelector(".line2").textContent = `${km(t.range)} ${t.direction} · ${movement(t)}${last}`;
  }
}

// ── Action panel ──
function renderActions() {
  const panel = $("actions");
  const sel = st.tracks.find((t) => t.id === st.selected);
  if (!sel || !["running", "paused"].includes(st.status)) {
    const key = "empty";
    if (actionsKey !== key) {
      actionsKey = key;
      panel.innerHTML = '<div class="empty">Select a contact on the radar, in the Contacts list or in the camera view to act on it.</div>';
    }
    return;
  }
  const label = pending.get(sel.id) || sel.label;
  const inRange = sel.range <= st.rules.effect_m;
  const armed = hardArmed.id === sel.id && performance.now() < hardArmed.until;
  const key = JSON.stringify([sel.id, sel.status, sel.label, sel.hostile, sel.actions, label, inRange, armed, st.mode]);
  if (key !== actionsKey) {
    actionsKey = key;
    const down = sel.status === "down";
    const identified = sel.hostile !== null && sel.hostile !== undefined;
    const typeBtns = TYPES.map(([k, name]) =>
      `<button class="choice ${label === k ? "on" : ""}" data-type="${k}" ${down ? "disabled" : ""}>${ICON[k]}<span>${name}</span></button>`).join("");
    const threat = `
      <button class="choice red ${sel.hostile === true ? "on" : ""}" data-threat="1" ${!label || down ? "disabled" : ""}><span>Hostile</span></button>
      <button class="choice blue ${sel.hostile === false ? "on" : ""}" data-threat="0" ${!label || down ? "disabled" : ""}><span>Not hostile</span></button>`;
    const resp = RESPONSES.map(([k, name, sub]) => {
      const kill = k.includes("kill");
      let disabled = down || !identified, why = "";
      if (!identified && !down) why = "identify it first";
      if (kill && !inRange && !down) { disabled = true; why = `too far (${km(sel.range)})`; }
      const isArmed = k === "simulated_hard_kill" && armed;
      const done = sel.actions.includes(k);
      return `<button class="choice ${kill ? "kill" : ""} ${done ? "done" : ""} ${isArmed ? "confirm" : ""}" data-resp="${k}" ${disabled ? "disabled" : ""}>
        <span>${isArmed ? "Click again to confirm" : name}<small>${why || sub}</small></span></button>`;
    }).join("");
    const s1 = sel.label ? "done" : "current", s2 = identified ? "done" : label ? "current" : "", s3 = identified && !down ? (sel.actions.length ? "done" : "current") : "";
    panel.innerHTML = `
      <div class="act-head"><h3>Contact ${sel.id}</h3><span class="facts" id="act-facts"></span>
        <span class="st ${sel.status}">${STATUS_TEXT[sel.status]}</span></div>
      <div class="steps">
        <div class="step ${s1}"><span class="step-title">1 · What is it?</span><div class="choices">${typeBtns}</div></div>
        <div class="step ${s2}"><span class="step-title">2 · Is it a threat?</span><div class="choices two">${threat}</div></div>
        <div class="step ${s3}"><span class="step-title">3 · What do you do?</span><div class="choices">${resp}</div>
          ${st.mode === "guided" && identified && !down ? `<span class="rule-hint" id="rule-hint"></span>` : ""}</div>
      </div>`;
  }
  const facts = $("act-facts");
  if (facts) facts.textContent = `${km(sel.range)} to the ${sel.direction} · ${movement(sel)}`;
  const hint = $("rule-hint");
  if (hint) hint.textContent = ruleHint(sel);
}
$("actions").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b || b.disabled || !st) return;
  const sel = st.tracks.find((t) => t.id === st.selected);
  if (!sel) return;
  if (b.dataset.type) {
    pending.set(sel.id, b.dataset.type);
    if (sel.hostile !== null && sel.hostile !== undefined) {           // re-identifying: keep the threat call
      await post({ type: "classify", label: b.dataset.type, hostile: sel.hostile });
      pending.delete(sel.id);
    }
    actionsKey = ""; renderActions(); setGuide(guidance());
  } else if (b.dataset.threat) {
    const label = pending.get(sel.id) || sel.label;
    await post({ type: "classify", label, hostile: b.dataset.threat === "1" });
    pending.delete(sel.id);
  } else if (b.dataset.resp) {
    const k = b.dataset.resp;
    if (k === "simulated_hard_kill" && !(hardArmed.id === sel.id && performance.now() < hardArmed.until)) {
      hardArmed = { id: sel.id, until: performance.now() + 3000 };
      actionsKey = ""; renderActions();
      setTimeout(() => { actionsKey = ""; st && renderActions(); }, 3100);
      return;
    }
    hardArmed = { id: null, until: 0 };
    await post({ type: "respond", action: k });
  }
});

// ── Counters and threat alert ──
let soundOn = true, audioCtx = null;
const alerted = new Set();
$("sound-btn").addEventListener("click", () => {
  soundOn = !soundOn;
  $("sound-btn").textContent = soundOn ? "Sound on" : "Sound off";
  $("sound-btn").setAttribute("aria-pressed", String(soundOn));
});
function beep() {
  if (!soundOn) return;
  try {
    audioCtx = audioCtx || new AudioContext();
    const t0 = audioCtx.currentTime;
    for (let i = 0; i < 2; i++) {
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type = "square"; o.frequency.value = 880;
      g.gain.setValueAtTime(0.0001, t0 + i * 0.22);
      g.gain.exponentialRampToValueAtTime(0.08, t0 + i * 0.22 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + i * 0.22 + 0.16);
      o.connect(g).connect(audioCtx.destination);
      o.start(t0 + i * 0.22); o.stop(t0 + i * 0.22 + 0.18);
    }
  } catch { /* audio is a nice-to-have */ }
}
function renderCounters() {
  const T = st.tracks;
  const n = (s) => T.filter((t) => t.status === s).length;
  const chip = (cls, v, label) => `<span class="chip ${v ? cls : ""}"><b>${v}</b> ${label}</span>`;
  $("counters").innerHTML = chip("", T.length, "on radar") + chip("warn", n("unknown"), "not identified") +
    chip("bad", n("hostile"), "hostile") + chip("", n("down"), "down");
}
// A threat is anything not cleared as harmless that is inside the engage zone and closing
function threats() {
  if (!["running", "paused"].includes(st.status)) return [];
  return st.tracks.filter((t) => (t.status === "unknown" || t.status === "hostile") &&
    t.range <= st.rules.engage_m && t.closing > st.rules.approach_mps &&
    !t.actions.some((a) => a.includes("kill")));
}
function renderAlert() {
  const list = threats();
  const el = $("alert");
  el.hidden = !list.length;
  if (!list.length) return;
  const t = list.sort((a, b) => a.range - b.range)[0];
  el.textContent = `⚠ CONTACT ${t.id} INSIDE 1 KM AND CLOSING · ${km(t.range)} ${t.direction.toUpperCase()}` +
    (list.length > 1 ? ` · +${list.length - 1} MORE` : "");
  for (const x of list) if (!alerted.has(x.id)) { alerted.add(x.id); beep(); }
}

// ── Day / thermal ──
let sensor = "day";
$("sensor").addEventListener("click", (e) => {
  const s = e.target.dataset.sensor;
  if (!s) return;
  sensor = s;
  world.setSensor(s);
  $("gl").classList.toggle("thermal", s === "thermal" && view === "camera");
  [...$("sensor").children].forEach((b) => b.classList.toggle("on", b.dataset.sensor === s));
});

// ── Toasts ──
function toast(text, kind = "info") {
  const box = $("toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = text;
  box.prepend(el);
  while (box.children.length > 4) box.lastChild.remove();
  setTimeout(() => el.remove(), 5000);
}

// ── Briefing and score ──
function renderBriefing() {
  const show = st.status === "briefing";
  $("briefing").hidden = !show;
  if (!show) return;
  $("brief-title").textContent = st.scenario.title;
  $("brief-text").textContent = st.scenario.briefing;
  $("brief-chips").innerHTML = [st.scenario.terrain, st.scenario.time_of_day, mmss(st.duration), st.mode === "guided" ? "Guided" : "Standard"]
    .map((c) => `<span class="chip">${c}</span>`).join("");
}
$("brief-go").addEventListener("click", () => post({ type: "begin" }));
$("brief-back").addEventListener("click", () => post({ type: "menu" }));

const NOTE_WORDS = [[/simulated_soft_kill/g, "soft kill"], [/simulated_hard_kill/g, "hard kill"], [/alert_qrt/g, "alert reaction team"],
  [/hand_off/g, "hand over"], [/fixed_wing/g, "fixed-wing drone"], [/\bquad\b/g, "quadcopter"], [/\bhexa\b/g, "hexacopter"],
  [/hostile close approaching/g, "hostile, inside 1 km, coming closer"], [/hostile close holding/g, "hostile, inside 1 km, not closing"],
  [/hostile far/g, "hostile, more than 1 km away"], [/earned ([0-9.]+)/g, (m, v) => `scored ${Math.round(Number(v) * 100)}%`]];
function plainNote(n) { return NOTE_WORDS.reduce((s, [re, rep]) => s.replace(re, rep), n); }

function renderScore() {
  const show = st.status === "done" && !!st.score;
  $("score").hidden = !show;
  if (!show || scoreShown) return;
  scoreShown = true;
  const s = st.score;
  $("score-total").textContent = Math.round(s.total * 100);
  const parts = [["detect", "Spotting contacts quickly", 30], ["classify", "Identifying them correctly", 25],
                 ["respond", "Right response under the rules", 30], ["false_alarms", "Avoiding mistakes and misses", 15]];
  $("score-bars").innerHTML = parts.map(([k, name, w]) => {
    const v = s[k], pct = v == null ? null : Math.round(v * 100);
    const cls = pct == null ? "" : pct >= 75 ? "" : pct >= 40 ? "mid" : "low";
    return `<div class="bar"><span>${name} <small>${w}% of score</small></span>
      <div class="bar-track"><div class="bar-fill ${cls}" style="width:${pct ?? 0}%"></div></div><span class="v">${pct ?? "n/a"}</span></div>`;
  }).join("");
  $("score-notes").innerHTML = s.notes.length ? s.notes.map((n) => `<li>${plainNote(n)}</li>`).join("")
    : "<li>Nothing. Every hostile was spotted, identified and handled under the rules.</li>";
  $("score-log").textContent = `Full record of this mission: ${st.log}`;
  renderAAR();
}

// ── After-action timeline ──
const GRADE = { good: "var(--green)", partial: "var(--amber)", bad: "var(--red)", info: "var(--ink)" };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
async function renderAAR() {
  $("aar-timeline").innerHTML = "";
  $("aar-stats").innerHTML = "";
  let tl;
  try { tl = await (await fetch("/api/aar")).json(); } catch { return; }
  if (!tl) return;
  const rows = [...tl.rows].sort((a, b) => (b.hostile - a.hostile) || a.start - b.start);
  if (tl.clutter.length) rows.push({ id: "Clutter", name: "radar false alarms", hostile: false, start: 0, end: tl.duration, marks: tl.clutter, clutter: true });
  const hostiles = tl.rows.filter((r) => r.hostile);
  const stopped = hostiles.filter((r) => r.end_reason === "neutralised_simulated").length;
  const reached = hostiles.filter((r) => r.end_reason === "arrived").length;
  const marks = rows.flatMap((r) => r.marks);
  const wrong = marks.filter((m) => m.grade === "bad").length;
  const ttds = hostiles.map((r) => r.time_to_detect_s).filter((v) => v != null);
  const stat = (v, label, cls = "") => `<div class="stat ${cls}"><b>${v}</b><span>${label}</span></div>`;
  $("aar-stats").innerHTML =
    stat(`${stopped}/${hostiles.length}`, "hostiles stopped", stopped === hostiles.length && hostiles.length ? "good" : "") +
    stat(reached, "reached your post", reached ? "bad" : "good") +
    stat(ttds.length ? `${(ttds.reduce((a, b) => a + b, 0) / ttds.length).toFixed(1)} s` : "–", "average time to spot") +
    stat(wrong, "wrong decisions", wrong ? "bad" : "good");

  const W = 980, LW = 190, RH = 38, TOP = 30, H = TOP + rows.length * RH + 8;
  const dur = Math.max(tl.duration, 1), X = (t) => LW + (t / dur) * (W - LW - 110);
  const step = dur > 150 ? 30 : 15;
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Mission timeline">`;
  for (let t = 0; t <= dur + 0.01; t += step) {
    svg += `<line x1="${X(t)}" x2="${X(t)}" y1="${TOP - 6}" y2="${H - 6}" stroke="var(--grid)"/>` +
      `<text x="${X(t)}" y="${TOP - 12}" fill="var(--muted)" font-size="11" text-anchor="middle">${mmss(t)}</text>`;
  }
  rows.forEach((r, i) => {
    const y = TOP + i * RH, mid = y + RH / 2;
    const col = r.clutter ? "var(--muted)" : r.hostile ? "var(--red)" : "var(--blue)";
    svg += `<text x="12" y="${mid - 3}" fill="var(--ink)" font-size="13" font-weight="600">${esc(r.id)}</text>` +
      `<text x="12" y="${mid + 12}" fill="var(--muted)" font-size="11">${esc(r.name)}${r.hostile ? " · hostile" : ""}</text>` +
      `<rect x="${X(r.start)}" y="${mid - 4}" width="${Math.max(2, X(r.end) - X(r.start))}" height="8" rx="4" fill="${col}" opacity="0.35"/>`;
    if (r.detectable != null) svg += `<line x1="${X(r.detectable)}" x2="${X(r.detectable)}" y1="${mid - 11}" y2="${mid + 11}" stroke="var(--amber)" stroke-width="2"><title>Became detectable at ${r.detectable.toFixed(1)} s</title></line>`;
    if (r.end_reason === "neutralised_simulated") svg += `<text x="${X(r.end) + 6}" y="${mid + 4}" fill="var(--green)" font-size="11" font-weight="700">DOWN</text>`;
    if (r.end_reason === "arrived") svg += `<text x="${X(r.end) + 6}" y="${mid + 4}" fill="var(--red)" font-size="11" font-weight="700">REACHED POST</text>`;
    for (const m of r.marks) {
      const x = X(m.t), c = GRADE[m.grade];
      const tip = `<title>${mmss(m.t)}  ${esc(m.text)}</title>`;
      if (m.kind === "select") svg += `<path d="M${x} ${mid - 5}l5 5-5 5-5-5z" fill="${c}">${tip}</path>`;
      else if (m.kind === "classify") svg += `<circle cx="${x}" cy="${mid}" r="5.5" fill="${c}" stroke="var(--bg)" stroke-width="1.5">${tip}</circle>`;
      else svg += `<path d="M${x} ${mid - 7}l6.5 11h-13z" fill="${c}" stroke="var(--bg)" stroke-width="1.5">${tip}</path>`;
    }
  });
  svg += "</svg>";
  $("aar-timeline").innerHTML = svg;
}
$("score-again").addEventListener("click", async () => {
  if (!lastStart) {
    if (!scenarios.length) scenarios = await (await fetch("/api/scenarios")).json();
    const s = scenarios.find((x) => x.id === st.scenario.id);
    lastStart = { scenario: s ? s.file : scenarios[0].file, mode: st.mode };
  }
  pending.clear(); scoreShown = false; alerted.clear();
  post({ type: "start", ...lastStart });
});
$("score-menu").addEventListener("click", () => { scoreShown = false; post({ type: "menu" }); });

// ── View tabs, zoom, drag ──
const zoomBox = $("zoom");
zoomBox.innerHTML = ZOOMS.map((z, i) => `<button data-z="${i}">${z.label}</button>`).join("");
function setZoom(i) {
  zoomI = Math.max(0, Math.min(ZOOMS.length - 1, i));
  world.setFov(ZOOMS[zoomI].fov);
  [...zoomBox.children].forEach((b, j) => b.classList.toggle("on", j === zoomI));
}
setZoom(0);
zoomBox.addEventListener("click", (e) => { const z = e.target.dataset.z; if (z !== undefined) setZoom(Number(z)); });
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  view = t.dataset.view;
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  world.setMode(view);
  $("cam-controls").hidden = view !== "camera";
  $("gl").classList.toggle("thermal", sensor === "thermal" && view === "camera");
  $("stage-help").textContent = view === "camera" ? "Drag to look around · scroll to zoom"
    : "Drag to turn the map · scroll to zoom · aircraft are drawn larger than life so you can see them";
}));

let drag = null, camQueue = { daz: 0, del: 0 }, camTimer = null;
function flushCamera() {
  camTimer = null;
  if (Math.abs(camQueue.daz) + Math.abs(camQueue.del) < 0.01) return;
  const q = camQueue; camQueue = { daz: 0, del: 0 };
  post({ type: "camera", daz: q.daz, del: q.del });
}
stage.addEventListener("pointerdown", (e) => {
  if (e.target.closest("button")) return;
  drag = { x: e.clientX, y: e.clientY, moved: 0 };
  stage.setPointerCapture(e.pointerId);
});
stage.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.x = e.clientX; drag.y = e.clientY; drag.moved += Math.abs(dx) + Math.abs(dy);
  if (view === "camera") {
    const degPx = world.eo.fov / stage.clientHeight;
    camQueue.daz -= dx * degPx; camQueue.del += dy * degPx;
    world.target.az -= dx * degPx; world.target.el += dy * degPx;   // feels instant; the server confirms
    if (!camTimer) camTimer = setTimeout(flushCamera, 80);
  } else {
    world.orbit.az -= dx * 0.3;
    world.orbit.el = Math.max(10, Math.min(85, world.orbit.el + dy * 0.2));
  }
});
stage.addEventListener("pointerup", (e) => {
  if (drag && drag.moved < 5 && view === "camera") pickInCamera(e);
  drag = null;
});
stage.addEventListener("wheel", (e) => {
  e.preventDefault();
  if (view === "camera") setZoom(zoomI + (e.deltaY < 0 ? 1 : -1));
  else world.orbit.r = Math.max(1200, Math.min(14000, world.orbit.r * (e.deltaY < 0 ? 0.88 : 1.14)));
}, { passive: false });

let boxes = [];   // contact squares drawn in the camera view, for clicking
function pickInCamera(e) {
  const r = stage.getBoundingClientRect();
  const x = e.clientX - r.left, y = e.clientY - r.top;
  const hit = boxes.find((b) => Math.abs(b.x - x) < 26 && Math.abs(b.y - y) < 26);
  if (hit) select(hit.id);
}

// ── Overlay ──
let grain = null;
function grainTile() {
  if (grain) return grain;
  grain = document.createElement("canvas");
  grain.width = grain.height = 200;
  const g = grain.getContext("2d"), img = g.createImageData(200, 200);
  for (let i = 0; i < img.data.length; i += 4) { const v = Math.random() * 255; img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255; }
  g.putImageData(img, 0, 0);
  return grain;
}
function drawGrain(ctx, w, h, alpha) {
  const t = grainTile();
  ctx.save();
  ctx.globalAlpha = alpha;
  const ox = Math.random() * 200, oy = Math.random() * 200;
  ctx.translate(-ox, -oy);
  ctx.fillStyle = ctx.createPattern(t, "repeat");
  ctx.fillRect(0, 0, w + 200, h + 200);
  ctx.restore();
}
function brackets(ctx, x, y, s, color, width) {
  const c = s * 0.35;
  ctx.strokeStyle = color; ctx.lineWidth = width;
  ctx.beginPath();
  for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    ctx.moveTo(x + sx * s, y + sy * (s - c)); ctx.lineTo(x + sx * s, y + sy * s); ctx.lineTo(x + sx * (s - c), y + sy * s);
  }
  ctx.stroke();
}
function label(ctx, text, x, y, color) {
  ctx.font = "600 12px Segoe UI, system-ui, sans-serif";
  const w = ctx.measureText(text).width + 10;
  ctx.fillStyle = "rgba(8,12,16,0.72)";
  ctx.fillRect(x, y - 9, w, 18);
  ctx.fillStyle = color;
  ctx.textBaseline = "middle";
  ctx.fillText(text, x + 5, y);
}
// ── Camera HUD, styled after a surveillance camera feed ──
const HUD = "rgba(232,240,236,0.86)", HUD_DIM = "rgba(232,240,236,0.45)";
function tickStep(span) {
  for (const s of [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30]) if (span / s <= 14) return s;
  return 45;
}
function drawHud(ctx, w, h) {
  const az = world.look.az, el = world.look.el;
  const vfov = world.eo.fov, hfov = 2 * Math.atan(Math.tan(vfov * Math.PI / 360) * (w / h)) * 180 / Math.PI;
  const thermal = sensor === "thermal";
  ctx.save();
  ctx.font = "12px Cascadia Mono, Consolas, monospace";
  ctx.textBaseline = "middle";

  // corner frame of the feed
  ctx.strokeStyle = HUD_DIM; ctx.lineWidth = 2;
  const m = 14, L = 28;
  for (const [x, y, sx, sy] of [[m, m, 1, 1], [w - m, m, -1, 1], [m, h - m, 1, -1], [w - m, h - m, -1, -1]]) {
    ctx.beginPath(); ctx.moveTo(x, y + sy * L); ctx.lineTo(x, y); ctx.lineTo(x + sx * L, y); ctx.stroke();
  }

  // compass tape: ticks sit exactly over the directions they name
  const tapeW = Math.min(w - 620, 640), tx0 = (w - tapeW) / 2, ty = 26;
  if (tapeW > 160) {
    const pxPerDeg = w / hfov, step = tickStep(tapeW / pxPerDeg);
    ctx.fillStyle = "rgba(6,10,12,0.45)"; ctx.fillRect(tx0, ty - 14, tapeW, 30);
    ctx.save(); ctx.beginPath(); ctx.rect(tx0, ty - 14, tapeW, 30); ctx.clip();
    const half = tapeW / 2 / pxPerDeg;
    for (let d = Math.ceil((az - half) / step) * step; d <= az + half; d += step) {
      const x = w / 2 + (d - az) * pxPerDeg, dd = ((Math.round(d / step) * step) % 360 + 360) % 360;
      const major = Math.abs((d / (step * 2)) - Math.round(d / (step * 2))) < 1e-6;
      ctx.strokeStyle = HUD; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, ty + 16); ctx.lineTo(x, ty + (major ? 4 : 9)); ctx.stroke();
      if (major) {
        const card = { 0: "N", 90: "E", 180: "S", 270: "W" }[Math.round(dd * 10) / 10];
        ctx.fillStyle = card ? "#ffd27a" : HUD; ctx.textAlign = "center";
        ctx.fillText(card || (step < 1 ? dd.toFixed(1) : String(Math.round(dd)).padStart(3, "0")), x, ty - 4);
      }
    }
    ctx.restore();
    ctx.fillStyle = "#ffd27a";
    ctx.beginPath(); ctx.moveTo(w / 2 - 6, ty + 17); ctx.lineTo(w / 2 + 6, ty + 17); ctx.lineTo(w / 2, ty + 10); ctx.fill();
  }

  // elevation scale on the right
  const ex = w - 30, pxPerDegV = h / vfov, estep = tickStep(260 / pxPerDegV);
  ctx.strokeStyle = HUD; ctx.fillStyle = HUD; ctx.textAlign = "right";
  for (let d = Math.ceil((el - 130 / pxPerDegV) / estep) * estep; d <= el + 130 / pxPerDegV; d += estep) {
    const y = h / 2 - (d - el) * pxPerDegV;
    const major = Math.abs(d / (estep * 2) - Math.round(d / (estep * 2))) < 1e-6;
    ctx.beginPath(); ctx.moveTo(ex, y); ctx.lineTo(ex - (major ? 12 : 6), y); ctx.stroke();
    if (major) ctx.fillText(`${d > 0 ? "+" : ""}${estep < 1 ? d.toFixed(1) : Math.round(d)}`, ex - 16, y);
  }
  ctx.fillStyle = "#ffd27a";
  ctx.beginPath(); ctx.moveTo(ex + 2, h / 2); ctx.lineTo(ex + 10, h / 2 - 5); ctx.lineTo(ex + 10, h / 2 + 5); ctx.fill();

  // reticle with an open centre, so it never hides a small target
  ctx.strokeStyle = HUD; ctx.lineWidth = 1.2;
  ctx.beginPath();
  for (const [a, b] of [[-52, -30], [30, 52]]) { ctx.moveTo(w / 2 + a, h / 2); ctx.lineTo(w / 2 + b, h / 2); ctx.moveTo(w / 2, h / 2 + a); ctx.lineTo(w / 2, h / 2 + b); }
  ctx.stroke();

  // live indicator and mission clock, top right
  ctx.textAlign = "right";
  const blink = Math.floor(performance.now() / 600) % 2 === 0;
  ctx.fillStyle = blink ? "#ff4a3d" : "rgba(255,74,61,0.35)";
  ctx.beginPath(); ctx.arc(w - 112, 30, 5, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = HUD;
  ctx.fillText(`LIVE  T+${mmss(st.t)}`, w - 24, 30);

  // readout panel, bottom left
  const sel = st.tracks.find((t) => t.id === st.selected);
  const lines = [
    `${thermal ? "THERMAL  WHITE-HOT" : "DAY TV"}   FOV ${vfov < 2 ? vfov.toFixed(2) : vfov.toFixed(1)}°  ${ZOOMS[zoomI].label.toUpperCase()}`,
    `AZ ${az.toFixed(1).padStart(5, "0")}° ${compass(az).toUpperCase()}   EL ${el >= 0 ? "+" : ""}${el.toFixed(1)}°`,
    sel ? `TRACK  C${sel.id}  ${st.camera.locked ? "LOCKED" : "RADAR CUE"}` : "TRACK  NONE",
    sel ? `RANGE  ${(sel.range / 1000).toFixed(2)} KM   ${sel.closing > 1 ? `CLOSING ${Math.round(sel.closing)} M/S` : sel.closing < -1 ? "OPENING" : "CROSSING"}` : "",
  ].filter(Boolean);
  const bh = lines.length * 18 + 14;
  ctx.fillStyle = "rgba(6,10,12,0.5)"; ctx.fillRect(16, h - bh - 16, 330, bh);
  ctx.textAlign = "left";
  lines.forEach((ln, i) => {
    ctx.fillStyle = i === 2 && sel && st.camera.locked ? "#7dffb0" : HUD;
    ctx.fillText(ln, 26, h - bh - 16 + 16 + i * 18);
  });
  ctx.restore();
}

function drawOverlay() {
  const dpr = overlay.width / Math.max(1, stage.clientWidth);
  const w = stage.clientWidth, h = stage.clientHeight;
  const ctx = octx;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  boxes = [];
  const deg = (s, k) => st.degradations.some((d) => d.sensor === s && (!k || d.kind === k));

  if (view === "camera") {
    const lost = deg("eo", "dropout") || deg("eo", "jamming");
    if (st.scenario.time_of_day === "night") drawGrain(ctx, w, h, 0.10);
    if (deg("eo", "noise")) drawGrain(ctx, w, h, 0.22);
    if (deg("eo", "glare")) {
      const g = ctx.createRadialGradient(w * 0.8, h * 0.15, 10, w * 0.8, h * 0.15, w * 0.7);
      g.addColorStop(0, "rgba(255,250,235,0.95)"); g.addColorStop(1, "rgba(255,250,235,0)");
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    }
    if (lost) {
      drawGrain(ctx, w, h, 0.85);
      ctx.fillStyle = css("--red"); ctx.font = "700 22px Segoe UI, system-ui"; ctx.textAlign = "center";
      ctx.fillText("DAY CAMERA SIGNAL LOST", w / 2, h / 2);
      ctx.textAlign = "left";
      return;
    }
    drawHud(ctx, w, h);
    const az = world.look.az;
    // contacts (radar cues, height assumed)
    for (const t of st.tracks) {
      const sel = t.id === st.selected;
      const locked = sel && st.camera.locked;
      // A locked target is wherever the camera points: the centre of the view
      const p = locked ? { x: w / 2, y: h / 2 } : world.project(t.e, t.n, st.camera.assumed_alt_m, w, h);
      const color = css(STATUS_VAR[t.status]);
      if (!p || p.x < -20 || p.x > w + 20 || p.y < -20 || p.y > h + 20) {
        if (sel) {               // off screen: point the way
          const d = ((t.bearing - az + 540) % 360) - 180;
          const x = d < 0 ? 16 : w - 16;
          ctx.fillStyle = color; ctx.font = "700 14px Segoe UI, system-ui";
          ctx.textAlign = d < 0 ? "left" : "right";
          ctx.fillText(d < 0 ? `◀ Contact ${t.id}` : `Contact ${t.id} ▶`, x, h / 2);
          ctx.textAlign = "left";
        }
        continue;
      }
      const s = sel ? 30 : 17;
      // When the cameras are locked on, the target sits at the centre of the view
      const x = sel && st.camera.locked ? w / 2 : p.x, y = sel && st.camera.locked ? h / 2 : p.y;
      brackets(ctx, x, y, s, color, sel ? 2.5 : 1.5);
      const tag = sel ? (st.camera.locked ? " · camera locked on" : " · following radar") : "";
      label(ctx, `Contact ${t.id} · ${km(t.range)}${tag}`, x + s + 6, y - s + 6, color);
      boxes.push({ id: t.id, x, y });
    }
    if (st.instructor) {
      for (const en of st.entities) {
        const p = world.project(en.e, en.n, en.u, w, h);
        if (!p) continue;
        const color = en.hostile ? css("--red") : css("--blue");
        ctx.strokeStyle = color; ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.moveTo(p.x, p.y - 7); ctx.lineTo(p.x + 7, p.y); ctx.lineTo(p.x, p.y + 7); ctx.lineTo(p.x - 7, p.y); ctx.closePath(); ctx.stroke();
        ctx.fillStyle = color; ctx.font = "11px Segoe UI, system-ui";
        ctx.fillText(`${en.id} (${TYPE_NAME[en.label]})`, p.x + 10, p.y + 14);
      }
    }
  } else {
    const p0 = world.project(0, 0, 0, w, h);
    if (p0) label(ctx, "Your post", p0.x + 10, p0.y, css("--ink"));
    for (const t of st.tracks) {
      const p = world.project(t.e, t.n, st.camera.assumed_alt_m, w, h);
      if (!p) continue;
      const color = css(STATUS_VAR[t.status]);
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(p.x, p.y, t.id === st.selected ? 7 : 5, 0, Math.PI * 2); ctx.fill();
      label(ctx, `Contact ${t.id} · ${STATUS_TEXT[t.status]}`, p.x + 10, p.y - 10, color);
    }
    if (st.instructor) {
      for (const en of st.entities) {
        const p = world.project(en.e, en.n, en.u, w, h);
        if (!p) continue;
        label(ctx, `${en.id} · ${TYPE_NAME[en.label]}`, p.x + 10, p.y + 14, en.hostile ? css("--red") : css("--blue"));
      }
    }
    // label the engage ring on the side nearest the viewer, away from most traffic
    const oa = world.orbit.az * Math.PI / 180;
    const lr = world.project(Math.sin(oa) * st.rules.engage_m, Math.cos(oa) * st.rules.engage_m, 0, w, h);
    if (lr) label(ctx, "1 km engage zone", lr.x + 6, lr.y + 12, css("--red"));
  }
}

// ── Main loop ──
let lastFrame = performance.now();
function loop(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  if (st && st.status !== "menu" && st.scenario) {
    world.frame(now, dt);
    drawOverlay();
    radar.draw(st, now);
  }
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);

fetch("/api/state").then((r) => r.json()).then((s) => { st = s; stamp = performance.now(); onState(); });
