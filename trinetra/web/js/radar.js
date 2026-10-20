// TRINETRA — radar panel: a plain top-down map around the post.
// Contacts are numbered circles coloured by what the trainee has decided.

const STATUS_COLOR = { unknown: "--amber", hostile: "--red", not_hostile: "--blue", down: "--muted" };

export class RadarView {
  constructor(canvas, onPick) {
    this.c = canvas;
    this.ctx = canvas.getContext("2d");
    this.viewM = 3500;
    this.hits = [];
    canvas.addEventListener("click", (ev) => {
      const r = canvas.getBoundingClientRect();
      const x = ev.clientX - r.left, y = ev.clientY - r.top;
      let best = null, bestD = 26;
      for (const h of this.hits) {
        const d = Math.hypot(h.x - x, h.y - y);
        if (d < bestD) { best = h; bestD = d; }
      }
      if (best) onPick(best.id);
    });
  }

  draw(st, now) {
    const css = getComputedStyle(document.documentElement);
    const col = (v) => css.getPropertyValue(v).trim();
    const w = this.c.clientWidth;
    if (!w) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (this.c.width !== Math.round(w * dpr)) { this.c.width = Math.round(w * dpr); this.c.height = Math.round(w * dpr); }
    const ctx = this.ctx;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const cx = w / 2, cy = w / 2, R = w / 2 - 18, k = R / this.viewM;
    const P = (e, n) => [cx + e * k, cy - n * k];
    ctx.clearRect(0, 0, w, w);
    ctx.fillStyle = col("--radar-bg");
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();

    const jammed = st.radar.status === "jammed", dropout = st.radar.status === "dropout";
    if (jammed || dropout) {
      ctx.fillStyle = col("--red-soft");
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
    }

    ctx.font = "11px system-ui, sans-serif";
    ctx.textAlign = "left"; ctx.textBaseline = "middle";
    for (const km of [1, 2, 3]) {
      const engage = km * 1000 === st.rules.engage_m;
      ctx.strokeStyle = engage ? col("--red") : col("--grid");
      ctx.lineWidth = engage ? 1.5 : 1;
      ctx.setLineDash(engage ? [5, 4] : []);
      ctx.beginPath(); ctx.arc(cx, cy, km * 1000 * k, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);
      // labels sit on the south-west of each ring, where they cover the least
      const a = 225 * Math.PI / 180, rr = km * 1000 * k;
      ctx.fillStyle = engage ? col("--red") : col("--muted");
      ctx.textAlign = "right";
      ctx.fillText(engage ? "1 km engage zone" : `${km} km`, cx + Math.sin(a) * rr - 4, cy - Math.cos(a) * rr + 8);
      ctx.textAlign = "left";
    }
    // compass letters
    ctx.fillStyle = col("--muted"); ctx.textAlign = "center"; ctx.font = "600 12px system-ui, sans-serif";
    for (const [lbl, a] of [["N", 0], ["E", 90], ["S", 180], ["W", 270]]) {
      const r = a * Math.PI / 180;
      ctx.fillText(lbl, cx + Math.sin(r) * (R + 9), cy - Math.cos(r) * (R + 9));
    }
    // sweep
    const sw = ((now / 1000) % st.radar.scan_s) / st.radar.scan_s * Math.PI * 2;
    const grad = ctx.createConicGradient ? ctx.createConicGradient(sw - Math.PI / 2 - 0.6, cx, cy) : null;
    if (grad && !dropout) {
      grad.addColorStop(0, "rgba(120,200,160,0)");
      grad.addColorStop(0.095, col("--sweep"));
      grad.addColorStop(0.0955, "rgba(120,200,160,0)");
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.fill();
    }
    // post
    ctx.fillStyle = col("--ink");
    ctx.beginPath(); ctx.arc(cx, cy, 4, 0, Math.PI * 2); ctx.fill();

    // raw radar returns (incl. clutter)
    for (const [e, n, age] of st.radar.plots) {
      const [x, y] = P(e, n);
      if (Math.hypot(x - cx, y - cy) > R) continue;
      ctx.globalAlpha = Math.max(0.15, 0.7 - age / 4);
      ctx.fillStyle = col("--muted");
      ctx.beginPath(); ctx.arc(x, y, 2, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;

    // instructor truth
    if (st.instructor) {
      for (const en of st.entities) {
        const [x, y] = P(en.e, en.n);
        ctx.strokeStyle = en.hostile ? col("--red") : col("--blue");
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x - 4, y - 4); ctx.lineTo(x + 4, y + 4); ctx.moveTo(x + 4, y - 4); ctx.lineTo(x - 4, y + 4); ctx.stroke();
      }
    }

    // contacts
    this.hits = [];
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    for (const t of st.tracks) {
      const [x, y] = P(t.e, t.n);
      if (Math.hypot(x - cx, y - cy) > R + 4) continue;
      const c = col(STATUS_COLOR[t.status]);
      const sel = t.id === st.selected;
      // where it will be in 20 s
      ctx.strokeStyle = c; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + t.ve * 20 * k, y - t.vn * 20 * k); ctx.stroke();
      if (sel) {
        ctx.strokeStyle = col("--ink"); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(x, y, 15, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.fillStyle = c;
      ctx.beginPath(); ctx.arc(x, y, 10, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = col("--on-dot");
      ctx.font = "700 11px system-ui, sans-serif";
      ctx.fillText(String(t.id), x, y + 0.5);
      this.hits.push({ id: t.id, x, y });
    }

    if (jammed || dropout) {
      ctx.fillStyle = col("--red");
      ctx.font = "700 13px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(jammed ? "RADAR JAMMED" : "RADAR SIGNAL LOST", cx, cy + R * 0.55);
    }
  }
}
