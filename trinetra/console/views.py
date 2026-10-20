"""
TRINETRA — console drawing (OpenCV, BGR).

Pure drawing functions: they take a numpy image and state, and draw. No
window handling and no input here, so the views can be tested and
screenshotted without a display.
"""

import math
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

FONT = cv2.FONT_HERSHEY_SIMPLEX

# ── Palette (BGR) ──
BG = (24, 19, 15)
PANEL = (36, 29, 24)
LINE = (74, 64, 56)
GRID = (50, 43, 37)
INK = (232, 230, 226)
MUTED = (150, 140, 128)
ACCENT = (58, 166, 232)       # tracks, amber
HOSTILE = (88, 100, 255)
NEUTRAL = (226, 178, 112)
GOOD = (122, 200, 96)
PLOT = (165, 155, 145)


def text(img, s: str, org, scale=0.48, color=INK, thick=1) -> None:
    cv2.putText(img, s, (int(org[0]), int(org[1])), FONT, scale, color, thick, cv2.LINE_AA)


def text_width(s: str, scale=0.48, thick=1) -> int:
    return cv2.getTextSize(s, FONT, scale, thick)[0][0]


def wrap(s: str, width_px: int, scale=0.48) -> List[str]:
    lines, line = [], ""
    for word in s.split():
        trial = f"{line} {word}".strip()
        if line and text_width(trial, scale) > width_px:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def panel(img, x, y, w, h, title: Optional[str] = None) -> None:
    cv2.rectangle(img, (x, y), (x + w, y + h), PANEL, -1)
    cv2.rectangle(img, (x, y), (x + w, y + h), LINE, 1)
    if title:
        text(img, title.upper(), (x + 10, y + 18), 0.42, MUTED)


def mils(deg: float) -> int:
    return int(round((deg % 360.0) * 6400.0 / 360.0)) % 6400


class PPI:
    """Radar plan-position indicator, north up, post at the centre."""

    def __init__(self, x: int, y: int, size: int, view_m: float = 3500.0):
        self.x, self.y, self.size, self.view_m = x, y, size, view_m
        self.cx, self.cy = x + size / 2, y + size / 2
        self.r = size / 2 - 24
        self.k = self.r / view_m

    def to_px(self, east: float, north: float) -> Tuple[int, int]:
        return int(round(self.cx + east * self.k)), int(round(self.cy - north * self.k))

    def contains(self, px: int, py: int) -> bool:
        return math.hypot(px - self.cx, py - self.cy) <= self.r

    def draw(self, img, t: float, scans: Sequence, tracks: Sequence, selected: Optional[int],
             truth: Optional[Sequence] = None, jammed: bool = False, dropout: bool = False,
             engage_m: float = 1000.0, r50_m: float = 2500.0, scan_period_s: float = 1.0) -> None:
        cx, cy, r = int(self.cx), int(self.cy), int(self.r)
        cv2.circle(img, (cx, cy), r, (14, 11, 9), -1)
        if jammed or dropout:
            overlay = img.copy()
            cv2.circle(overlay, (cx, cy), r, (30, 30, 90), -1)
            cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)

        for km in (1, 2, 3):
            rr = int(km * 1000 * self.k)
            col = HOSTILE if km * 1000 == engage_m else GRID
            cv2.circle(img, (cx, cy), rr, col, 1, cv2.LINE_AA)
            text(img, f"{km} km", (cx + 4, cy - rr + 14), 0.38, MUTED)
        rr = int(r50_m * self.k)
        for a in range(0, 360, 6):                       # dotted 50 % detection ring
            p = (int(cx + math.sin(math.radians(a)) * rr), int(cy - math.cos(math.radians(a)) * rr))
            cv2.circle(img, p, 1, ACCENT, -1)
        for b in range(0, 360, 10):
            a = math.radians(b)
            inner = r - (10 if b % 30 == 0 else 5)
            p0 = (int(cx + math.sin(a) * inner), int(cy - math.cos(a) * inner))
            p1 = (int(cx + math.sin(a) * r), int(cy - math.cos(a) * r))
            cv2.line(img, p0, p1, LINE, 1, cv2.LINE_AA)
            if b % 30 == 0:
                lbl = f"{b:03d}"
                tw = text_width(lbl, 0.38)
                text(img, lbl, (cx + math.sin(a) * (r + 13) - tw / 2, cy - math.cos(a) * (r + 13) + 4), 0.38, MUTED)
        cv2.circle(img, (cx, cy), r, LINE, 1, cv2.LINE_AA)

        sweep = (t % scan_period_s) / scan_period_s * 2 * math.pi
        cv2.line(img, (cx, cy), (int(cx + math.sin(sweep) * r), int(cy - math.cos(sweep) * r)), GRID, 1, cv2.LINE_AA)
        cv2.rectangle(img, (cx - 3, cy - 3), (cx + 3, cy + 3), INK, -1)

        if truth:
            for e in truth:
                px, py = self.to_px(e.pos[0], e.pos[1])
                if not self.contains(px, py):
                    continue
                col = HOSTILE if e.hostile else NEUTRAL
                if e.hostile:
                    pts = np.array([[px, py - 6], [px + 6, py], [px, py + 6], [px - 6, py]], np.int32)
                    cv2.fillConvexPoly(img, pts, col, cv2.LINE_AA)
                else:
                    cv2.circle(img, (px, py), 4, col, -1, cv2.LINE_AA)
                text(img, e.id, (px + 8, py + 14), 0.36, col)

        for i, scan in enumerate(scans):
            age = t - scan.t
            fade = max(0.25, 1.0 - age / 3.0)
            col = tuple(int(c * fade + b * (1 - fade)) for c, b in zip(PLOT, (14, 11, 9)))
            for p in scan.plots:
                b = math.radians(p.bearing_deg)
                px, py = self.to_px(p.range_m * math.sin(b), p.range_m * math.cos(b))
                if self.contains(px, py):
                    cv2.circle(img, (px, py), 2, col, -1, cv2.LINE_AA)

        for tr in tracks:
            px, py = self.to_px(tr.east, tr.north)
            if not self.contains(px, py):
                continue
            if tr.status != "confirmed":
                cv2.rectangle(img, (px - 3, py - 3), (px + 3, py + 3), (40, 90, 125), 1)
                continue
            sel = tr.id == selected
            s = 8 if sel else 6
            cv2.rectangle(img, (px - s, py - s), (px + s, py + s), ACCENT, 2 if sel else 1, cv2.LINE_AA)
            lead = tr.speed_mps * 20 * self.k                    # 20 s velocity leader
            a = math.radians(tr.course_deg)
            cv2.line(img, (px, py), (int(px + math.sin(a) * lead), int(py - math.cos(a) * lead)), ACCENT, 1, cv2.LINE_AA)
            text(img, f"T{tr.id}", (px + 10, py - 8), 0.42 if sel else 0.38, ACCENT, 2 if sel else 1)

        if jammed:
            text(img, "RADAR JAMMED", (self.x + 8, self.y + 18), 0.5, HOSTILE, 2)
        elif dropout:
            text(img, "RADAR DROPOUT", (self.x + 8, self.y + 18), 0.5, HOSTILE, 2)


def draw_ir(img, x: int, y: int, scale: int, frame, truth_ids: Optional[dict] = None,
            zoom_center: Optional[Tuple[float, float]] = None) -> Tuple[int, int]:
    """Draw a thermal frame scaled by `scale`; returns (width, height) drawn."""
    if frame is None or frame.image is None:
        h, w = 256 * scale, 320 * scale
        cv2.rectangle(img, (x, y), (x + w, y + h), (8, 8, 8), -1)
        msg = "THERMAL: NO SIGNAL" if frame is not None else "THERMAL: STARTING"
        text(img, msg, (x + w / 2 - text_width(msg, 0.6, 2) / 2, y + h / 2), 0.6, HOSTILE, 2)
        return w, h
    h0, w0 = frame.image.shape[:2]
    w, h = w0 * scale, h0 * scale
    img[y:y + h, x:x + w] = cv2.resize(frame.image, (w, h), interpolation=cv2.INTER_NEAREST)

    # crosshair
    cxp, cyp = x + w // 2, y + h // 2
    for d0, d1 in ((-14, -5), (5, 14)):
        cv2.line(img, (cxp + d0, cyp), (cxp + d1, cyp), (210, 210, 210), 1)
        cv2.line(img, (cxp, cyp + d0), (cxp, cyp + d1), (210, 210, 210), 1)

    # 4x zoom inset of the centre (or of a given point)
    zu, zv = zoom_center if zoom_center else (w0 / 2, h0 / 2)
    zw, zh = 40, 30
    zx = int(min(max(0, zu - zw / 2), w0 - zw))
    zy = int(min(max(0, zv - zh / 2), h0 - zh))
    inset = cv2.resize(frame.image[zy:zy + zh, zx:zx + zw], (zw * 5, zh * 5), interpolation=cv2.INTER_NEAREST)
    ix, iy = x + w - zw * 5 - 8, y + 8
    img[iy:iy + zh * 5, ix:ix + zw * 5] = inset
    cv2.rectangle(img, (ix, iy), (ix + zw * 5, iy + zh * 5), ACCENT, 1)
    text(img, "ZOOM x5", (ix + 6, iy + zh * 5 - 8), 0.4, ACCENT)

    if truth_ids:
        for tr in frame.truth:
            u, v = x + tr.u * scale, y + tr.v * scale
            s = max(10, tr.size_px * scale * 1.6)
            col = HOSTILE if truth_ids.get(tr.truth_id) else NEUTRAL
            cv2.rectangle(img, (int(u - s / 2), int(v - s / 2)), (int(u + s / 2), int(v + s / 2)), col, 1)
            text(img, tr.truth_id, (u + s / 2 + 4, v + 4), 0.38, col)
    return w, h


def draw_score(img, score, log_path: str) -> None:
    """Full-screen end-of-run summary."""
    img[:] = BG
    H, W = img.shape[:2]
    text(img, "RUN COMPLETE", (60, 70), 0.6, MUTED, 1)
    text(img, f"{round(score.total * 100)}", (60, 150), 2.4, INK, 4)
    text(img, "/ 100", (60 + text_width(f"{round(score.total * 100)}", 2.4, 4) + 12, 150), 0.8, MUTED, 1)

    parts = [("Detect", "detect", 30), ("Classify", "classify", 25),
             ("Respond (ROE)", "respond", 30), ("False alarms & misses", "false_alarms", 15)]
    y = 210
    for name, key, w in parts:
        v = getattr(score, key)
        text(img, f"{name}", (60, y), 0.55, INK)
        text(img, f"{w}%", (300, y), 0.45, MUTED)
        cv2.rectangle(img, (350, y - 12), (750, y), GRID, -1)
        if v is not None:
            cv2.rectangle(img, (350, y - 12), (350 + int(400 * v), y), GOOD, -1)
        text(img, "n/a" if v is None else f"{round(v * 100)}", (765, y), 0.5, INK)
        y += 36

    text(img, "WHY POINTS WERE LOST", (60, y + 20), 0.45, MUTED)
    y += 50
    notes = score.notes or ["Nothing: every hostile was detected, classified and handled per ROE."]
    for n in notes[:9]:
        for i, line in enumerate(wrap(n, W - 160, 0.5)):
            text(img, ("- " if i == 0 else "  ") + line, (60, y), 0.5, INK)
            y += 24
    if len(notes) > 9:
        text(img, f"... and {len(notes) - 9} more in the terminal", (60, y), 0.45, MUTED)
    text(img, f"Event log: {log_path}", (60, H - 50), 0.42, MUTED)
    text(img, "Press any key to close", (60, H - 24), 0.45, ACCENT)
