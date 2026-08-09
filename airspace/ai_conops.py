from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.fields.files import FieldFile
from django.forms.models import model_to_dict
from django.utils import timezone
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .conops import (
    CONOPS_DEFINITIONS,
    OPERATIONS_OVER_PEOPLE_AVOIDED,
    _crewed_aircraft_conflict_response,
    _operations_over_people,
    get_or_create_application,
)
from .models import ApprovalApplication, ConopsSection, OperationApproval


PROMPT_VERSION = "controlled-airspace-v3"

AIRCRAFT_REGISTRATION_PATTERN = re.compile(
    r"\b(?:FAA\s+registration(?:\s+number)?|registration\s+number)"
    r"\s*(?::|is)?\s*(?P<registration>(?=[A-Za-z0-9-]*\d)"
    r"[A-Za-z0-9-]+)\b|\bregistered\s+as\s+"
    r"(?P<registered_as>(?=[A-Za-z0-9-]*\d)[A-Za-z0-9-]+)\b",
    re.IGNORECASE,
)
COORDINATE_PATTERN = re.compile(
    r"(?<![\d.+-])[+-]?\d{1,3}\.\d{4,}(?!\d)"
)
COORDINATE_TOLERANCE = Decimal("0.0000001")
EMERGENCY_AIRSPACE_CONFLICT_REFERENCE = (
    "Airspace Conflict: Follow the crewed-aircraft conflict procedure "
    "described in Section 4.0."
)


class OpenAIConopsError(RuntimeError):
    """Raised when AirSpace cannot generate a usable CONOPS package."""


class GeneratedConopsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class GeneratedConopsPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description_of_operations: str = Field(
        min_length=1,
        max_length=5000,
    )
    sections: list[GeneratedConopsSection] = Field(
        min_length=1,
    )


def _setting(name: str, default: Any = None) -> Any:
    value = getattr(settings, name, None)
    if value not in (None, ""):
        return value
    return os.environ.get(name, default)


def openai_is_configured() -> bool:
    return bool(_setting("OPENAI_API_KEY", ""))


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, FieldFile):
        stored_name = str(value.name or "")
        return {
            "present": bool(stored_name),
            "filename": (
                PurePosixPath(stored_name).name
                if stored_name
                else ""
            ),
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _json_value(item)
            for key, item in value.items()
        }
    if hasattr(value, "pk"):
        return value.pk
    return value


def _operation_payload(
    approval: OperationApproval,
) -> dict[str, Any]:
    operation = approval.operation
    controlled_airspace_only = (
        approval.approval_type.code == "controlled-airspace"
        and not operation.approvals.exclude(pk=approval.pk).exists()
    )

    excluded_operation_fields = {
        "user",
        "aircraft",
        "pilot_profile",
        "nearest_airport_ref",
    }
    operation_data = {
        key: _json_value(value)
        for key, value in model_to_dict(operation).items()
        if key not in excluded_operation_fields
    }

    pilot = operation.pilot_profile
    pilot_user = getattr(pilot, "user", None) if pilot else None
    pilot_name = (
        (operation.pilot_name_manual or "").strip()
        or " ".join(
            value
            for value in [
                getattr(pilot_user, "first_name", ""),
                getattr(pilot_user, "last_name", ""),
            ]
            if value
        ).strip()
    )
    pilot_certificate = (
        (operation.pilot_cert_manual or "").strip()
        or (
            getattr(pilot, "faa_certificate_number", "")
            if pilot
            else ""
        )
    )

    aircraft = []
    assignments = operation.aircraft_assignments.select_related(
        "drone"
    )
    for assignment in assignments:
        drone = assignment.drone
        aircraft.append(
            {
                "manufacturer": drone.manufacturer,
                "model": drone.model,
                "nickname": drone.nickname,
                "serial_number": drone.serial_number,
                "faa_registration_number": (
                    drone.faa_registration_number
                ),
                "planned_payload": assignment.planned_payload,
                "registration_verified": (
                    assignment.registration_verified
                ),
                "remote_id_verified": (
                    assignment.remote_id_verified
                ),
                "airworthiness_verified": (
                    assignment.preflight_airworthiness_verified
                ),
                "current_firmware_installed": (
                    assignment.current_firmware_installed
                ),
                "safety_features": (
                    assignment.safety_features_snapshot
                    or drone.safety_features
                ),
                "operation_specific_safety_notes": (
                    assignment.operation_specific_safety_notes
                ),
            }
        )

    airport = operation.nearest_airport_ref
    nearest_airport = None
    if airport:
        nearest_airport = {
            "name": airport.name,
            "faa_identifier": airport.faa_identifier,
            "icao": airport.icao,
            "distance_nm": _json_value(
                operation.distance_to_airport_nm
            ),
        }

    expected_sections = [
        {"key": item.key, "title": item.title}
        for item in CONOPS_DEFINITIONS
    ]

    return {
        "regulatory_context": {
            "application_scope": (
                "14 CFR 107.41 controlled-airspace authorization; "
                "no other Part 107 relief is implied"
            ),
            "standard_part_107_weather": {
                "minimum_flight_visibility_sm": 3,
                "minimum_below_cloud_ft": 500,
                "minimum_horizontal_from_cloud_ft": 2000,
                "fixed_cloud_ceiling": None,
            },
            "uasfm_rule": (
                "Do not state a UASFM grid altitude unless it is "
                "explicitly present in operation planning data."
            ),
            "controlled_airspace_only": controlled_airspace_only,
        },
        "document_purpose": {
            "short_output": (
                "Description of Operations for the FAA application form"
            ),
            "long_output": (
                "Attachment-ready full Concept of Operations"
            ),
        },
        "application_type": {
            "name": approval.approval_type.name,
            "code": approval.approval_type.code,
            "category": approval.approval_type.category,
            "regulation": approval.approval_type.regulation,
            "description": approval.approval_type.description,
        },
        "approval_planning": {
            "requested_operation": approval.requested_operation,
            "safety_justification": approval.safety_justification,
            "risk_mitigations": approval.risk_mitigations,
            "equivalent_level_of_safety": (
                approval.equivalent_level_of_safety
            ),
        },
        "operation": operation_data,
        "operation_semantics": {
            "launch_location": operation.launch_location,
            "recovery_location": operation.recovery_location,
            "operational_area_geometry": (
                operation.get_operation_area_type_display()
                if operation.operation_area_type
                else ""
            ),
            "dronezone_requested_radius": (
                operation.get_dronezone_radius_display()
                if operation.dronezone_radius
                else ""
            ),
            "operation_reference_coordinates": {
                "latitude": _json_value(operation.location_latitude),
                "longitude": _json_value(operation.location_longitude),
                "meaning": (
                    "Reference point for the overall operation; not a launch "
                    "or recovery coordinate unless the planning record "
                    "explicitly says so."
                ),
            },
            "corridor_dimensions": {
                "length_ft": operation.corridor_length_ft,
                "width_ft": operation.corridor_width_ft,
            } if operation.operation_area_type == "corridor" else None,
            "operational_boundary_description": (
                operation.operational_boundary_description
            ),
        },
        "airspace_standard_procedures": {
            "crewed_aircraft_conflict_response": (
                _crewed_aircraft_conflict_response(operation)
            ),
            "operations_over_people": _operations_over_people(operation),
            "flight_tracking_disclaimer": (
                f"{operation.flight_tracking_service} is used as a "
                "supplemental situational-awareness tool and does not replace "
                "visual scanning, see-and-avoid responsibilities, or the "
                "RPIC's obligation to yield right of way to crewed aircraft."
                if operation.uses_flight_tracking
                and operation.flight_tracking_service.strip()
                else ""
            ),
        },
        "pilot": {
            "name": pilot_name,
            "faa_certificate_number": pilot_certificate,
            "flight_hours": _json_value(
                operation.pilot_flight_hours
            ),
        },
        "aircraft": aircraft,
        "nearest_airport": nearest_airport,
        "expected_sections": expected_sections,
    }


def _system_prompt() -> str:
    return """You are drafting FAA small-UAS application material for AirSpace.

The primary target is a professional 14 CFR 107.41 controlled-airspace
authorization package. Write like an experienced UAS operator preparing a
concise operational document for FAA review, not like a database export.

SOURCE FIDELITY IS MANDATORY:
- Use only mission purpose, venue type, event type, client, activity, and
  operational context explicitly supplied in the planning JSON.
- Never infer racing, sports, construction, inspection, public safety,
  agriculture, mapping, real estate, media production, or any other use case
  from a venue name, address, previous generation, aircraft, crowd size, or
  other contextual clue.
- If the user entered only a general purpose such as "aerial photography" or
  "mapping", use only that description.
- Do not introduce a named event, organization, race, sport, or business
  activity unless it appears explicitly in the supplied planning data.

Create two separate deliverables:

1. description_of_operations
   - Write 2 to 3 concise paragraphs suitable for the FAA DroneZone
     Description of Operation field.
   - Target roughly 150 to 300 words.
   - State what the operation is, where and when it will occur, the aircraft
     and planned altitude, the requested authorization, and the principal
     safety/airspace controls.
   - It must read as connected prose.
   - Do NOT include numbered CONOPS headings, field labels, or a list of every
     planning value.
   - Do NOT reproduce the full CONOPS.

2. sections
   - Produce every key/title in expected_sections exactly once and in the
     supplied order.
   - Treat the sections as chapters of one coherent document.
   - Prefer concise narrative paragraphs.
   - Use bullets only when they improve readability for aircraft capabilities,
     procedural steps, operating limitations, or emergency actions.
   - Avoid repeating the same fact in multiple sections.
   - Target a concise attachment rather than an exhaustive safety manual.

FAA / REGULATORY GUARDRAILS FOR A STANDARD §107.41 REQUEST:
- A §107.41 controlled-airspace authorization does not itself waive other
  Part 107 operating rules.
- When the planning record uses standard Part 107 weather minimums, describe
  them as at least 3 statute miles flight visibility and remaining at least
  500 feet below and 2,000 feet horizontally from clouds.
- Do NOT convert cloud-clearance requirements into a fixed "minimum cloud
  ceiling" such as 200 feet or any other invented ceiling.
- Do NOT state or imply that obstacle sensing, LiDAR, Return-to-Home,
  geofencing, or similar aircraft systems provide separation from crewed
  aircraft. They are aircraft-control / obstacle-avoidance safety systems.
- Do NOT imply that event security, ground security, or venue personnel
  provide ATC or airspace-control functions.
- Direct contact with ATC is not a substitute for the required §107.41
  authorization. If the planning record does not contain a specific ATC
  procedure, state that the operation will not begin until the authorization
  is issued and that the RPIC will comply with all applicable limitations and
  special provisions in the authorization.
- Never invent an ATC telephone number, frequency, facility, notification
  requirement, or check-in procedure.
- If an ATC contact or frequency exists in the planning record, reproduce it
  exactly and describe it only for the purpose entered by the user.
- Preserve user-entered facility identifiers exactly as written. Never expand,
  reinterpret, normalize, or substitute an identifier such as "LSV ATC" with
  a facility name, airport code, or another identifier unless that exact value
  appears in the relevant planning field.
- Do not mention a UAS Facility Map (UASFM) grid altitude unless a grid
  altitude is explicitly supplied in the planning data. Never invent a grid
  altitude or claim that the requested altitude is within a UASFM value when
  that fact is not supplied.
- Do not claim that a requested altitude is operationally necessary unless the
  planning record contains the user's altitude justification.
- Describe maximum_planned_altitude_agl as the requested maximum altitude,
  never as an altitude already authorized. State that the operation remains
  subject to the altitude authorized by the FAA and will not exceed any lower
  altitude limitation in the issued authorization. In the Description of
  Operations, say the aircraft will operate "at or below the requested maximum
  altitude of [value] feet AGL and subject to any lower altitude limitation
  specified in the FAA authorization." In Flight Envelope and Operating
  Limitations, say flights will be conducted "at or below the requested maximum
  altitude of [value] feet AGL and will not exceed any lower altitude limitation
  specified in the FAA authorization." Always use the actual numeric altitude
  supplied in the planning record.
- Treat operation_semantics.dronezone_requested_radius as required planning
  data and reproduce its actual stored display value. "Blanket Area / Wide
  Area" is not a numeric radius; never convert it to 0.5 NM or any other
  distance. A numeric selection such as "1/2 NM" may be stated only when that
  is the stored selection.
- Preserve operation_semantics.operational_area_geometry exactly. When it is
  "Multiple sites", do not rewrite the operation as one radius around a single
  launch site.
- When launch_location or recovery_location is "Varies", preserve that value.
  operation_reference_coordinates identify the overall operation reference
  point and must not be called launch-site or recovery-site coordinates unless
  a separate source field explicitly establishes that fact.
- Only when regulatory_context.controlled_airspace_only is true, state: "This
  application requests a controlled-airspace authorization under §107.41 and
  does not request relief from any other Part 107 requirement." Do not call a
  §107.41 controlled-airspace authorization a waiver.
- When uses_flight_tracking is true, identify only the user-entered
  flight_tracking_service when one is supplied. State that the service is used
  only for supplemental situational awareness and does not replace visual
  scanning, see-and-avoid responsibilities, or the RPIC's obligation to yield
  right of way to crewed aircraft. Never substitute or invent FlightAware or
  another service name.
- When the planning record indicates spectators, public access, or other
  non-participating persons, do not imply that §107.41 permits flight over
  them. State, when relevant, that operations will avoid non-participating
  persons/open-air assemblies unless a separately applicable Part 107
  compliance basis is documented in the planning record.
- Never invent a separate operations-over-people waiver or approval.
- Treat airspace_standard_procedures as AirSpace-provided standard language.
  Preserve those propositions without adding regulatory eligibility or approval.
- Prior operating experience, previous FAA coordination, or prior work with an
  ATC facility must remain historical context. Never convert it into a claim
  that coordination for the current application has occurred.
- Prior FAA approvals do not guarantee the current application, and previous
  Special Provisions must not be presented as current requirements.
- A stored ATC phone number or frequency is contact information only. Do not
  invent a preflight calling or frequency-monitoring requirement.
- Do not state that no direct ATC coordination or communication procedures are
  prescribed when the planning record contains a user-entered emergency ATC
  notification procedure. When there is no routine procedure, distinguish it
  from emergency notification: "No routine ATC check-in or communication
  procedure is prescribed. User-defined emergency notification procedures are
  addressed in Section 9."
- Preserve user-entered operating-frequency or duration language, including
  year-round operations, exactly in substance. Do not normalize, reinterpret,
  or remove it.

WRITING GUIDANCE BY SECTION:
- Operational Overview: Explain the user-entered mission purpose and requested
  FAA action in one concise opening narrative. Do not infer the mission.
- Operational Area and Airspace: Describe the actual planned operating area,
  coordinates, boundaries, altitude, nearby airport, and controlled airspace
  as one operational picture. Distinguish the actual operating GPS location
  from a facility mailing address.
- Airspace Integration and ATC Coordination: Describe the authorization,
  any user-entered ATC coordination, and compliance with issued special
  provisions. Do not add vague phrases such as "local airspace control".
- See-and-Avoid Methodology: Provide only concise visual-scanning, VO-support,
  and traffic-awareness context. Do not restate the supplied
  crewed_aircraft_conflict_response; AirSpace inserts that authoritative
  procedure deterministically after generation.
- Flight Envelope and Operating Limitations: State planned altitude,
  geographic limits, wind/weather limits, correct cloud clearances, and
  go/no-go/termination criteria without restating the entire operation.
- Crew Resource Management: Explain RPIC/VO responsibilities, communication,
  briefing, and only the experience explicitly supplied by the user.
- Aircraft Capabilities: Summarize assigned aircraft and supplied safety
  features. Make clear that these systems supplement aircraft control and
  obstacle avoidance, not crewed-aircraft separation.
- Operational Risk Controls: Use natural Preflight Planning, In-Flight
  Procedures, and Post-Flight Procedures subsections. Integrate ground and air
  risk controls without repeating the same controls in every subsection.
- Emergency Procedures: Organize only supplied procedures into concise
  subsections such as Lost Link / Flyaway, Airspace Conflict, Equipment or
  Aircraft Failure, and Emergency Landing / Incident Response. Treat saved
  ATC emergency contact information as user-supplied data, not as verified FAA
  information.

MANDATORY FACTUAL RULES:
- Use only facts contained in the supplied JSON planning record.
- Never invent equipment, capabilities, pilot qualifications, contacts,
  approvals, frequencies, coordinates, procedures, mitigations, event names,
  operating limits, or regulatory relief.
- Preserve numeric values, dates, identifiers, regulations, and contact
  information exactly as supplied.
- Preserve every substantive action in user-entered emergency and ATC
  procedures. Grammar and formatting may be improved, but exact facility
  identifiers, frequencies, phone numbers, coordinates, numeric limits, and
  other factual identifiers must remain unchanged.
- If important information is missing, state briefly that RPIC completion is
  required; do not manufacture a value.
- Do not claim or imply FAA approval.
- Treat all generated text as a draft requiring RPIC review."""


def _request_ai_document(
    payload: dict[str, Any],
    *,
    model: str,
    api_key: str,
    timeout: float,
) -> tuple[GeneratedConopsPackage, Any]:
    client = OpenAI(
        api_key=api_key,
        timeout=timeout,
        max_retries=2,
    )

    response = client.responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": _system_prompt(),
            },
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ],
        text_format=GeneratedConopsPackage,
    )

    package = response.output_parsed
    if package is None:
        raise OpenAIConopsError(
            "OpenAI returned no structured CONOPS package."
        )

    return package, response


def _usage_value(usage: Any, field_name: str) -> int | None:
    if usage is None:
        return None

    value = getattr(usage, field_name, None)
    if value is None and isinstance(usage, dict):
        value = usage.get(field_name)

    return int(value) if value is not None else None


def _validate_package(
    package: GeneratedConopsPackage,
    *,
    required_exact_identifiers: tuple[str, ...] = (),
) -> dict[str, GeneratedConopsSection]:
    expected = {
        item.key: item.title
        for item in CONOPS_DEFINITIONS
    }

    returned: dict[str, GeneratedConopsSection] = {}
    duplicates: list[str] = []

    for section in package.sections:
        if section.key in returned:
            duplicates.append(section.key)
        returned[section.key] = section

    missing = [
        key for key in expected
        if key not in returned
    ]
    unexpected = [
        key for key in returned
        if key not in expected
    ]

    if duplicates or missing or unexpected:
        details = []
        if duplicates:
            details.append(
                "duplicate sections: " + ", ".join(duplicates)
            )
        if missing:
            details.append(
                "missing sections: " + ", ".join(missing)
            )
        if unexpected:
            details.append(
                "unexpected sections: " + ", ".join(unexpected)
            )
        raise OpenAIConopsError(
            "The generated CONOPS structure was invalid ("
            + "; ".join(details)
            + ")."
        )

    for key, expected_title in expected.items():
        if returned[key].title.strip() != expected_title:
            raise OpenAIConopsError(
                "The generated CONOPS changed the required title "
                f"for {key!r}."
            )

    generated_text = "\n".join(
        [package.description_of_operations]
        + [section.content for section in package.sections]
    )
    missing_identifiers = [
        identifier
        for identifier in required_exact_identifiers
        if identifier and identifier not in generated_text
    ]
    if missing_identifiers:
        raise OpenAIConopsError(
            "The generated CONOPS changed or omitted an exact user-entered "
            "identifier: " + ", ".join(missing_identifiers) + ". "
            "No reviewed content was changed."
        )

    return returned


def _ensure_crewed_aircraft_response(
    package: GeneratedConopsPackage,
    operation,
) -> None:
    """Insert the authoritative stored procedure into generated Section 4."""
    procedure = _crewed_aircraft_conflict_response(operation)
    if not procedure:
        return

    section = next(
        (
            item
            for item in package.sections
            if item.key == "see-and-avoid"
        ),
        None,
    )
    if section is None:
        return

    intro = section.content.replace(procedure, " ")
    sentences = re.split(r"(?<=[.!?])\s+", intro.strip())
    concise_context = []
    for sentence in sentences:
        normalized = sentence.casefold()
        action_count = sum(
            term in normalized
            for term in ("descend", "reposition", "land", "maneuver")
        )
        duplicates_response = (
            action_count >= 2
            and (
                "crewed aircraft" in normalized
                or "conflict" in normalized
            )
        )
        if sentence.strip() and not duplicates_response:
            concise_context.append(sentence.strip())

    intro_text = " ".join(concise_context)
    section.content = "\n\n".join(
        part for part in (intro_text, procedure) if part
    )


def _ensure_emergency_airspace_conflict_reference(
    package: GeneratedConopsPackage,
) -> None:
    """Replace repeated Section 4 response actions with one cross-reference."""
    section = next(
        (
            item
            for item in package.sections
            if item.key == "emergency-procedures"
        ),
        None,
    )
    if section is None:
        return

    content = section.content.replace(
        EMERGENCY_AIRSPACE_CONFLICT_REFERENCE,
        " ",
    )
    retained = []
    for sentence in re.split(r"(?<=[.!?])\s+", content.strip()):
        normalized = sentence.casefold()
        action_count = sum(
            term in normalized
            for term in ("descend", "reposition", "land", "maneuver")
        )
        duplicate = (
            action_count >= 2
            and (
                "crewed aircraft" in normalized
                or "airspace conflict" in normalized
            )
        )
        if sentence.strip() and not duplicate:
            retained.append(sentence.strip())

    section.content = "\n\n".join(
        part
        for part in (
            " ".join(retained),
            EMERGENCY_AIRSPACE_CONFLICT_REFERENCE,
        )
        if part
    )


def _assigned_registration_lookup(operation) -> dict[str, str]:
    return {
        registration.casefold(): registration
        for assignment in operation.aircraft_assignments.select_related("drone")
        if (registration := assignment.drone.faa_registration_number.strip())
    }


def _canonicalize_structured_facts(
    package: GeneratedConopsPackage,
    operation,
) -> None:
    """Canonicalize narrow, database-owned facts without rewriting prose."""
    registrations = _assigned_registration_lookup(operation)
    coordinates = tuple(
        str(value)
        for value in (
            operation.location_latitude,
            operation.location_longitude,
        )
        if value is not None
    )

    def canonicalize(text: str) -> str:
        def registration_replacement(match):
            group_name = (
                "registration"
                if match.group("registration")
                else "registered_as"
            )
            supplied = match.group(group_name)
            canonical = registrations.get(supplied.casefold())
            if canonical is None:
                return match.group(0)
            start = match.start(group_name) - match.start()
            end = match.end(group_name) - match.start()
            return match.group(0)[:start] + canonical + match.group(0)[end:]

        text = AIRCRAFT_REGISTRATION_PATTERN.sub(
            registration_replacement,
            text,
        )

        def coordinate_replacement(match):
            generated = Decimal(match.group(0))
            for stored in coordinates:
                if abs(generated - Decimal(stored)) <= COORDINATE_TOLERANCE:
                    return stored
            return match.group(0)

        return COORDINATE_PATTERN.sub(coordinate_replacement, text)

    package.description_of_operations = canonicalize(
        package.description_of_operations
    )
    for section in package.sections:
        section.content = canonicalize(section.content)


def _ensure_operation_reference_coordinates(
    package: GeneratedConopsPackage,
    operation,
) -> None:
    """Insert one canonical operation-reference sentence into Section 2."""
    has_reference = (
        operation.location_latitude is None
        or operation.location_longitude is None
    ) is False
    has_launch = (
        operation.launch_latitude is None
        or operation.launch_longitude is None
    ) is False
    if not has_reference and not has_launch:
        return

    section = next(
        (
            item
            for item in package.sections
            if item.key == "operational-area-airspace"
        ),
        None,
    )
    if section is None:
        return

    retained = []
    for sentence in re.split(r"(?<=[.!?])\s+", section.content.strip()):
        if not sentence.strip():
            continue
        coordinate_role = re.search(
            r"\b(?:operation\s+reference\s+(?:point|coordinates?)|"
            r"launch\s+(?:site|location|point|coordinates?))\b",
            sentence,
            re.IGNORECASE,
        )
        if not coordinate_role or not COORDINATE_PATTERN.search(sentence):
            retained.append(sentence.strip())

    reference_sentence = ""
    if has_reference:
        reference_sentence = (
            "The operation reference point is latitude "
            f"{operation.location_latitude}, longitude "
            f"{operation.location_longitude}."
        )
    launch_sentence = ""
    if has_launch:
        launch_sentence = (
            "The launch location is latitude "
            f"{operation.launch_latitude}, longitude "
            f"{operation.launch_longitude}."
        )
    section.content = "\n\n".join(
        part
        for part in (
            " ".join(retained),
            reference_sentence,
            launch_sentence,
        )
        if part
    )


def _ensure_operations_over_people_avoided(
    package: GeneratedConopsPackage,
    operation,
) -> None:
    """Insert the authoritative avoided-over-people limitation once."""
    if operation.operations_over_people != "avoided":
        return

    section = next(
        (
            item
            for item in package.sections
            if item.key == "flight-envelope-limitations"
        ),
        None,
    )
    if section is None:
        return

    existing = section.content.replace(
        OPERATIONS_OVER_PEOPLE_AVOIDED,
        " ",
    ).strip()
    section.content = "\n\n".join(
        part
        for part in (existing, OPERATIONS_OVER_PEOPLE_AVOIDED)
        if part
    )


def _ensure_additional_operational_information(
    package: GeneratedConopsPackage,
    operation,
) -> None:
    """Ensure intentional additional planning information is not omitted."""
    information = (operation.additional_operational_information or "").strip()
    if not information:
        return
    if any(
        information in section.content
        for section in package.sections
    ):
        return

    normalized = information.casefold()
    if "atc" in normalized:
        target_key = "airspace-atc-coordination"
    elif any(
        term in normalized
        for term in ("risk control", "mitigation", "hazard", "safety control")
    ):
        target_key = "operational-risk-controls"
    else:
        target_key = "operational-overview"

    section = next(
        (item for item in package.sections if item.key == target_key),
        None,
    )
    if section is not None:
        section.content = (
            f"{section.content.strip()}\n\n"
            "Additional Operational Information / Controls\n"
            f"{information}"
        ).strip()


def _source_fidelity_requirements(operation):
    exact_identifiers = []
    for value in (
        operation.atc_facility_name,
        operation.atc_phone,
        operation.atc_frequency,
    ):
        value = (value or "").strip()
        if value:
            exact_identifiers.append(value)

    narrative_fields = (
        "operation_description",
        "operational_boundary_description",
        "containment_notes",
        "ground_environment_other",
        "ground_risk_mitigation",
        "air_risk_mitigation",
        "crewed_aircraft_conflict_response",
        "crowd_mitigation",
        "additional_operational_information",
        "safety_features_notes",
        "lost_link_actions",
        "flyaway_actions",
        "emergency_response_plan",
        "emergency_landing_areas",
        "aircraft_failure_actions",
        "injury_or_property_damage_actions",
        "incident_reporting_procedure",
        "termination_conditions",
        "atc_checkin_procedure",
        "atc_deviation_triggers",
        "communications_failure_actions",
        "weather_go_nogo",
        "night_lighting_description",
        "crew_briefing_procedure",
    )
    narrative_text = "\n".join(
        getattr(operation, field_name, "") or ""
        for field_name in narrative_fields
    )
    exact_identifiers.extend(
        match.group(0)
        for match in re.finditer(
            r"\b[A-Z0-9]{2,8}\s+ATC\b",
            narrative_text,
        )
    )
    exact_identifiers.extend(
        match.group(0)
        for match in re.finditer(
            r"\b\d{4}-P\d{3}-[A-Z]{2,4}-\d{4,8}\b",
            narrative_text,
        )
    )
    exact_identifiers.extend(
        match.group(0)
        for match in re.finditer(
            r"\b(?:K[A-Z]{3}|N\d{1,5}[A-Z]{0,2})\b",
            narrative_text,
        )
    )
    exact_identifiers.extend(
        match.group(0)
        for match in re.finditer(
            r"(?<!\d)[+-]?\d{1,3}\.\d{4,}(?!\d)",
            narrative_text,
        )
    )
    exact_identifiers.extend(
        match.group(0)
        for match in re.finditer(
            r"(?<!\w)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\w)",
            narrative_text,
        )
    )
    exact_identifiers.extend(
        match.group(0)
        for match in re.finditer(
            r"\b\d{3}\.\d{1,3}\s*MHz\b",
            narrative_text,
            re.IGNORECASE,
        )
    )
    # exact_identifiers.extend(
    #     match.group(1)
    #     for match in re.finditer(
    #         r"\b(\d+(?:\.\d+)?)\s*(?:feet|foot|ft\.?|mph|knots?|"
    #         r"nautical miles?|NM)\b",
    #         narrative_text,
    #         re.IGNORECASE,
    #     )
    # )

    return tuple(dict.fromkeys(exact_identifiers))


def _validate_discrete_source_fidelity(
    package: GeneratedConopsPackage,
    operation,
) -> None:
    generated_text = "\n".join(
        [package.description_of_operations]
        + [section.content for section in package.sections]
    )

    expected_reference = (
        operation.location_latitude,
        operation.location_longitude,
    )
    reference_role = (
        r"(?:\b(?:the\s+)?(?:operation\s+)?reference\s+"
        r"(?:point|coordinates?)\b|"
        r"\b(?:the\s+)?operation\s+is\s+centered\s+at\b)"
    )
    reference_pair_pattern = re.compile(
        reference_role
        + rf"(?:(?![.!?]\s).){{0,80}}?(?:latitude\s*)?"
        rf"(?P<latitude>{COORDINATE_PATTERN.pattern})"
        rf"(?:(?![.!?]\s).){{0,40}}?(?:longitude\s*)?"
        rf"(?P<longitude>{COORDINATE_PATTERN.pattern})",
        re.IGNORECASE,
    )
    for match in reference_pair_pattern.finditer(generated_text):
        for label, expected in zip(
            ("latitude", "longitude"),
            expected_reference,
        ):
            if expected is None:
                continue
            supplied = Decimal(match.group(label))
            if abs(supplied - Decimal(str(expected))) > COORDINATE_TOLERANCE:
                raise OpenAIConopsError(
                    "The generated CONOPS substituted a different operation "
                    f"reference {label}. No reviewed content was changed."
                )

    altitude = operation.maximum_planned_altitude_agl
    if altitude is not None and not re.search(
        rf"\b{altitude}\s*(?:feet|ft\.?)\s+AGL\b",
        generated_text,
        re.IGNORECASE,
    ):
        raise OpenAIConopsError(
            "The generated CONOPS changed or omitted the requested maximum "
            "altitude. No reviewed content was changed."
        )

    assigned_registrations = _assigned_registration_lookup(operation)
    mentioned_registrations = {
        registration
        for match in AIRCRAFT_REGISTRATION_PATTERN.finditer(generated_text)
        for registration in (
            match.group("registration") or match.group("registered_as"),
        )
    }
    unexpected_registrations = {
        registration
        for registration in mentioned_registrations
        if registration.casefold() not in assigned_registrations
    }
    if unexpected_registrations:
        raise OpenAIConopsError(
            "The generated CONOPS substituted an aircraft FAA registration "
            "that is not assigned to this operation: "
            + ", ".join(sorted(unexpected_registrations))
            + ". No reviewed content was changed."
        )

    month_names = (
        "January|February|March|April|May|June|July|August|September|"
        "October|November|December"
    )
    for label, value in (
        ("operation start date", operation.start_date),
        ("operation end date", operation.end_date),
    ):
        if value is None:
            continue
        date_patterns = (
            re.escape(value.isoformat()),
            rf"\b(?:{month_names})\s+0?{value.day},\s+{value.year}\b",
            rf"\b0?{value.month}/0?{value.day}/{value.year}\b",
        )
        if not any(
            re.search(pattern, generated_text, re.IGNORECASE)
            for pattern in date_patterns
        ):
            raise OpenAIConopsError(
                f"The generated CONOPS changed or omitted the {label}. "
                "No reviewed content was changed."
            )


def _validate_geometry_source_fidelity(
    package: GeneratedConopsPackage,
    operation,
) -> None:
    generated_text = "\n".join(
        [package.description_of_operations]
        + [section.content for section in package.sections]
    )
    normalized = generated_text.casefold()

    number = r"\d+(?:\.\d+)?|\d+\s*/\s*\d+|\d+\s*-\s*\d+"
    radius_mentions = re.findall(
        rf"\bradius\b[^.\n]{{0,35}}?\b({number})\s*"
        rf"(?:nautical\s*miles?|nm)\b|\b({number})\s*"
        rf"(?:nautical\s*miles?|nm)\b[^.\n]{{0,15}}\bradius\b",
        normalized,
    )

    def radius_value(raw_value):
        compact = re.sub(r"\s+", "", raw_value)
        if "/" in compact:
            numerator, denominator = compact.split("/", 1)
            return (Decimal(numerator) / Decimal(denominator),)
        if "-" in compact:
            lower, upper = compact.split("-", 1)
            return (Decimal(lower), Decimal(upper))
        return (Decimal(compact),)

    mentioned_values = [
        radius_value(first or second)
        for first, second in radius_mentions
    ]
    expected_radius_values = {
        "0.1_nm": (Decimal("0.1"),),
        "0.25_nm": (Decimal("0.25"),),
        "0.5_nm": (Decimal("0.5"),),
        "0.75_nm": (Decimal("0.75"),),
        "1_nm": (Decimal("1"),),
        "1_2_nm": (Decimal("1"), Decimal("2")),
        "2_3_nm": (Decimal("2"), Decimal("3")),
    }

    if operation.dronezone_radius == "blanket_wide_area" and mentioned_values:
        raise OpenAIConopsError(
            "The generated CONOPS invented a numeric radius for a Blanket "
            "Area / Wide Area request. No reviewed content was changed."
        )
    expected_radius = expected_radius_values.get(operation.dronezone_radius)
    if expected_radius and any(
        value != expected_radius
        for value in mentioned_values
    ):
        raise OpenAIConopsError(
            "The generated CONOPS substituted a different numeric DroneZone "
            "Requested Radius. No reviewed content was changed."
        )

    if operation.operation_area_type == "multiple_sites" and re.search(
        r"\b(?:single|one)\s+(?:fixed\s+)?(?:operating\s+)?site\b|"
        r"\bfixed-radius site\b|\bsingle fixed launch (?:point|site)\b",
        normalized,
    ):
        raise OpenAIConopsError(
            "The generated CONOPS contradicted the Multiple Sites "
            "operational-area geometry. No reviewed content was changed."
        )

    for label, value in (
        ("launch", operation.launch_location),
        ("recovery", operation.recovery_location),
    ):
        if (value or "").strip().casefold() == "varies":
            fixed_location = re.search(
                rf"\b(?:fixed|single|specific|designated|primary)\s+{label}\b|"
                rf"\b{label}\s+(?:site|location|point)\b[^.\n]{{0,40}}"
                rf"\b(?:fixed|specific|designated)\b",
                normalized,
            )
            coordinate_location = any(
                COORDINATE_PATTERN.search(sentence)
                for sentence in re.split(
                    r"(?<=[.!?])\s+|\n+",
                    generated_text,
                )
                if re.search(
                    rf"\b{label}\s+(?:site|location|point|coordinates?)\b",
                    sentence,
                    re.IGNORECASE,
                )
                and not re.search(
                    rf"\bnot\s+(?:a\s+)?{label}\b",
                    sentence,
                    re.IGNORECASE,
                )
            )
            if fixed_location or coordinate_location:
                raise OpenAIConopsError(
                    f"The generated CONOPS contradicted that the {label} "
                    "location varies. No reviewed content was changed."
                )

    reference_coordinates = tuple(
        Decimal(str(value))
        for value in (
            operation.location_latitude,
            operation.location_longitude,
        )
        if value is not None
    )
    if len(reference_coordinates) == 2:
        for context in (
            sentence
            for sentence in re.split(
                r"(?<=[.!?])\s+|\n+",
                generated_text,
            )
            if re.search(
                r"\b(?:launch|recovery)\s+"
                r"(?:site|location|point|coordinates?)\b",
                sentence,
                re.IGNORECASE,
            )
        ):
            normalized_context = context.casefold()
            if re.search(
                r"\bnot\s+(?:a\s+)?(?:launch|recovery)\b",
                normalized_context,
            ):
                continue
            mentioned = tuple(
                Decimal(match.group(0))
                for match in COORDINATE_PATTERN.finditer(context)
            )
            pair_matches = len(mentioned) >= 2 and all(
                abs(supplied - expected) <= COORDINATE_TOLERANCE
                for supplied, expected in zip(mentioned[:2], reference_coordinates)
            )
            single_matches = len(mentioned) == 1 and any(
                abs(mentioned[0] - expected) <= COORDINATE_TOLERANCE
                for expected in reference_coordinates
            )
            if pair_matches or single_matches:
                raise OpenAIConopsError(
                    "The generated CONOPS treated operation reference "
                    "coordinates as launch or recovery coordinates. "
                    "No reviewed content was changed."
                )


def _record_generation_error(
    approval: OperationApproval,
    user,
    message: str,
) -> None:
    application, _ = ApprovalApplication.objects.get_or_create(
        approval=approval,
        defaults={
            "user": user,
            "status": "draft",
            "description": "",
            "locked_description": False,
            "ai_generation_model": "",
            "ai_prompt_version": "",
            "ai_generation_error": "",
        },
    )
    application.ai_generation_error = message[:5000]
    application.save(
        update_fields=[
            "ai_generation_error",
            "updated_at",
        ]
    )


def latest_conops_source_updated_at(
    approval: OperationApproval,
):
    """
    Return the newest timestamp among saved records supplied to ChatGPT
    for this approval's CONOPS.
    """
    timestamps = [
        getattr(approval.operation, "updated_at", None),
        getattr(approval, "updated_at", None),
    ]

    for assignment in approval.operation.aircraft_assignments.all():
        timestamps.append(
            getattr(assignment, "updated_at", None)
        )

    return max(
        (
            value
            for value in timestamps
            if value is not None
        ),
        default=None,
    )


def _looks_like_legacy_combined_description(text: str) -> bool:
    value = (text or "").strip()
    legacy_headings = (
        "1. Operation Overview and Purpose",
        "2. Requested FAA Waiver / Approval",
        "5. Aircraft and Safety Systems",
        "11. Approval-Specific Risk Mitigations",
        "13. Operational Commitment",
    )
    return sum(
        1 for heading in legacy_headings if heading in value
    ) >= 2


def generate_ai_conops(
    approval: OperationApproval,
    user,
    *,
    regenerate_unlocked: bool = True,
) -> ApprovalApplication:
    api_key = str(_setting("OPENAI_API_KEY", "") or "")
    model = str(
        _setting("OPENAI_TEXT_MODEL", "gpt-4.1-mini")
        or "gpt-4.1-mini"
    )
    timeout = float(
        _setting("OPENAI_REQUEST_TIMEOUT", 120) or 120
    )

    if not api_key:
        raise OpenAIConopsError(
            "OPENAI_API_KEY is not configured for this environment."
        )

    payload = _operation_payload(approval)

    try:
        package, response = _request_ai_document(
            payload,
            model=model,
            api_key=api_key,
            timeout=timeout,
        )
        _ensure_crewed_aircraft_response(
            package,
            approval.operation,
        )
        _ensure_emergency_airspace_conflict_reference(package)
        _ensure_operations_over_people_avoided(
            package,
            approval.operation,
        )
        _ensure_additional_operational_information(
            package,
            approval.operation,
        )
        _canonicalize_structured_facts(
            package,
            approval.operation,
        )
        required_exact_identifiers = _source_fidelity_requirements(
            approval.operation
        )
        returned = _validate_package(
            package,
            required_exact_identifiers=required_exact_identifiers,
        )
        _validate_discrete_source_fidelity(
            package,
            approval.operation,
        )
        _validate_geometry_source_fidelity(
            package,
            approval.operation,
        )
        _ensure_operation_reference_coordinates(
            package,
            approval.operation,
        )
    except (
        OpenAIConopsError,
        ValidationError,
        ValueError,
        TypeError,
    ) as exc:
        message = str(exc) or (
            "OpenAI returned an invalid CONOPS package."
        )
        _record_generation_error(
            approval,
            user,
            message,
        )
        raise OpenAIConopsError(message) from exc
    except Exception as exc:
        message = (
            "OpenAI could not generate the CONOPS package. "
            "No reviewed content was changed."
        )
        _record_generation_error(
            approval,
            user,
            message,
        )
        raise OpenAIConopsError(message) from exc

    generated_at = timezone.now()

    # The API call completes before this atomic block. A failed API request
    # therefore cannot leave partially updated CONOPS text.
    with transaction.atomic():
        application = get_or_create_application(
            approval,
            user,
        )

        application_update_fields = [
            "ai_generation_model",
            "ai_generated_at",
            "conops_source_updated_at",
            "ai_prompt_version",
            "ai_generation_error",
            "ai_input_tokens",
            "ai_output_tokens",
            "updated_at",
        ]

        legacy_combined_description = (
            _looks_like_legacy_combined_description(
                application.description
            )
        )
        if (
            not application.locked_description
            or legacy_combined_description
        ):
            application.description = (
                package.description_of_operations.strip()
            )
            application.description_generated_at = generated_at
            application.description_is_complete = False
            application.description_validated_at = None
            if legacy_combined_description:
                application.locked_description = False
                application_update_fields.append(
                    "locked_description"
                )
            application_update_fields.extend(
                [
                    "description",
                    "description_generated_at",
                    "description_is_complete",
                    "description_validated_at",
                ]
            )

        usage = getattr(response, "usage", None)
        application.ai_generation_model = model
        application.ai_generated_at = generated_at
        application.conops_source_updated_at = (
            latest_conops_source_updated_at(approval)
        )
        application.ai_prompt_version = PROMPT_VERSION
        application.ai_generation_error = ""
        application.ai_input_tokens = _usage_value(
            usage,
            "input_tokens",
        )
        application.ai_output_tokens = _usage_value(
            usage,
            "output_tokens",
        )
        application.save(
            update_fields=list(
                dict.fromkeys(application_update_fields)
            )
        )

        expected = {
            item.key: item.title
            for item in CONOPS_DEFINITIONS
        }

        application.conops_sections.exclude(
            section_key__in=expected.keys()
        ).delete()

        for key, title in expected.items():
            generated = returned[key]
            section, created = ConopsSection.objects.get_or_create(
                application=application,
                section_key=key,
                defaults={
                    "user": user,
                    "title": title,
                    "content": generated.content.strip(),
                    "locked": False,
                    "is_complete": False,
                    "generated_at": generated_at,
                },
            )

            if created:
                continue

            update_fields = []
            if section.title != title:
                section.title = title
                update_fields.append("title")

            if regenerate_unlocked and not section.locked:
                section.content = generated.content.strip()
                section.generated_at = generated_at
                section.is_complete = False
                section.validated_at = None
                update_fields.extend(
                    [
                        "content",
                        "generated_at",
                        "is_complete",
                        "validated_at",
                    ]
                )

            if update_fields:
                update_fields.append("updated_at")
                section.save(update_fields=update_fields)

        approval.operation.generated_conops_at = generated_at
        approval.operation.save(
            update_fields=["generated_conops_at"]
        )

    return application
