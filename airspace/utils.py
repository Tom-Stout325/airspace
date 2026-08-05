#airspce/utils.py
from __future__ import annotations

from decimal import Decimal
from typing import List, Dict, Any, Optional

from math import radians, sin, cos, sqrt, atan2





def dms_to_decimal(deg, minutes, seconds, direction):
    """
    Convert DMS + direction (N/S/E/W) to signed decimal degrees.

    Example:
        39, 48, 41.6, "N" ->  39.811556
        86, 20, 35.6, "W" -> -86.343222
    """
    if deg is None or minutes is None or seconds is None or not direction:
        return None

    deg = Decimal(str(deg))
    minutes = Decimal(str(minutes))
    seconds = Decimal(str(seconds))

    decimal = deg + (minutes / Decimal("60")) + (seconds / Decimal("3600"))

    if direction.upper() in ("S", "W"):
        decimal = -decimal

    # store with 6 decimal places (matches your model)
    return decimal.quantize(Decimal("0.000001"))


def decimal_to_dms(value, is_lat=True):
    """
    Convert signed decimal degrees to DMS + direction (N/S/E/W).

    Returns a dict:
      {"deg": 39, "min": 48, "sec": 41.6, "dir": "N"}
    or None if value is missing.
    """
    if value is None:
        return None

    value = Decimal(str(value))
    sign = -1 if value < 0 else 1
    abs_val = float(abs(value))

    deg = int(abs_val)
    minutes_full = (abs_val - deg) * 60
    minutes = int(minutes_full)
    seconds = round((minutes_full - minutes) * 60, 1)

    if is_lat:
        direction = "N" if sign >= 0 else "S"
    else:
        direction = "E" if sign >= 0 else "W"

    return {
        "deg": deg,
        "min": minutes,
        "sec": seconds,
        "dir": direction,
    }


# ---------------------------------------------------------------------
# Short Description generator
# ---------------------------------------------------------------------


def _clean_snippet(text: Optional[str], max_len: int = 140) -> Optional[str]:
    """
    Collapse whitespace into single spaces and truncate to max_len characters.
    Returns None for empty/whitespace-only input.
    """
    if not text:
        return None

    # Collapse newlines and multiple spaces
    snippet = " ".join(str(text).split())

    if not snippet:
        return None

    if len(snippet) > max_len:
        return snippet[: max_len - 1].rstrip() + "…"

    return snippet


def generate_short_description(waiver: Any) -> str:
    """
    Build an ultra-brief FAA-style 'Brief Description of Operations'
    from an AirspaceWaiver instance.

    Baseline structure (your approved copy):

      "The RPIC will conduct sUAS flights for aerial imaging within the
       defined area, remaining below the requested maximum AGL and
       launching from a secure location. Operations will follow VLOS
       requirements, use a qualified VO as needed, and employ a
       GPS-stabilized aircraft with safety features. The RPIC will
       perform standard pre-flight checks, monitor the area for hazards,
       and cease operations if unsafe conditions arise."
    """

    # ------------------------------------------------------------------
    # Purpose / operation type
    # ------------------------------------------------------------------
    purpose = "aerial imaging"

    # If you later enrich operation_activities, this will automatically
    # reflect that without breaking.
    activities_raw = getattr(waiver, "operation_activities", None)

    if activities_raw:
        if isinstance(activities_raw, (list, tuple, set)):
            codes = [str(c).strip() for c in activities_raw if str(c).strip()]
        else:
            # Treat as comma-separated string or single value
            codes = [
                c.strip()
                for c in str(activities_raw).split(",")
                if c.strip()
            ]

        if codes:
            # You can later map codes -> human phrases; for now we just
            # indicate that more than simple imaging is involved.
            purpose = "aerial imaging and related UAS operations"

    # ------------------------------------------------------------------
    # Location snippet (proposed_location)
    # ------------------------------------------------------------------
    location_snippet = _clean_snippet(getattr(waiver, "proposed_location", ""))

    # ------------------------------------------------------------------
    # Maximum AGL
    # ------------------------------------------------------------------
    max_agl: Optional[int] = None
    try:
        max_agl_value = getattr(waiver, "max_agl", None)
        if max_agl_value is not None:
            max_agl = int(max_agl_value)
    except (TypeError, ValueError):
        max_agl = None

    # ------------------------------------------------------------------
    # Sentence 1 – core mission
    # ------------------------------------------------------------------
    if location_snippet and max_agl is not None:
        first_sentence = (
            f"The RPIC will conduct sUAS flights for {purpose} within the defined area near "
            f"{location_snippet}, remaining below approximately {max_agl} feet AGL and "
            f"launching from a secure location."
        )
    elif max_agl is not None:
        first_sentence = (
            f"The RPIC will conduct sUAS flights for {purpose} within the defined area, "
            f"remaining below approximately {max_agl} feet AGL and launching from a "
            f"secure location."
        )
    else:
        first_sentence = (
            f"The RPIC will conduct sUAS flights for {purpose} within the defined area, "
            f"and will maintain an altitude at or below AGL and launching from a controlled "
            f"location."
        )

    # ------------------------------------------------------------------
    # Sentence 2 – VLOS / VO / safety language
    # ------------------------------------------------------------------
    second_sentence = (
        "Operations will follow VLOS requirements, utilize a qualified VO, and employ "
        "a GPS-stabilized aircraft with manufacturers safety features. The RPIC will perform standard "
        "pre-flight checks, monitor the area for hazards, and cease operations if unsafe "
        "conditions arise."
    )

    # Ensure a clean space between sentences
    return f"{first_sentence} {second_sentence}"




NM_PER_KM = Decimal("0.539956803")
EARTH_RADIUS_KM = 6371.0088  # km


def haversine_nm(lat1, lon1, lat2, lon2) -> Decimal:
    phi1 = radians(float(lat1))
    phi2 = radians(float(lat2))
    dphi = radians(float(lat2 - lat1))
    dlambda = radians(float(lon2 - lon1))

    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    km = EARTH_RADIUS_KM * c
    return (Decimal(str(km)) * NM_PER_KM).quantize(Decimal("0.01"))








CROWDLIKE_ENV_CODES = {
    "crowd_sparse", "crowd_moderate", "crowd_dense",
    "pedestrian", "roadways", "recreational", "commercial",
}


def should_include_10739(planning) -> bool:
    """
    §107.39 section is included if:
      - user indicates they are operating under an existing 107.39 waiver, OR
      - planning suggests people/public may be present.
    """
    if getattr(planning, "operates_under_10739", False):
        return True

    env = getattr(planning, "ground_environment", None) or []
    env_set = set(env) if isinstance(env, (list, tuple)) else set()

    crowd_hint = bool(env_set.intersection(CROWDLIKE_ENV_CODES))
    crowd_size = bool((getattr(planning, "estimated_crowd_size", "") or "").strip())
    return crowd_hint or crowd_size




def validate_10739_readiness(planning) -> Dict[str, Any]:
    """
    Validates underlying facts needed to write a defensible §107.39 section.
    Returns dict: { ok: bool, missing: [str] }
    """
    missing: List[str] = []

    def req(label: str, ok: bool):
        if not ok:
            missing.append(label)

    def has_text(v) -> bool:
        return bool((v or "").strip()) if isinstance(v, str) else bool(v)

    def has_any(*vals) -> bool:
        return any(has_text(v) for v in vals)

    include = should_include_10739(planning)
    if not include:
        return {"ok": True, "missing": [], "included": False}

    # People/crowd context
    req("Ground environment OR estimated crowd size", has_any(getattr(planning, "estimated_crowd_size", ""), getattr(planning, "ground_environment", None)))

    # Containment / keep-out
    req("Containment method OR containment notes", has_any(getattr(planning, "containment_method", ""), getattr(planning, "containment_notes", "")))

    # Basic operating profile (keeps narrative from being vague)
    req("Proposed AGL (ft)", getattr(planning, "proposed_agl", None) is not None)
    req("Max groundspeed (mph)", getattr(planning, "max_groundspeed_mph", None) is not None)

    # Termination triggers + contingencies
    req("Deviation / termination triggers", has_text(getattr(planning, "atc_deviation_triggers", "")))
    req("Lost-link behavior", has_text(getattr(planning, "lost_link_behavior", "")))
    req("Lost-link actions", has_text(getattr(planning, "lost_link_actions", "")))
    req("Flyaway actions", has_text(getattr(planning, "flyaway_actions", "")))

    # If corridor: dimensions
    if (getattr(planning, "operation_area_type", "") or "").strip() == "corridor":
        req("Corridor length (ft)", getattr(planning, "corridor_length_ft", None) is not None)
        req("Corridor width (ft)", getattr(planning, "corridor_width_ft", None) is not None)

    # If RTH: altitude
    if (getattr(planning, "lost_link_behavior", "") or "").strip() == "rth":
        req("RTH altitude (ft AGL)", getattr(planning, "rth_altitude_ft_agl", None) is not None)

    return {"ok": len(missing) == 0, "missing": missing, "included": True}
