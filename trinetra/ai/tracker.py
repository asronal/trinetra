"""
TRINETRA — multi-target tracker on radar plots.

Follows the structure of the SkyNetics SORT tracker (predict -> Hungarian
assignment -> update / birth / prune), rewritten for world coordinates:

- state is [east, north, v_east, v_north] with a constant-velocity Kalman filter
- association uses a Mahalanobis gate instead of image-box IoU
- M-of-N confirmation: the old streak counter dropped by one on every
  predict and rose by one on every update, so it never got past 1 and
  min_hits >= 2 could never confirm a track
- track IDs belong to the tracker instance (the old counter was a
  class-level global shared by every tracker)
"""

import math
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Sequence, Tuple

import numpy as np

from ..config import TrackerConfig

TENTATIVE, CONFIRMED = "tentative", "confirmed"

_H = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
_BIG = 1e9


def plot_measurement(plot, range_sigma_m: float, bearing_sigma_deg: float):
    """Plot (range, bearing) -> east/north position and its 2x2 covariance."""
    r, b = plot.range_m, math.radians(plot.bearing_deg)
    z = np.array([r * math.sin(b), r * math.cos(b)])
    J = np.array([[math.sin(b), r * math.cos(b)],
                  [math.cos(b), -r * math.sin(b)]])
    sb = math.radians(bearing_sigma_deg)
    return z, J @ np.diag([range_sigma_m ** 2, sb ** 2]) @ J.T


@dataclass
class Track:
    id: int
    x: np.ndarray                   # [east, north, v_east, v_north]
    P: np.ndarray
    born_scan: int
    last_t: float
    hits: int = 1
    misses: int = 0
    status: str = TENTATIVE
    truth_votes: Deque[Optional[str]] = field(default_factory=lambda: deque(maxlen=5))

    @property
    def east(self) -> float:
        return float(self.x[0])

    @property
    def north(self) -> float:
        return float(self.x[1])

    @property
    def range_m(self) -> float:
        return math.hypot(self.x[0], self.x[1])

    @property
    def bearing_deg(self) -> float:
        return math.degrees(math.atan2(self.x[0], self.x[1])) % 360.0

    @property
    def speed_mps(self) -> float:
        return math.hypot(self.x[2], self.x[3])

    @property
    def course_deg(self) -> float:
        return math.degrees(math.atan2(self.x[2], self.x[3])) % 360.0

    @property
    def truth_id(self) -> Optional[str]:
        """Ground truth behind this track: the most common source of its recent plots.

        The simulator uses this to resolve what the trainee selected; it is
        never shown to the trainee. None means the track is mostly clutter.
        """
        if not self.truth_votes:
            return None
        return Counter(self.truth_votes).most_common(1)[0][0]


@dataclass
class TrackerUpdate:
    confirmed: List[Track] = field(default_factory=list)   # newly confirmed this scan
    dropped: List[Track] = field(default_factory=list)     # confirmed tracks removed this scan


def assign(cost: np.ndarray, gate: float) -> List[Tuple[int, int]]:
    """Min-cost assignment of rows to columns, keeping pairs within the gate.

    Hungarian (scipy) when available, otherwise greedy, the same fallback
    pattern as the SkyNetics tracker.
    """
    if cost.size == 0:
        return []
    try:
        from scipy.optimize import linear_sum_assignment
        rows, cols = linear_sum_assignment(np.where(cost <= gate, cost, _BIG))
        return [(int(r), int(c)) for r, c in zip(rows, cols) if cost[r, c] <= gate]
    except ImportError:
        pairs, used_r, used_c = [], set(), set()
        for flat in np.argsort(cost, axis=None):
            r, c = np.unravel_index(flat, cost.shape)
            if cost[r, c] > gate:
                break
            if r not in used_r and c not in used_c:
                pairs.append((int(r), int(c)))
                used_r.add(r)
                used_c.add(c)
        return pairs


class Tracker:
    def __init__(self, cfg: TrackerConfig, range_sigma_m: float, bearing_sigma_deg: float):
        self.cfg = cfg
        self.range_sigma_m = range_sigma_m
        self.bearing_sigma_deg = bearing_sigma_deg
        self.tracks: List[Track] = []
        self._next_id = 1
        self._scan = 0

    @property
    def confirmed(self) -> List[Track]:
        return [t for t in self.tracks if t.status == CONFIRMED]

    def get(self, track_id: int) -> Optional[Track]:
        return next((t for t in self.tracks if t.id == track_id), None)

    def _predict(self, tr: Track, t: float) -> None:
        dt = t - tr.last_t
        if dt <= 0:
            return
        F = np.eye(4)
        F[0, 2] = F[1, 3] = dt
        q = self.cfg.accel_sigma_mps2 ** 2
        a, b, c = dt ** 4 / 4, dt ** 3 / 2, dt ** 2
        Q = q * np.array([[a, 0, b, 0], [0, a, 0, b], [b, 0, c, 0], [0, b, 0, c]])
        tr.x = F @ tr.x
        tr.P = F @ tr.P @ F.T + Q
        tr.last_t = t

    def update(self, plots: Sequence, t: float) -> TrackerUpdate:
        self._scan += 1
        out = TrackerUpdate()
        for tr in self.tracks:
            self._predict(tr, t)

        meas = [plot_measurement(p, self.range_sigma_m, self.bearing_sigma_deg) for p in plots]

        # Mahalanobis distance of every plot from every track's prediction
        cost = np.full((len(self.tracks), len(meas)), _BIG)
        for i, tr in enumerate(self.tracks):
            HPH = _H @ tr.P @ _H.T
            for j, (z, R) in enumerate(meas):
                y = z - _H @ tr.x
                cost[i, j] = float(y @ np.linalg.solve(HPH + R, y))
        pairs = assign(cost, self.cfg.gate_chi2)

        matched_tracks = set()
        matched_plots = set()
        for i, j in pairs:
            tr = self.tracks[i]
            z, R = meas[j]
            S = _H @ tr.P @ _H.T + R
            K = np.linalg.solve(S.T, (tr.P @ _H.T).T).T
            I_KH = np.eye(4) - K @ _H
            tr.x = tr.x + K @ (z - _H @ tr.x)
            tr.P = I_KH @ tr.P @ I_KH.T + K @ R @ K.T          # Joseph form: stays symmetric
            tr.hits += 1
            tr.misses = 0
            tr.truth_votes.append(plots[j].truth_id)
            matched_tracks.add(i)
            matched_plots.add(j)

        for i, tr in enumerate(self.tracks):
            if i not in matched_tracks:
                tr.misses += 1

        # Births: every unmatched plot starts a tentative track
        v0 = self.cfg.init_speed_sigma_mps ** 2
        for j, (z, R) in enumerate(meas):
            if j in matched_plots:
                continue
            P = np.zeros((4, 4))
            P[:2, :2] = R
            P[2, 2] = P[3, 3] = v0
            tr = Track(self._next_id, np.array([z[0], z[1], 0.0, 0.0]), P, self._scan, t)
            tr.truth_votes.append(plots[j].truth_id)
            self._next_id += 1
            self.tracks.append(tr)

        # Confirm (M of N) and prune
        keep = []
        for tr in self.tracks:
            if tr.status == TENTATIVE:
                if tr.hits >= self.cfg.min_hits:
                    tr.status = CONFIRMED
                    out.confirmed.append(tr)
                else:
                    scans_left = self.cfg.confirm_window - (self._scan - tr.born_scan + 1)
                    if tr.hits + scans_left < self.cfg.min_hits:
                        continue                    # can no longer reach min_hits: drop quietly
            elif tr.misses >= self.cfg.max_misses:
                out.dropped.append(tr)
                continue
            keep.append(tr)
        self.tracks = keep
        return out
