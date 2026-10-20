"""
TRINETRA — rules of engagement (plan §6.3).

Turns the true threat state at the moment of a response into a credit for
each simulated action. Instructors edit ROE_SETS and CREDIT; nothing here
touches a real system.

  hostile? ── no ──> ignore / monitor
     └ yes ─ inside engage range? ── no ──> alert_qrt (monitor / hand_off partly right)
                └ yes ─ approaching the asset? ── yes ──> simulated_soft_kill
                         │                               (simulated_hard_kill once a soft kill was tried)
                         └ no ──> hand_off
"""

from dataclasses import dataclass

NON_HOSTILE = "non_hostile"
HOSTILE_FAR = "hostile_far"
HOSTILE_CLOSE_APPROACHING = "hostile_close_approaching"
HOSTILE_CLOSE_HOLDING = "hostile_close_holding"


@dataclass(frozen=True)
class RoeSet:
    engage_range_m: float = 1000.0
    approach_mps: float = 1.0       # closing faster than this = approaching the protected asset


ROE_SETS = {
    "standard": RoeSet(),
    "standard-forward-post": RoeSet(engage_range_m=1000.0, approach_mps=1.0),
}

# threat state -> {action: credit}; any action not listed earns 0
CREDIT = {
    NON_HOSTILE:               {"ignore": 1.0, "monitor": 1.0, "hand_off": 0.5, "alert_qrt": 0.25},
    HOSTILE_FAR:               {"alert_qrt": 1.0, "monitor": 0.5, "hand_off": 0.5},
    HOSTILE_CLOSE_APPROACHING: {"simulated_soft_kill": 1.0, "simulated_hard_kill": 0.5, "alert_qrt": 0.25},
    HOSTILE_CLOSE_HOLDING:     {"hand_off": 1.0, "alert_qrt": 0.5, "monitor": 0.5},
}

# Actions that declare a target hostile; used on a non-hostile they count as false alarms
HOSTILE_ACTIONS = ("alert_qrt", "simulated_soft_kill", "simulated_hard_kill")


def get_roe(name: str) -> RoeSet:
    try:
        return ROE_SETS[name]
    except KeyError:
        raise KeyError(f"unknown ROE set {name!r}; known: {', '.join(ROE_SETS)}") from None


def threat_state(hostile: bool, range_m: float, radial_speed_mps: float, roe: RoeSet) -> str:
    if not hostile:
        return NON_HOSTILE
    if range_m > roe.engage_range_m:
        return HOSTILE_FAR
    if radial_speed_mps > roe.approach_mps:
        return HOSTILE_CLOSE_APPROACHING
    return HOSTILE_CLOSE_HOLDING


def response_credit(state: str, action: str, soft_kill_tried: bool = False) -> float:
    """Credit for one action. A hard kill is the right escalation only after a soft kill was tried."""
    if state == HOSTILE_CLOSE_APPROACHING and action == "simulated_hard_kill" and soft_kill_tried:
        return 1.0
    return CREDIT[state].get(action, 0.0)
