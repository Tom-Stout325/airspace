from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .conops import CONOPS_DEFINITIONS, get_or_create_application
from .models import ApprovalApplication, ConopsSection, OperationApproval


PROMPT_VERSION = "controlled-airspace-v2"


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

Create two separate deliverables from the supplied planning record:

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
   - Produce the complete CONOPS using every key/title in expected_sections
     exactly once and in the supplied order.
   - Treat the sections as chapters of one coherent document.
   - Prefer concise narrative paragraphs.
   - Use bullets only when they improve readability for aircraft capabilities,
     procedural steps, operating limitations, or emergency actions.
   - Do not turn ordinary planning fields into label/value lines.
   - Avoid repeating the same fact in multiple sections.
   - Target a concise attachment rather than an exhaustive safety manual.

Writing guidance by section:
- Operational Overview: Explain mission purpose and requested FAA action in
  one concise opening narrative.
- Operational Area and Airspace: Describe the physical operating area,
  boundaries, location, altitude, nearby airport, and controlled airspace as
  one operational picture.
- Airspace Integration and ATC Coordination: Explain how the operation
  integrates with the controlling airspace and any entered ATC coordination,
  contact, frequency, check-in, or UASFM-related procedures. Do not invent ATC
  requirements that are not in the planning record.
- See-and-Avoid Methodology: Explain visual scanning, VO support, traffic
  awareness tools, and the immediate action used for a crewed-aircraft
  conflict.
- Flight Envelope and Operating Limitations: State the planned altitude,
  weather/wind limits, geographic limitations, and go/no-go or termination
  criteria without restating the entire operation.
- Crew Resource Management: Explain RPIC/VO responsibilities, communication,
  briefing, and relevant documented experience.
- Aircraft Capabilities: Summarize each assigned aircraft and the safety
  capabilities actually supplied in the planning record. Bullets are
  appropriate here.
- Operational Risk Controls: Write three natural subsections inside the
  content: Preflight Planning, In-Flight Procedures, and Post-Flight
  Procedures. Integrate ground-risk and air-risk controls into those
  procedures.
- Emergency Procedures: Organize the supplied procedures into concise
  subsections such as Lost Link / Flyaway, Airspace Conflict, Equipment or
  Aircraft Failure, and Emergency Landing / Incident Response when supported
  by the planning record.

Mandatory factual rules:
- Use only facts contained in the supplied JSON planning record.
- Never invent equipment, capabilities, pilot qualifications, contacts,
  approvals, frequencies, coordinates, procedures, mitigations, or operating
  limits.
- Preserve numeric values, dates, identifiers, regulations, and contact
  information exactly as supplied.
- If an important fact is missing, state briefly that RPIC completion is
  required; do not manufacture a value.
- Do not claim or imply FAA approval.
- Distinguish a §107.41 airspace authorization from an operational waiver.
- For a standard §107.41 authorization, do not create standalone chapters
  titled Equivalent Level of Safety, Safety Justification, Approval-Specific
  Risk Mitigations, or Operational Commitment. Integrate relevant safety
  material naturally into the operational sections.
- Treat all generated text as a draft requiring RPIC review.
"""


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

    return returned


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
        returned = _validate_package(package)
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
            if legacy_combined_description:
                application.locked_description = False
                application_update_fields.append(
                    "locked_description"
                )
            application_update_fields.extend(
                [
                    "description",
                    "description_generated_at",
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
