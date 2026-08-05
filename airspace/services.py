# airspace/services.py
from __future__ import annotations

from typing import Optional, List, Dict, Any
import re 
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from openai import OpenAI

from .constants.conops import CONOPS_SECTIONS
from .models import ConopsSection
from .forms import (
    TIMEFRAME_CHOICES,
    PURPOSE_OPERATIONS_CHOICES,
    GROUND_ENVIRONMENT_CHOICES,
    PREPARED_PROCEDURES_CHOICES,
)

# ==========================================================
# USER-SCOPING GUARDS
# ==========================================================


def _assert_owned_planning(planning: Any, user: Any) -> None:
    if planning is None or user is None:
        raise PermissionDenied("Unauthorized.")
    if getattr(planning, "user_id", None) != getattr(user, "id", None):
        raise PermissionDenied("You do not have permission to access this waiver planning record.")


def _assert_owned_application(application: Any, user: Any) -> None:
    if application is None or user is None:
        raise PermissionDenied("Unauthorized.")
    if getattr(application, "user_id", None) != getattr(user, "id", None):
        raise PermissionDenied("You do not have permission to access this waiver application.")


def _assert_owned_section(section: Any, user: Any) -> None:
    if section is None or user is None:
        raise PermissionDenied("Unauthorized.")
    app = getattr(section, "application", None)
    if app is None:
        raise PermissionDenied("Unauthorized.")
    if getattr(app, "user_id", None) != getattr(user, "id", None):
        raise PermissionDenied("You do not have permission to access this CONOPS section.")


# ==========================================================
# OPENAI CLIENT
# ==========================================================


def get_openai_client() -> OpenAI:
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env and settings.")
    return OpenAI(api_key=api_key)


# ==========================================================
# SHARED HELPERS
# ==========================================================


def _clean(value: Optional[str]) -> str:
    return (value or "").strip()


def _bool_text(value: bool) -> str:
    return "Yes" if bool(value) else "No"


def _labels_from_choices(values: List[str], choices: List[tuple]) -> List[str]:
    if not values:
        return []
    mapping = dict(choices)
    return [mapping.get(v, v) for v in values if v]


def _has_text(v: Any) -> bool:
    return bool((v or "").strip()) if isinstance(v, str) else bool(v)


def _has_aircraft(planning: Any, section: Any) -> bool:
    """
    True if aircraft is present via FK/manual OR already appears in generated section text.
    (The text fallback is intentionally forgiving because OpenAI phrasing varies.)
    """
    if getattr(planning, "aircraft_id", None):
        return True
    if _has_text(getattr(planning, "aircraft_manual", "")):
        return True

    text = (getattr(section, "content", "") or "").lower()
    return any(label in text for label in (
        "unmanned aircraft system",
        "aircraft:",
        "uas",
        "drone:",
    ))


def _has_flight_hours(planning: Any, section: Any) -> bool:
    hours = getattr(planning, "pilot_flight_hours", None)
    if hours not in (None, ""):
        return True
    return "flight hour" in ((getattr(section, "content", "") or "").lower())


def _has_pilot_name(planning: Any, section: Any) -> bool:
    """
    True if pilot name exists via planning OR already appears in generated section text.
    """
    if _has_text(getattr(planning, "pilot_display_name", lambda: "")()):
        return True

    text = (getattr(section, "content", "") or "").strip()
    if not text:
        return False

    patterns = [
        r"Remote Pilot in Command\s*:\s*\S+",
        r"RPIC Name\s*:\s*\S+",
        r"RPIC\s*:\s*\S+",
    ]
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def _line(label: str, value: Any) -> str:
    """
    Render 'Label: value' only if value is present.
    """
    if value is None:
        return ""
    if isinstance(value, str) and not value.strip():
        return ""
    return f"{label}: {value}\n"


CONTROLLED_AIRSPACE_CLASSES = {"B", "C", "D", "E"}

def _is_controlled_airspace(planning: Any) -> bool:
    return (getattr(planning, "airspace_class", "") or "").strip().upper() in CONTROLLED_AIRSPACE_CLASSES

def _date_range(planning: Any) -> str:
    start = getattr(planning, "start_date", None)
    end = getattr(planning, "end_date", None)
    if not start:
        return ""
    if end and end != start:
        return f"{start} to {end}"
    return f"{start}"


# ==========================================================
# CONTROLLED AIRSPACE REQUIREMENTS (FAA WAIVER DESCRIPTION)
# ==========================================================

def validate_controlled_airspace_description_requirements(planning: Any) -> None:
    """
    Enforces that the FAA DroneZone Description-of-Operations Paragraph 2 can be written
    WITHOUT inventing details when the operation is in controlled airspace.

    Raises ValidationError with field-specific errors for use in forms/views.
    Uses WaiverPlanning field names EXACTLY as in your model.
    """
    if not _is_controlled_airspace(planning):
        return

    errors: Dict[str, List[str]] = {}

    def add(field: str, msg: str) -> None:
        errors.setdefault(field, []).append(msg)

    # -------------------------
    # Containment (must exist)
    # -------------------------

    containment_ok = (
        _has_text(getattr(planning, "containment_method", "")) or
        _has_text(getattr(planning, "containment_notes", ""))
    )
    if not containment_ok:
        add("containment_method", "Required for controlled airspace: choose a containment method or provide containment notes.")
        add("containment_notes", "Required for controlled airspace: describe how containment is enforced/verified on-site (no inventing).")

    # If corridor is chosen, require corridor dimensions
    if (getattr(planning, "operation_area_type", "") or "").strip() == "corridor":
        if getattr(planning, "corridor_length_ft", None) is None:
            add("corridor_length_ft", "Required when operation area type is 'corridor': provide corridor length (ft).")
        if getattr(planning, "corridor_width_ft", None) is None:
            add("corridor_width_ft", "Required when operation area type is 'corridor': provide corridor width (ft).")

    # -------------------------
    # ATC coordination (must exist)
    # -------------------------
    # Accept a few ways to satisfy "ATC coordination exists" without inventing:
    # - facility name OR
    # - check-in procedure OR
    # - coordination method with at least one contact channel (phone/frequency)
    atc_facility_name = getattr(planning, "atc_facility_name", "")
    atc_checkin = getattr(planning, "atc_checkin_procedure", "")
    atc_method = getattr(planning, "atc_coordination_method", "")
    atc_phone = getattr(planning, "atc_phone", "")
    atc_freq = getattr(planning, "atc_frequency", "")

    atc_ok = (
        _has_text(atc_facility_name) or
        _has_text(atc_checkin) or
        (_has_text(atc_method) and (_has_text(atc_phone) or _has_text(atc_freq)))
    )
    if not atc_ok:
        add("atc_facility_name", "Required for controlled airspace: provide ATC facility name OR a check-in procedure OR a coordination method with phone/frequency.")
        add("atc_checkin_procedure", "Required for controlled airspace: describe check-in / coordination steps (when/how, what info, and termination procedure).")
        add("atc_coordination_method", "Required for controlled airspace if you don’t have a facility name/check-in procedure: select phone/radio/both/other.")
        add("atc_phone", "Provide if coordination uses phone.")
        add("atc_frequency", "Provide if coordination uses radio.")

    # Deviation/termination triggers (this is how we avoid inventing “traffic abort” logic)
    if not _has_text(getattr(planning, "atc_deviation_triggers", "")):
        add("atc_deviation_triggers", "Required for controlled airspace: define deviation/termination triggers (traffic, weather, direction, etc.).")

    # -------------------------
    # Lost link / flyaway (must exist)
    # -------------------------
    if not _has_text(getattr(planning, "lost_link_behavior", "")):
        add("lost_link_behavior", "Required for controlled airspace: select lost-link behavior (RTH/hover/land).")

    if not _has_text(getattr(planning, "lost_link_actions", "")):
        add("lost_link_actions", "Required for controlled airspace: provide step-by-step lost-link actions (who does what, who is notified, and how ops terminate).")

    # If behavior is RTH, require RTH altitude
    if (getattr(planning, "lost_link_behavior", "") or "").strip() == "rth":
        if getattr(planning, "rth_altitude_ft_agl", None) is None:
            add("rth_altitude_ft_agl", "Required when lost-link behavior is RTH: provide RTH altitude (ft AGL).")

    # Flyaway actions are strongly recommended; require in controlled airspace so Paragraph 2 can be complete.
    if not _has_text(getattr(planning, "flyaway_actions", "")):
        add("flyaway_actions", "Required for controlled airspace: provide flyaway actions (tracking/last-known position capture and facility notification).")

    # -------------------------
    # Finalize
    # -------------------------
    if errors:
        # Raise with field-specific errors so forms can display nicely
        raise ValidationError(errors)
# ==========================================================
# WAIVER DESCRIPTION (SHORT FORM – NOT CONOPS)
# ==========================================================


def build_waiver_description_prompt(planning) -> str:
    timeframe_labels = _labels_from_choices(planning.timeframe_codes(), TIMEFRAME_CHOICES)
    purpose_labels = _labels_from_choices(getattr(planning, "purpose_operations", []) or [], PURPOSE_OPERATIONS_CHOICES)
    ground_labels = _labels_from_choices(getattr(planning, "ground_environment", []) or [], GROUND_ENVIRONMENT_CHOICES)
    procedure_labels = _labels_from_choices(getattr(planning, "prepared_procedures", []) or [], PREPARED_PROCEDURES_CHOICES)

    addr_bits = [
        _clean(getattr(planning, "street_address", "")),
        _clean(getattr(planning, "location_city", "")),
        _clean(getattr(planning, "location_state", "")),
        _clean(getattr(planning, "zip_code", "")),
    ]
    address = ", ".join(b for b in addr_bits if b)

    airport = getattr(planning, "nearest_airport_ref", None)
    airport_icao = _clean(getattr(airport, "icao", "")) or _clean(getattr(planning, "nearest_airport", ""))
    airport_name = _clean(getattr(airport, "name", ""))

    data: Dict[str, Any] = {
        # --- operation basics ---
        "operation_title": _clean(getattr(planning, "operation_title", "")),
        "start_date": getattr(planning, "start_date", None) or "",
        "end_date": getattr(planning, "end_date", None) or "",
        "date_range": _date_range(planning),
        "timeframe": ", ".join(timeframe_labels),
        "frequency": _clean(getattr(planning, "frequency", "")),
        "local_time_zone": _clean(getattr(planning, "local_time_zone", "")),
        "proposed_agl": getattr(planning, "proposed_agl", None) or "",

        # --- location / airspace ---
        "venue_name": _clean(getattr(planning, "venue_name", "")),
        "street_address": _clean(getattr(planning, "street_address", "")),
        "location_city": _clean(getattr(planning, "location_city", "")),
        "location_state": _clean(getattr(planning, "location_state", "")),
        "zip_code": _clean(getattr(planning, "zip_code", "")),
        "venue_address_compiled": address,
        "location_latitude": getattr(planning, "location_latitude", None) or "",
        "location_longitude": getattr(planning, "location_longitude", None) or "",
        "airspace_class": _clean(getattr(planning, "airspace_class", "")),
        "location_radius": _clean(getattr(planning, "location_radius", "")),
        "nearest_airport": _clean(getattr(planning, "nearest_airport", "")),
        "nearest_airport_ref__icao": airport_icao,
        "nearest_airport_ref__name": airport_name,
        "distance_to_airport_nm": getattr(planning, "distance_to_airport_nm", None) or "",

        # --- aircraft ---
        "aircraft": _clean(getattr(planning, "aircraft_display", lambda: "")()),
        "aircraft_count": _clean(getattr(planning, "aircraft_count", "")),

        # --- pilot ---
        "pilot_name": _clean(getattr(planning, "pilot_display_name", lambda: "")()),
        "pilot_cert": _clean(getattr(planning, "pilot_cert_display", lambda: "")()),
        "pilot_flight_hours": getattr(planning, "pilot_flight_hours", None) or "",

        # --- safety posture helpers ---
        "has_visual_observer": _bool_text(getattr(planning, "has_visual_observer", False)),
        "uses_drone_detection": _bool_text(getattr(planning, "uses_drone_detection", False)),
        "uses_flight_tracking": _bool_text(getattr(planning, "uses_flight_tracking", False)),
        "safety_features_notes": _clean(getattr(planning, "safety_features_notes", "")),
        "ground_environment": ", ".join(ground_labels),
        "estimated_crowd_size": _clean(getattr(planning, "estimated_crowd_size", "")),
        "prepared_procedures": ", ".join(procedure_labels),

        # --- waivers (only if you’re also running them for this op) ---
        "operates_under_10739": _bool_text(getattr(planning, "operates_under_10739", False)),
        "oop_waiver_number": _clean(getattr(planning, "oop_waiver_number", "")),
        "operates_under_107145": _bool_text(getattr(planning, "operates_under_107145", False)),
        "mv_waiver_number": _clean(getattr(planning, "mv_waiver_number", "")),

        # --- FAA specificity (controlled airspace waiver posture) ---
        "operation_area_type": _clean(getattr(planning, "operation_area_type", "")),
        "containment_method": _clean(getattr(planning, "containment_method", "")),
        "containment_notes": _clean(getattr(planning, "containment_notes", "")),
        "corridor_length_ft": getattr(planning, "corridor_length_ft", None) or "",
        "corridor_width_ft": getattr(planning, "corridor_width_ft", None) or "",
        "max_groundspeed_mph": getattr(planning, "max_groundspeed_mph", None) or "",

        # --- lost-link / flyaway ---
        "lost_link_behavior": _clean(getattr(planning, "lost_link_behavior", "")),
        "rth_altitude_ft_agl": getattr(planning, "rth_altitude_ft_agl", None) or "",
        "lost_link_actions": _clean(getattr(planning, "lost_link_actions", "")),
        "flyaway_actions": _clean(getattr(planning, "flyaway_actions", "")),

        # --- ATC coordination (facility specifics) ---
        "atc_facility_name": _clean(getattr(planning, "atc_facility_name", "")),
        "atc_coordination_method": _clean(getattr(planning, "atc_coordination_method", "")),
        "atc_phone": _clean(getattr(planning, "atc_phone", "")),
        "atc_frequency": _clean(getattr(planning, "atc_frequency", "")),
        "atc_checkin_procedure": _clean(getattr(planning, "atc_checkin_procedure", "")),
        "atc_deviation_triggers": _clean(getattr(planning, "atc_deviation_triggers", "")),

        # --- weather + crew discipline ---
        "max_wind_mph": getattr(planning, "max_wind_mph", None) or "",
        "min_visibility_sm": getattr(planning, "min_visibility_sm", None) or "",
        "weather_go_nogo": _clean(getattr(planning, "weather_go_nogo", "")),
        "crew_count": getattr(planning, "crew_count", None) or "",
        "crew_briefing_procedure": _clean(getattr(planning, "crew_briefing_procedure", "")),
        "radio_discipline": _clean(getattr(planning, "radio_discipline", "")),
    }

    return f"""
You are writing a SHORT FAA DroneZone "Description of Operations" for controlled airspace waiver review.

RULES:
- Exactly 2 paragraphs.
- Each paragraph 2–4 sentences.
- No bullets, no headings, no markdown.
- This is NOT a CONOPS.
- Use ONLY the DATA below. Do not invent details.

DATA:
{data}

Paragraph 1: Describe the operation, location, dates/times, airspace class, altitude, aircraft, and general flight profile.

Paragraph 2: Describe the safety posture using ONLY provided data.
If present, include:
- Containment (operation_area_type, containment_method, containment_notes, corridor_* if applicable)
- ATC coordination (atc_facility_name, atc_coordination_method, atc_checkin_procedure, atc_deviation_triggers)
- Lost-link and flyaway (lost_link_behavior, rth_altitude_ft_agl, lost_link_actions, flyaway_actions)
- Traffic abort/termination triggers ONLY if explicitly provided in the data (atc_deviation_triggers)
Do not speculate or add procedures that are not explicitly provided.
""".strip()


def generate_waiver_description_text(planning, *, user, model=None) -> str:
    _assert_owned_planning(planning, user)

    # HARD STOP: prevent Paragraph 2 from being forced to "invent" controlled-airspace specifics
    validate_controlled_airspace_description_requirements(planning)
    
    client = get_openai_client()
    prompt = build_waiver_description_prompt(planning)

    response = client.responses.create(
        model=model or getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini"),
        input=prompt,
        max_output_tokens=1200,
        text={"format": {"type": "text"}},
    )

    result = (response.output_text or "").strip()
    if not result:
        raise RuntimeError("OpenAI response.output_text was empty.")
    return result


# ==========================================================
# CONOPS INITIALIZATION
# ==========================================================


def ensure_conops_sections(application, *, user) -> None:
    _assert_owned_application(application, user)

    desired_keys = [k for k, _ in CONOPS_SECTIONS]
    existing_qs = application.conops_sections.all()
    existing_keys = set(existing_qs.values_list("section_key", flat=True))

    # Create missing sections
    new_sections = [
        ConopsSection(
            application=application,
            user=application.user,
            section_key=key,
            title=title,
        )
        for key, title in CONOPS_SECTIONS
        if key not in existing_keys
    ]
    if new_sections:
        ConopsSection.objects.bulk_create(new_sections)

    # OPTIONAL: remove legacy sections (only if you want to enforce the new structure)
    # ConopsSection.objects.filter(application=application).exclude(section_key__in=desired_keys).delete()



# ==========================================================
# CONOPS GENERATION (PER SECTION)
# ==========================================================
CONOPS_AUTO_GENERATE = {
    "operational_area_containment",
    "operations_over_people_10739",
    "comms_coordination_contingencies",
}

CONOPS_NEVER_GENERATE = {
    "operation_summary",
    "appendix_optional",
}

def _should_include_10739(planning) -> bool:
    if getattr(planning, "operates_under_10739", False):
        return True

    env = set(getattr(planning, "ground_environment", []) or [])
    return bool(env.intersection({"crowd_sparse", "crowd_moderate", "crowd_dense"}))





def build_conops_section_prompt(*, application, planning, section) -> str:
    """
    Prompt for the NEW CONOPS narrative sections only.
    The Operation Summary is rendered from planning data and is not generated here.
    """

    timeframe_labels = _labels_from_choices(planning.timeframe_codes(), TIMEFRAME_CHOICES)
    purpose_labels = _labels_from_choices(getattr(planning, "purpose_operations", []) or [], PURPOSE_OPERATIONS_CHOICES)
    ground_labels = _labels_from_choices(getattr(planning, "ground_environment", []) or [], GROUND_ENVIRONMENT_CHOICES)
    procedure_labels = _labels_from_choices(getattr(planning, "prepared_procedures", []) or [], PREPARED_PROCEDURES_CHOICES)

    airport = getattr(planning, "nearest_airport_ref", None)
    airport_icao = _clean(getattr(airport, "icao", "")) or _clean(getattr(planning, "nearest_airport", ""))
    airport_name = _clean(getattr(airport, "name", ""))

    # data pack (keep it compact)
    data = {
        "operation_title": _clean(getattr(planning, "operation_title", "")),
        "date_range": _date_range(planning),
        "timeframe": ", ".join(timeframe_labels),
        "frequency": _clean(getattr(planning, "frequency", "")),
        "local_time_zone": _clean(getattr(planning, "local_time_zone", "")),
        "venue_name": _clean(getattr(planning, "venue_name", "")),
        "address": ", ".join([p for p in [
            _clean(getattr(planning, "street_address", "")),
            _clean(getattr(planning, "location_city", "")),
            _clean(getattr(planning, "location_state", "")),
            _clean(getattr(planning, "zip_code", "")),
        ] if p]),
        "airspace_class": _clean(getattr(planning, "airspace_class", "")),
        "nearest_airport": f"{airport_icao} – {airport_name}".strip(" –"),
        "distance_to_airport_nm": getattr(planning, "distance_to_airport_nm", None),

        "aircraft": _clean(getattr(planning, "aircraft_display", lambda: "")()),
        "aircraft_count": _clean(getattr(planning, "aircraft_count", "")),
        "proposed_agl": getattr(planning, "proposed_agl", None),
        "max_groundspeed_mph": getattr(planning, "max_groundspeed_mph", None),

        "operation_area_type": _clean(getattr(planning, "operation_area_type", "")),
        "location_radius": _clean(getattr(planning, "location_radius", "")),
        "corridor_length_ft": getattr(planning, "corridor_length_ft", None),
        "corridor_width_ft": getattr(planning, "corridor_width_ft", None),
        "containment_method": _clean(getattr(planning, "containment_method", "")),
        "containment_notes": _clean(getattr(planning, "containment_notes", "")),

        "has_visual_observer": bool(getattr(planning, "has_visual_observer", False)),
        "ground_environment": ", ".join(ground_labels),
        "estimated_crowd_size": _clean(getattr(planning, "estimated_crowd_size", "")),

        "atc_facility_name": _clean(getattr(planning, "atc_facility_name", "")),
        "atc_coordination_method": _clean(getattr(planning, "atc_coordination_method", "")),
        "atc_phone": _clean(getattr(planning, "atc_phone", "")),
        "atc_frequency": _clean(getattr(planning, "atc_frequency", "")),
        "atc_checkin_procedure": _clean(getattr(planning, "atc_checkin_procedure", "")),
        "atc_deviation_triggers": _clean(getattr(planning, "atc_deviation_triggers", "")),

        "lost_link_behavior": _clean(getattr(planning, "lost_link_behavior", "")),
        "rth_altitude_ft_agl": getattr(planning, "rth_altitude_ft_agl", None),
        "lost_link_actions": _clean(getattr(planning, "lost_link_actions", "")),
        "flyaway_actions": _clean(getattr(planning, "flyaway_actions", "")),

        "max_wind_mph": getattr(planning, "max_wind_mph", None),
        "min_visibility_sm": getattr(planning, "min_visibility_sm", None),
        "weather_go_nogo": _clean(getattr(planning, "weather_go_nogo", "")),

        "crew_count": getattr(planning, "crew_count", None),
        "crew_briefing_procedure": _clean(getattr(planning, "crew_briefing_procedure", "")),
        "radio_discipline": _clean(getattr(planning, "radio_discipline", "")),
    }

    if section.section_key == "operational_area_containment":
        instructions = """
Write a concise Operational Area & Containment section for an FAA CONOPS.

Rules:
- 1–2 short paragraphs, then optional bullets.
- Focus on containment method and how it is enforced on-site.
- Do not restate pilot, aircraft, dates, or general location.
- Do not invent barriers, security, VO procedures, or geofences not present in data.
- If corridor is used, reference corridor dimensions if provided.
"""
    elif section.section_key == "operations_over_people_10739":
        instructions = """
Write a concise §107.39 Operations Over People section.

Rules:
- Max 2–3 paragraphs total.
- Peer-to-peer tone: operational controls only, not education.
- Define participants vs non-participants briefly.
- Emphasize avoidance (sterile areas, lateral buffers, VO callouts, terminate/reposition triggers) ONLY if supported by data.
- Do not claim OOP category compliance or hardware categories.
- Do not invent crowd control measures or venue rules not in the data.
"""
    elif section.section_key == "comms_coordination_contingencies":
        instructions = """
Write a concise Communications, Coordination & Contingencies section.

Rules:
- Use bullets where helpful.
- Include ATC check-in procedure and termination/deviation triggers only if provided.
- Include lost-link and flyaway actions only if provided.
- Include weather go/no-go limits only if provided.
- No generic textbook material.
"""
    else:
        raise RuntimeError(f"Unsupported section_key for CONOPS prompt: {section.section_key}")

    return f"""
You are writing ONE section of an FAA CONOPS for a controlled airspace waiver in FAA DroneZone.

Global rules:
- Be concise and procedural.
- No educational explanations.
- Do not repeat facts that belong in the Operation Summary section.
- Use ONLY the data below. If missing, omit.

SECTION: {section.title}

{instructions}

DATA:
{data}

Return only the section body text (no heading).
""".strip()



# ==========================================================
# CONOPS VALIDATION
# ==========================================================


MIN_WORDS_BY_SECTION = {
    "operation_summary": 0, 
    "operational_area_containment": 60,
    "operations_over_people_10739": 80,  
    "comms_coordination_contingencies": 80,
    "appendix_optional": 0,
}



def validate_conops_section(section, *, user) -> dict:
    _assert_owned_section(section, user)

    planning = section.application.planning
    key = section.section_key
    missing: List[str] = []

    def _req(label: str, ok: bool):
        if not ok:
            missing.append(label)

    def _has_any(*vals) -> bool:
        return any(_has_text(v) for v in vals)

    include_10739 = _should_include_10739(planning)

    if key == "operation_summary":
        # Validate the underlying facts exist (not the text)
        _req("operation_title", _has_text(getattr(planning, "operation_title", "")))
        _req("start_date", bool(getattr(planning, "start_date", None)))
        _req("airspace_class", _has_text(getattr(planning, "airspace_class", "")))
        _req("aircraft", _has_aircraft(planning, section))
        _req("pilot_display_name()", _has_text(getattr(planning, "pilot_display_name", lambda: "")()))
        _req("pilot_cert_display()", _has_text(getattr(planning, "pilot_cert_display", lambda: "")()))
        # No word count requirement
    elif key == "operational_area_containment":
        _req("operation_area_type", _has_text(getattr(planning, "operation_area_type", "")))
        _req("containment_method or containment_notes", _has_any(getattr(planning, "containment_method", ""), getattr(planning, "containment_notes", "")))
        if (getattr(planning, "operation_area_type", "") or "").strip() == "corridor":
            _req("corridor_length_ft", getattr(planning, "corridor_length_ft", None) is not None)
            _req("corridor_width_ft", getattr(planning, "corridor_width_ft", None) is not None)
    elif key == "operations_over_people_10739":
        if not include_10739:
            # It's ok to be empty when not included
            section.is_complete = True
            section.validated_at = timezone.now()
            section.save(update_fields=["is_complete", "validated_at", "updated_at"])
            return {"ok": True, "missing": [], "fix_url": "airspace:waiver_planning_new"}

        # If it IS included, we need at least *some* crowd/people context
        _req("ground_environment or estimated_crowd_size", _has_any(getattr(planning, "ground_environment", None), getattr(planning, "estimated_crowd_size", "")))
        _req("containment_method or containment_notes", _has_any(getattr(planning, "containment_method", ""), getattr(planning, "containment_notes", "")))
    elif key == "comms_coordination_contingencies":
        # In controlled airspace, ATC coordination details matter, but don't force invention
        if _is_controlled_airspace(planning):
            _req(
                "atc_checkin_procedure OR (coordination method + phone/frequency)",
                _has_any(getattr(planning, "atc_checkin_procedure", "")) or (
                    _has_text(getattr(planning, "atc_coordination_method", "")) and
                    _has_any(getattr(planning, "atc_phone", ""), getattr(planning, "atc_frequency", ""))
                )
            )
            _req("atc_deviation_triggers", _has_text(getattr(planning, "atc_deviation_triggers", "")))

        _req("lost_link_behavior", _has_text(getattr(planning, "lost_link_behavior", "")))
        _req("lost_link_actions", _has_text(getattr(planning, "lost_link_actions", "")))
        _req("flyaway_actions", _has_text(getattr(planning, "flyaway_actions", "")))
    elif key == "appendix_optional":
        # Always OK (optional)
        pass

    # Text quality gate for narrative sections only
    if key in ("operational_area_containment", "operations_over_people_10739", "comms_coordination_contingencies"):
        text = (section.content or "").strip()
        min_words = MIN_WORDS_BY_SECTION.get(key, 50)
        wc = len(text.split()) if text else 0
        if not text:
            missing.append("Section text is empty.")
        elif wc < min_words:
            missing.append(f"Section text is too short ({wc} words). Target: {min_words}+.")

    ok = len(missing) == 0
    section.is_complete = ok
    section.validated_at = timezone.now()
    section.save(update_fields=["is_complete", "validated_at", "updated_at"])

    return {"ok": ok, "missing": missing, "fix_url": "airspace:waiver_planning_new"}





def generate_conops_section_text(*, application, section, user, model=None) -> str:
    _assert_owned_application(application, user)
    _assert_owned_section(section, user)

    planning = application.planning

    if section.section_key in CONOPS_NEVER_GENERATE:
        if not (section.content or "").strip():
            section.content = ""
            section.save(update_fields=["content", "updated_at"])
        validate_conops_section(section, user=user)
        return section.content or ""

    if section.section_key == "operations_over_people_10739" and not _should_include_10739(planning):
        section.content = ""  
        section.save(update_fields=["content", "updated_at"])
        validate_conops_section(section, user=user)
        return ""
    
    if section.section_key not in CONOPS_AUTO_GENERATE:
        validate_conops_section(section, user=user)
        return section.content or ""

    client = get_openai_client()
    prompt = build_conops_section_prompt(application=application, planning=planning, section=section)

    response = client.responses.create(
        model=model or getattr(settings, "OPENAI_TEXT_MODEL", "gpt-4.1-mini"),
        input=prompt,
        max_output_tokens=1400,  # lower output prevents bloat
        text={"format": {"type": "text"}},
    )

    result = (response.output_text or "").strip()
    if not result:
        raise RuntimeError("OpenAI response.output_text was empty.")

    section.content = result
    section.generated_at = timezone.now()
    section.save(update_fields=["content", "generated_at", "updated_at"])

    validate_conops_section(section, user=user)
    return result




def planning_aircraft_summary(planning, *, user) -> dict:
    """
    Returns normalized aircraft strings for narrative sections.
    """
    _assert_owned_planning(planning, user)

    primary = ""
    if getattr(planning, "aircraft", None):
        primary = str(planning.aircraft).strip()

    manual_raw = (getattr(planning, "aircraft_manual", "") or "").strip()

    manual_list = []
    if manual_raw:
        parts = manual_raw.replace("\n", ",").split(",")
        manual_list = [p.strip() for p in parts if p.strip()]

    seen = set()
    combined = []
    for item in [primary] + manual_list:
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        combined.append(item)

    return {
        "primary": primary,
        "manual_list": manual_list,
        "combined_list": combined,
        "combined_display": "; ".join(combined) if combined else "—",
    }
