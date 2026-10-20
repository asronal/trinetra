"""
TRINETRA — trainee console (OpenCV window).

    +------------------------+-------------------------------+
    | radar scope (PPI)      | thermal camera (cued to the   |
    | click a track          | selected track) + zoom inset  |
    |                        +-------------------------------+
    +------------------------+ selected track | messages     |
    | keys                   |                |              |
    +------------------------+-------------------------------+

Selecting a track slews the thermal camera to it. The radar gives no
height, so the camera assumes 60 m and the trainee trims with W/S.

ConsoleUI holds the UI state and handles keys and clicks; run_console()
owns the window and the real-time loop. ConsoleUI never opens a window,
so it is tested without a display.
"""

import math
import time
from collections import deque
from typing import Deque, Optional, Tuple

import cv2
import numpy as np

from ..core.catalog import CLASSES
from ..core.session import ActionError, Session
from ..scoring.rubric import RunScore
from ..sensors.ir import CAMERA_HEIGHT_M
from . import views as V

WINDOW = "TRINETRA"
W, H = 1280, 720
ASSUMED_ALT_M = 60.0
SPEEDS = (1, 2, 4)

CLASS_KEYS = {ord(str(i + 1)): c for i, c in enumerate(CLASSES)}       # 1..6
RESPONSE_KEYS = {ord("m"): "monitor", ord("q"): "alert_qrt", ord("o"): "hand_off",
                 ord("i"): "ignore", ord("k"): "simulated_soft_kill", ord("x"): "simulated_hard_kill"}
CONFIRM_S = 2.0          # a hard kill needs a second press within this many seconds

HELP = [
    ("Click / Tab", "select track"),
    ("1-6", "quad hexa f-wing fpv bird acft"),
    ("H / N", "hostile / not hostile"),
    ("M Q O I", "monitor QRT hand-off ignore"),
    ("K", "simulated soft kill"),
    ("X X", "simulated hard kill"),
    ("W A S D  R", "trim camera, reset"),
    ("Space + -  T", "pause, speed, truth"),
]


class ConsoleUI:
    def __init__(self, session: Session, instructor: bool = False):
        self.s = session
        self.show_truth = instructor
        self.paused = True                     # starts on the briefing
        self.briefing = True
        self.speed_i = 0
        self.pending_class: Optional[str] = None
        self.confirm_hard_until = -1.0
        self.cam_trim = [0.0, 0.0]             # az, el degrees
        self.messages: Deque[Tuple[float, str, tuple]] = deque(maxlen=6)
        self.scans: Deque = deque(maxlen=3)
        self.ppi = V.PPI(10, 46, 560, view_m=3500.0)
        self.quit = False
        self._last_selected = None
        self.say("Briefing: press Space to start", V.ACCENT)

    @property
    def speed(self) -> int:
        return SPEEDS[self.speed_i]

    def say(self, msg: str, color=V.INK) -> None:
        self.messages.append((self.s.t, msg, color))

    # ── Simulation hooks ──────────────────────────────────────────
    def aim_camera(self) -> None:
        ir, tr = self.s.ir, self.s.tracker.get(self.s.selected) if self.s.selected else None
        if ir is None:
            return
        if tr is not None:
            el = math.degrees(math.atan2(ASSUMED_ALT_M - CAMERA_HEIGHT_M, max(tr.range_m, 1.0)))
            ir.point(tr.bearing_deg + self.cam_trim[0], el + self.cam_trim[1])
        else:
            ir.point(ir.az_deg + self.cam_trim[0], ir.el_deg + self.cam_trim[1])
            self.cam_trim = [0.0, 0.0]

    def tick(self, sense_ir: bool = True) -> None:
        self.aim_camera()
        before = self.s.last_scan
        self.s.step(sense_ir=sense_ir)
        if self.s.last_scan is not before and self.s.last_scan is not None:
            self.scans.append(self.s.last_scan)
        if self._last_selected is not None and self.s.selected is None:
            self.say(f"Track {self._last_selected} lost: reacquire", V.HOSTILE)
        self._last_selected = self.s.selected

    # ── Input ─────────────────────────────────────────────────────
    def _do(self, fn, *args) -> None:
        try:
            res = fn(*args)
            self.say(res.message, V.ACCENT if "down" not in res.message else V.GOOD)
        except ActionError as e:
            self.say(str(e).capitalize(), V.HOSTILE)

    def click(self, px: int, py: int) -> None:
        if self.briefing or not self.ppi.contains(px, py):
            return
        best, best_d = None, 22.0
        for tr in self.s.tracker.confirmed:
            tx, ty = self.ppi.to_px(tr.east, tr.north)
            d = math.hypot(tx - px, ty - py)
            if d < best_d:
                best, best_d = tr, d
        if best is not None:
            self.cam_trim = [0.0, 0.0]
            self._do(self.s.select, best.id)

    def key(self, k: int) -> None:
        if k < 0:
            return
        k = k & 0xFFFF
        if k == 27:                                          # Esc
            self.quit = True
            return
        if self.briefing:
            if k == 32:
                self.briefing = False
                self.paused = False
                self.say("Run started", V.GOOD)
            return
        if k >= 256:                                         # arrows, function keys: unused
            return
        ch = chr(k).lower()
        kk = ord(ch)
        if k == 32:
            self.paused = not self.paused
            self.say("Paused" if self.paused else "Resumed", V.MUTED)
        elif ch in "+=":
            self.speed_i = min(self.speed_i + 1, len(SPEEDS) - 1)
        elif ch in "-_":
            self.speed_i = max(self.speed_i - 1, 0)
        elif ch == "t":
            self.show_truth = not self.show_truth
            self.say("Truth view " + ("on (instructor)" if self.show_truth else "off"), V.MUTED)
        elif k == 9:                                         # Tab
            ids = sorted(tr.id for tr in self.s.tracker.confirmed)
            if ids:
                cur = self.s.selected
                nxt = next((i for i in ids if cur is None or i > cur), ids[0])
                self.cam_trim = [0.0, 0.0]
                self._do(self.s.select, nxt)
        elif kk in CLASS_KEYS:
            self.pending_class = CLASS_KEYS[kk]
            self.say(f"Class set: {self.pending_class.replace('_', ' ')}. H = hostile, N = not hostile", V.MUTED)
        elif ch in ("h", "n"):
            if self.pending_class is None:
                self.say("Pick a class first (1-6)", V.HOSTILE)
            else:
                self._do(self.s.classify, self.pending_class, ch == "h")
                self.pending_class = None
        elif kk in RESPONSE_KEYS:
            action = RESPONSE_KEYS[kk]
            if action == "simulated_hard_kill" and self.s.t > self.confirm_hard_until:
                self.confirm_hard_until = self.s.t + CONFIRM_S
                self.say("Press X again to confirm simulated hard kill", V.HOSTILE)
                return
            self.confirm_hard_until = -1.0
            self._do(self.s.respond, action)
        elif ch in "wasd":
            step = 0.25
            da = {"a": -step, "d": step}.get(ch, 0.0)
            de = {"w": step, "s": -step}.get(ch, 0.0)
            self.cam_trim = [self.cam_trim[0] + da, self.cam_trim[1] + de]
        elif ch == "r":
            self.cam_trim = [0.0, 0.0]

    # ── Rendering ─────────────────────────────────────────────────
    def render(self) -> np.ndarray:
        s = self.s
        img = np.full((H, W, 3), V.BG, np.uint8)
        jammed = self.s.last_scan is not None and self.s.last_scan.status == "jammed"
        dropout = self.s.last_scan is not None and self.s.last_scan.status == "dropout"

        # top bar
        title = s.scenario.title or s.scenario.id
        V.text(img, "TRINETRA", (12, 28), 0.6, V.ACCENT, 2)
        V.text(img, title, (130, 28), 0.55, V.INK)
        clock = f"T+ {s.t:05.1f} / {s.duration_s:.0f} s   x{self.speed}"
        V.text(img, clock, (W - 12 - V.text_width(clock, 0.55), 28), 0.55, V.INK)
        flags = []
        if self.paused and not self.briefing:
            flags.append(("PAUSED", V.MUTED))
        if self.show_truth:
            flags.append(("INSTRUCTOR VIEW", V.NEUTRAL))
        x = W - 12 - V.text_width(clock, 0.55) - 20
        for label, col in flags:
            x -= V.text_width(label, 0.45, 1) + 16
            V.text(img, label, (x, 28), 0.45, col)

        # radar scope
        truth = [e for e in s.world.active()] if self.show_truth else None
        self.ppi.draw(img, s.t, list(self.scans), s.tracker.tracks, s.selected, truth, jammed, dropout,
                      r50_m=s.cfg.radar.ref_range_m, scan_period_s=s.cfg.radar.scan_period_s)

        # thermal
        ix, iy = 590, 46
        hostile = {e.id: e.hostile for e in s.world.entities} if self.show_truth else None
        V.draw_ir(img, ix, iy, 2, s.last_ir, hostile)
        if s.ir is not None:
            cue = "cued to T%d" % s.selected if s.selected else "manual"
            V.text(img, f"THERMAL  AZ {s.ir.az_deg:05.1f} deg ({V.mils(s.ir.az_deg):04d} mil)  "
                        f"EL {s.ir.el_deg:+.1f} deg   {cue}", (ix, iy + 512 + 18), 0.42, V.MUTED)

        # selected track
        V.panel(img, 590, 584, 300, 128, "Selected track")
        tr = s.tracker.get(s.selected) if s.selected else None
        if tr is None:
            V.text(img, "None. Click a track or press Tab.", (600, 626), 0.45, V.MUTED)
        else:
            V.text(img, f"T{tr.id}", (600, 630), 0.8, V.ACCENT, 2)
            V.text(img, f"BRG {tr.bearing_deg:05.1f} / {V.mils(tr.bearing_deg):04d} mil", (680, 616), 0.42)
            V.text(img, f"RNG {tr.range_m / 1000:.2f} km", (680, 636), 0.42)
            V.text(img, f"SPD {tr.speed_mps:.0f} m/s  CRS {tr.course_deg:03.0f}", (680, 656), 0.42)
            closing = -(tr.x[0] * tr.x[2] + tr.x[1] * tr.x[3]) / max(tr.range_m, 1.0)
            V.text(img, ("CLOSING" if closing > 1 else "NOT CLOSING") + f" {closing:+.0f} m/s", (600, 684), 0.42,
                   V.HOSTILE if closing > 1 else V.MUTED)
        if self.pending_class:
            V.text(img, f"class: {self.pending_class.replace('_', ' ')} (H/N)", (600, 704), 0.42, V.ACCENT)

        # messages
        V.panel(img, 900, 584, 370, 128, "Messages")
        y = 626
        for t, msg, col in list(self.messages)[-4:]:
            V.text(img, f"{t:5.1f}", (910, y), 0.4, V.MUTED)
            V.text(img, msg[:46], (960, y), 0.42, col)
            y += 21

        # keys
        V.panel(img, 10, 612, 560, 100, "Keys  (Esc ends the run)")
        for i, (k, desc) in enumerate(HELP):
            cx, cy = 20 + (i % 2) * 280, 652 + (i // 2) * 17
            V.text(img, k, (cx, cy), 0.38, V.ACCENT)
            V.text(img, desc, (cx + 100, cy), 0.37, V.MUTED)

        if self.briefing:
            self._draw_briefing(img)
        return img

    def _draw_briefing(self, img) -> None:
        overlay = img.copy()
        cv2.rectangle(overlay, (0, 0), (W, H), V.BG, -1)
        cv2.addWeighted(overlay, 0.85, img, 0.15, 0, img)
        sc = self.s.scenario
        x, y = 140, 140
        V.text(img, "BRIEFING", (x, y), 0.5, V.MUTED)
        V.text(img, sc.title or sc.id, (x, y + 44), 1.0, V.INK, 2)
        y += 90
        meta = f"{sc.terrain}  |  {sc.time_of_day}  |  ROE {sc.roe}  |  {self.s.duration_s:.0f} s  |  {self.s.difficulty}"
        V.text(img, meta, (x, y), 0.5, V.ACCENT)
        y += 40
        for line in V.wrap(sc.briefing or "Detect, classify and respond to every air contact per ROE.", 900, 0.55):
            V.text(img, line, (x, y), 0.55, V.INK)
            y += 28
        y += 20
        V.text(img, "Simulated responses only. No real systems are connected.", (x, y), 0.45, V.MUTED)
        V.text(img, "Press Space to start, Esc to quit", (x, y + 50), 0.6, V.ACCENT, 2)


def run_console(session: Session, instructor: bool = False) -> RunScore:
    ui = ConsoleUI(session, instructor)
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, lambda ev, x, y, *_: ui.click(x, y) if ev == cv2.EVENT_LBUTTONDOWN else None)
    tick_dt = 1.0 / session.cfg.tick_hz
    last = time.perf_counter()
    budget = 0.0
    try:
        while not ui.quit and not session.done:
            now = time.perf_counter()
            if not ui.paused:
                budget = min(budget + (now - last) * ui.speed, 1.0)     # never try to catch up more than 1 s
                n = int(budget / tick_dt)
                for i in range(n):
                    ui.tick(sense_ir=(i == n - 1))
                budget -= n * tick_dt
            last = now
            cv2.imshow(WINDOW, ui.render())
            ui.key(cv2.waitKeyEx(15))
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
        score = session.finish()
        img = np.zeros((H, W, 3), np.uint8)
        V.draw_score(img, score, str(session.log_path))
        cv2.imshow(WINDOW, img)
        while cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) >= 1 and cv2.waitKeyEx(100) < 0:
            pass
    finally:
        session.finish()
        cv2.destroyAllWindows()
    return session.score
