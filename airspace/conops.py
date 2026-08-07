from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from django.db import transaction
from django.utils import timezone

from .models import (
    ApprovalApplication,
    ConopsSection,
    OperationApproval,
    OperationsPlanning,
)


@dataclass(frozen=True)
class ConopsDefinition:
    key: str
    title: str
    builder: Callable[[OperationApproval], str]


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _sentence(value, fallback="Not yet provided.") -> str:
    text = _clean(value)
    return text if text else fallback


def _choice_labels(values, choices) -> str:
    lookup = dict(choices)
    labels = [lookup.get(value, value) for value in (values or [])]
    return ", ".join(str(label) for label in labels if label)


def _pilot_name(operation) -> str:
    manual = _clean(operation.pilot_name_manual)
    if manual:
        return manual

    profile = operation.pilot_profile
    if profile is None:
        return "The Remote Pilot in Command has not yet been identified."

    profile_user = getattr(profile, "user", None)
    first_name = _clean(getattr(profile_user, "first_name", ""))
    last_name = _clean(getattr(profile_user, "last_name", ""))
    full_name = " ".join(
        part for part in (first_name, last_name) if part
    ).strip()

    return (
        full_name
        or _clean(getattr(profile_user, "email", ""))
        or "The saved pilot profile"
    )


def _pilot_certificate(operation) -> str:
    manual = _clean(operation.pilot_cert_manual)
    if manual:
        return manual

    profile = operation.pilot_profile
    if profile is None:
        return "not yet entered"

    return (
        _clean(getattr(profile, "faa_certificate_number", ""))
        or _clean(getattr(profile, "license_number", ""))
        or "not yet entered"
    )


def _date_range(operation) -> str:
    if not operation.start_date:
        return "Dates have not yet been established."

    start = operation.start_date.strftime("%B %d, %Y")
    if operation.end_date and operation.end_date != operation.start_date:
        end = operation.end_date.strftime("%B %d, %Y")
        return f"{start} through {end}"

    return start


def _location_line(operation) -> str:
    parts = [
        _clean(operation.venue_name),
        _clean(operation.street_address),
    ]

    city_state_zip = " ".join(
        part
        for part in [
            _clean(operation.location_city),
            _clean(operation.location_state),
            _clean(operation.zip_code),
        ]
        if part
    )
    if city_state_zip:
        parts.append(city_state_zip)

    return ", ".join(part for part in parts if part) or (
        "The operation location has not yet been fully entered."
    )


def _coordinates(operation) -> str:
    if (
        operation.location_latitude is None
        or operation.location_longitude is None
    ):
        return "Operation coordinates have not yet been entered."

    return (
        f"{operation.location_latitude}, "
        f"{operation.location_longitude}"
    )


def _airport_description(operation) -> str:
    airport = operation.nearest_airport_ref
    if airport is None:
        identifier = _clean(operation.nearest_airport)
        if identifier:
            return f"Nearest airport identifier: {identifier}."
        return "The nearest airport has not yet been identified."

    distance = (
        f", approximately {operation.distance_to_airport_nm} NM "
        "from the operation"
        if operation.distance_to_airport_nm is not None
        else ""
    )
    return f"The nearest airport is {airport}{distance}."


def _aircraft_paragraphs(operation) -> str:
    assignments = list(
        operation.aircraft_assignments.select_related("drone").all()
    )
    if not assignments:
        return "No aircraft have been assigned to the operation."

    paragraphs = []
    for assignment in assignments:
        drone = assignment.drone
        label = _clean(str(drone)) or (
            f"{_clean(drone.manufacturer)} {_clean(drone.model)}"
        ).strip()

        details = [f"The operation will use {label}."]

        if _clean(drone.faa_registration_number):
            details.append(
                "FAA registration: "
                f"{drone.faa_registration_number}."
            )

        if _clean(assignment.planned_payload):
            details.append(
                "Planned payload or attached equipment: "
                f"{assignment.planned_payload}."
            )

        readiness = [
            (
                "registration verified"
                if assignment.registration_verified
                else "registration verification pending"
            ),
            (
                "Remote ID verified"
                if assignment.remote_id_verified
                else "Remote ID verification pending"
            ),
            (
                "airworthiness verified"
                if assignment.preflight_airworthiness_verified
                else "airworthiness verification pending"
            ),
            (
                "current firmware confirmed"
                if assignment.current_firmware_installed
                else "firmware confirmation pending"
            ),
        ]
        details.append(
            "Readiness status: " + ", ".join(readiness) + "."
        )

        safety = _clean(assignment.safety_features_snapshot)
        if safety:
            details.append(
                "Aircraft safety systems and features include: "
                f"{safety}"
            )

        notes = _clean(assignment.operation_specific_safety_notes)
        if notes:
            details.append(
                "Operation-specific aircraft safety notes: "
                f"{notes}"
            )

        paragraphs.append(" ".join(details))

    return "\n\n".join(paragraphs)


def _operation_overview(approval) -> str:
    operation = approval.operation
    purpose = _choice_labels(
        operation.purpose_operations,
        OperationsPlanning.PURPOSE_OPERATIONS_CHOICES,
    )

    return (
        f"{operation.operation_title} is a planned UAS operation at "
        f"{_location_line(operation)}. The operation is proposed for "
        f"{_date_range(operation)}. "
        f"The mission purpose is {purpose or 'not yet specified'}. "
        f"{_sentence(operation.operation_description)}"
    )


def _requested_approval(approval) -> str:
    regulation = _clean(approval.regulation_display)
    regulation_text = (
        f" The associated regulation is {regulation}."
        if regulation
        else ""
    )
    return (
        f"The requested FAA waiver or approval is "
        f"{approval.approval_type}.{regulation_text}\n\n"
        f"Requested operation:\n"
        f"{_sentence(approval.requested_operation)}"
    )


def _is_controlled_airspace_only_request(approval) -> bool:
    return (
        approval.approval_type.code == "controlled-airspace"
        and not approval.operation.approvals.exclude(pk=approval.pk).exists()
    )


def _dates_location_airspace(approval) -> str:
    operation = approval.operation
    timeframe = _choice_labels(
        operation.timeframe,
        OperationsPlanning.TIMEFRAME_CHOICES,
    )

    altitude = (
        "Requested maximum altitude: "
        f"{operation.maximum_planned_altitude_agl} feet AGL, subject to "
        "the altitude authorized by the FAA."
        if operation.maximum_planned_altitude_agl is not None
        else "Maximum planned altitude: not yet entered."
    )

    return (
        f"Proposed operating dates: {_date_range(operation)}.\n"
        f"Planned operating periods: "
        f"{timeframe or 'not yet entered'}.\n"
        f"Local time zone: "
        f"{_clean(operation.local_time_zone) or 'not yet entered'}.\n"
        f"Operation location: {_location_line(operation)}.\n"
        f"Coordinates: {_coordinates(operation)}\n"
        f"Airspace classification: "
        f"{operation.get_airspace_class_display() if operation.airspace_class else 'not yet determined'}.\n"
        f"{altitude}\n"
        f"{_airport_description(operation)}"
    )


def _rpic_and_crew(approval) -> str:
    operation = approval.operation
    hours = (
        f"{operation.pilot_flight_hours} hours"
        if operation.pilot_flight_hours is not None
        else "not yet calculated"
    )
    procedures = _choice_labels(
        operation.prepared_procedures,
        OperationsPlanning.PREPARED_PROCEDURES_CHOICES,
    )

    return (
        f"The Remote Pilot in Command is {_pilot_name(operation)}. "
        f"FAA Remote Pilot certificate number: "
        f"{_pilot_certificate(operation)}. "
        f"Documented UAS flight experience: {hours}.\n\n"
        f"Total planned crew members: "
        f"{operation.crew_count if operation.crew_count is not None else 'not yet entered'}.\n"
        f"Crew communications method: "
        f"{_sentence(operation.crew_communications_method)}\n"
        f"Communications failure procedures: "
        f"{_sentence(operation.communications_failure_actions)}\n"
        f"Crew briefing notes: "
        f"{_sentence(operation.crew_briefing_procedure)}\n"
        f"Prepared procedures: "
        f"{procedures or 'not yet selected'}."
    )


def _aircraft_and_systems(approval) -> str:
    return _aircraft_paragraphs(approval.operation)


def _area_and_containment(approval) -> str:
    operation = approval.operation
    geometry = (
        operation.get_operation_area_type_display()
        if operation.operation_area_type
        else "not yet selected"
    )
    containment = (
        operation.get_containment_method_display()
        if operation.containment_method
        else "not yet selected"
    )

    return (
        f"The operational area geometry is {geometry}. "
        f"{_sentence(operation.operation_area_description)}\n\n"
        f"The primary containment method is {containment}. "
        f"Containment procedures: "
        f"{_sentence(operation.containment_notes)}\n\n"
        f"Primary launch site: "
        f"{_sentence(operation.launch_location)}\n"
        f"Planned landing location: "
        f"{_sentence(operation.recovery_location)}"
    )


def _ground_air_risk(approval) -> str:
    operation = approval.operation
    ground_environment = _choice_labels(
        operation.ground_environment,
        OperationsPlanning.GROUND_ENVIRONMENT_CHOICES,
    )

    support_systems = []
    if operation.has_visual_observer:
        support_systems.append("visual observers")
    if operation.uses_flight_tracking:
        support_systems.append(
            "crewed-aircraft traffic awareness tools"
        )
    if operation.uses_drone_detection:
        support_systems.append("drone detection equipment")

    support_text = (
        ", ".join(support_systems)
        if support_systems
        else "no additional support systems have been selected"
    )

    return (
        f"Ground environment: "
        f"{ground_environment or 'not yet entered'}. "
        f"{_sentence(operation.ground_environment_other, '')}\n"
        f"Estimated maximum crowd size: "
        f"{_clean(operation.estimated_crowd_size) or 'not yet entered'}.\n\n"
        f"Ground risk controls:\n"
        f"{_sentence(operation.ground_risk_mitigation)}\n\n"
        f"Airspace risk controls:\n"
        f"{_sentence(operation.air_risk_mitigation)}\n\n"
        f"Additional operational support includes {support_text}."
    ).strip()


def _lost_link_emergency(approval) -> str:
    operation = approval.operation
    lost_link_behavior = (
        operation.get_lost_link_behavior_display()
        if operation.lost_link_behavior
        else "not yet selected"
    )
    rth = (
        f"{operation.rth_altitude_ft_agl} feet AGL"
        if operation.rth_altitude_ft_agl is not None
        else "not yet entered"
    )

    return (
        f"Programmed lost-link behavior: {lost_link_behavior}.\n"
        f"Return-to-Home altitude: {rth}.\n\n"
        f"Lost-link procedures:\n"
        f"{_sentence(operation.lost_link_actions)}\n\n"
        f"Flyaway procedures:\n"
        f"{_sentence(operation.flyaway_actions)}\n\n"
        f"Emergency response procedures:\n"
        f"{_sentence(operation.emergency_response_plan)}\n\n"
        f"Emergency landing areas:\n"
        f"{_sentence(operation.emergency_landing_areas)}\n\n"
        f"Injury or property-damage response:\n"
        f"{_sentence(operation.injury_or_property_damage_actions)}\n\n"
        f"Incident reporting procedures:\n"
        f"{_sentence(operation.incident_reporting_procedure)}\n\n"
        f"Operation suspension and termination criteria:\n"
        f"{_sentence(operation.termination_conditions)}"
    )


def _weather_night(approval) -> str:
    operation = approval.operation
    max_wind = (
        f"{operation.max_wind_mph} MPH"
        if operation.max_wind_mph is not None
        else "not yet entered"
    )
    visibility = (
        f"{operation.min_visibility_sm} statute miles"
        if operation.min_visibility_sm is not None
        else "not yet entered"
    )
    ceiling = (
        f"{operation.minimum_cloud_ceiling_ft} feet"
        if operation.minimum_cloud_ceiling_ft is not None
        else "not yet entered"
    )

    return (
        f"Maximum operating wind: {max_wind}.\n"
        f"Operator minimum visibility: {visibility}.\n"
        f"Operator minimum cloud ceiling: {ceiling}.\n"
        f"Weather information sources: "
        f"{_sentence(operation.weather_source)}\n\n"
        f"Weather go/no-go criteria:\n"
        f"{_sentence(operation.weather_go_nogo)}\n\n"
        f"Night lighting and night-operation procedures:\n"
        f"{_sentence(operation.night_lighting_description)}"
    )


def _safety_justification(approval) -> str:
    return _sentence(approval.safety_justification)


def _approval_risk_mitigations(approval) -> str:
    return _sentence(approval.risk_mitigations)


def _equivalent_safety(approval) -> str:
    return _sentence(approval.equivalent_level_of_safety)


def _conclusion(approval) -> str:
    operation = approval.operation
    return (
        f"The proposed {operation.operation_title} operation will be "
        f"conducted only when the RPIC confirms that the aircraft, crew, "
        f"weather, operating area, communications, and required FAA "
        f"authorizations are ready. The operation will be suspended or "
        f"terminated whenever the documented limits or safety controls "
        f"cannot be maintained."
    )


# AIRSPACE_CONOPS_DOCUMENT_STYLE_V2
def _controlled_area_airspace(approval) -> str:
    return (
        f"{_dates_location_airspace(approval)}\n\n"
        f"{_area_and_containment(approval)}"
    )


def _airspace_atc_coordination(approval) -> str:
    operation = approval.operation
    details = []

    if _clean(operation.atc_facility_name):
        details.append(
            f"The ATC facility identified in the planning record is "
            f"{operation.atc_facility_name}."
        )

    if _clean(operation.atc_coordination_method):
        details.append(
            "The user-entered coordination method is "
            f"{operation.get_atc_coordination_method_display()}."
        )

    if _clean(operation.atc_phone):
        details.append(
            f"The planning record lists ATC telephone "
            f"{operation.atc_phone}."
        )

    if _clean(operation.atc_frequency):
        details.append(
            f"The planning record lists ATC frequency "
            f"{operation.atc_frequency}."
        )

    if _clean(operation.atc_checkin_procedure):
        details.append(
            "The user-entered ATC/check-in procedure is: "
            f"{operation.atc_checkin_procedure}"
        )

    if _is_controlled_airspace_only_request(approval):
        details.append(
            "This application requests a controlled-airspace authorization "
            "under §107.41 and does not request relief from any other Part "
            "107 requirement."
        )

    if not details:
        details.append(
            "The operation will not begin until the required §107.41 "
            "authorization has been issued. The RPIC will comply with all "
            "altitude limits, geographic restrictions, operating times, "
            "notification requirements, and other special provisions "
            "contained in the issued authorization."
        )

    return " ".join(details)

def _see_and_avoid(approval) -> str:
    operation = approval.operation
    details = []

    if _clean(operation.air_risk_mitigation):
        details.append(_clean(operation.air_risk_mitigation))

    if operation.has_visual_observer:
        details.append(
            "Visual observers will support continuous scanning for crewed "
            "aircraft and other airborne hazards."
        )

    if operation.uses_flight_tracking:
        tracking_service = _clean(operation.flight_tracking_service)
        tracking_subject = tracking_service or (
            "The documented crewed-aircraft tracking system"
        )
        details.append(
            f"{tracking_subject} will be used as a supplemental "
            "situational-awareness tool and does not replace visual scanning, "
            "see-and-avoid responsibilities, or the RPIC's obligation to "
            "yield right of way to crewed aircraft."
        )

    details.append(
        "Upon detection of a potential conflict with a crewed aircraft, "
        "the RPIC will immediately descend, reposition, land, or otherwise "
        "suspend the UAS operation as necessary to maintain safe separation."
    )

    return " ".join(details)


def _flight_envelope_limitations(approval) -> str:
    operation = approval.operation
    parts = []

    if operation.maximum_planned_altitude_agl is not None:
        parts.append(
            "The sUAS will operate at or below the requested maximum altitude "
            f"of {operation.maximum_planned_altitude_agl} feet AGL and will "
            "not exceed any lower altitude limitation specified in the FAA "
            "authorization."
        )

    if operation.max_wind_mph is not None:
        parts.append(
            f"The maximum planned operating wind is "
            f"{operation.max_wind_mph} MPH."
        )

    if operation.uses_standard_part_107_weather_minimums:
        parts.append(
            "Standard Part 107 weather minimums will apply: at least "
            "3 statute miles flight visibility and at least 500 feet below "
            "and 2,000 feet horizontally from clouds."
        )

    if _clean(operation.weather_go_nogo):
        parts.append(
            f"Weather and operational go/no-go criteria include: "
            f"{operation.weather_go_nogo}"
        )

    if _clean(operation.termination_conditions):
        parts.append(
            f"Operations will be suspended or terminated when: "
            f"{operation.termination_conditions}"
        )

    return " ".join(parts) or (
        "Flight-envelope and operating limitations require RPIC completion."
    )

def _crew_resource_management(approval) -> str:
    return _rpic_and_crew(approval)


def _aircraft_capabilities(approval) -> str:
    return _aircraft_and_systems(approval)


def _operational_risk_controls(approval) -> str:
    operation = approval.operation
    sections = []

    preflight = []
    if _clean(operation.weather_source):
        preflight.append(
            f"review weather information using {operation.weather_source}"
        )
    if _clean(operation.ground_risk_mitigation):
        preflight.append("verify ground-risk controls are in place")
    if _clean(operation.air_risk_mitigation):
        preflight.append("confirm airspace-risk controls and traffic monitoring")

    if preflight:
        sections.append(
            "Preflight Planning\n"
            "Before flight, the RPIC will "
            + ", ".join(preflight)
            + ", and will conduct the documented crew and aircraft readiness checks."
        )

    sections.append(
        "In-Flight Procedures\n"
        + _ground_air_risk(approval)
    )

    sections.append(
        "Post-Flight Procedures\n"
        "Following flight, the RPIC will inspect the aircraft, document "
        "relevant flight information and anomalies, and ensure any incident "
        "or maintenance issue is addressed before the next operation."
    )

    return "\n\n".join(sections)


def _emergency_procedures(approval) -> str:
    return _lost_link_emergency(approval)


def ordered_conops_sections(application):
    """
    Return current CONOPS sections in document order, never alphabetical order.
    """
    by_key = {
        section.section_key: section
        for section in application.conops_sections.all()
    }
    return [
        by_key[definition.key]
        for definition in CONOPS_DEFINITIONS
        if definition.key in by_key
    ]


CONOPS_DEFINITIONS = (
    ConopsDefinition(
        "operational-overview",
        "1.0 Operational Overview",
        _operation_overview,
    ),
    ConopsDefinition(
        "operational-area-airspace",
        "2.0 Operational Area and Airspace",
        _controlled_area_airspace,
    ),
    ConopsDefinition(
        "airspace-atc-coordination",
        "3.0 Airspace Integration and ATC Coordination",
        _airspace_atc_coordination,
    ),
    ConopsDefinition(
        "see-and-avoid",
        "4.0 See-and-Avoid Methodology",
        _see_and_avoid,
    ),
    ConopsDefinition(
        "flight-envelope-limitations",
        "5.0 Flight Envelope and Operating Limitations",
        _flight_envelope_limitations,
    ),
    ConopsDefinition(
        "crew-resource-management",
        "6.0 Crew Resource Management",
        _crew_resource_management,
    ),
    ConopsDefinition(
        "aircraft-capabilities",
        "7.0 Aircraft Capabilities",
        _aircraft_capabilities,
    ),
    ConopsDefinition(
        "operational-risk-controls",
        "8.0 Operational Risk Controls",
        _operational_risk_controls,
    ),
    ConopsDefinition(
        "emergency-procedures",
        "9.0 Emergency Procedures",
        _emergency_procedures,
    ),
)



def get_or_create_application(
    approval: OperationApproval,
    user,
) -> ApprovalApplication:
    application, _ = ApprovalApplication.objects.get_or_create(
        approval=approval,
        defaults={
            "user": user,
            "status": "draft",
            "description": "",
            "locked_description": False,
            "ai_generation_model": "",
            "conops_source_updated_at": None,
            "ai_prompt_version": "",
            "ai_generation_error": "",
        },
    )

    if application.user_id != user.id:
        raise PermissionError(
            "The CONOPS application is owned by another user."
        )

    return application


def _sync_application_description(application):
    ordered_sections = application.conops_sections.order_by("section_key")
    application.description = "\n\n".join(
        f"{section.title}\n{section.content}".strip()
        for section in ordered_sections
    )
    application.save(update_fields=["description", "updated_at"])


@transaction.atomic
def generate_conops(
    approval: OperationApproval,
    user,
    *,
    regenerate_unlocked: bool = False,
) -> ApprovalApplication:
    """
    Create the initial CONOPS or refresh only unlocked sections.

    Locked sections and sections manually edited in the review screen are
    preserved.
    """
    application = get_or_create_application(approval, user)
    generated_at = timezone.now()

    for definition in CONOPS_DEFINITIONS:
        generated_content = definition.builder(approval).strip()
        section, created = ConopsSection.objects.get_or_create(
            application=application,
            section_key=definition.key,
            defaults={
                "user": user,
                "title": definition.title,
                "content": generated_content,
                "generated_at": generated_at,
                "is_complete": bool(generated_content),
            },
        )

        if not created:
            update_fields = []

            if section.title != definition.title:
                section.title = definition.title
                update_fields.append("title")

            if regenerate_unlocked and not section.locked:
                section.content = generated_content
                section.generated_at = generated_at
                section.is_complete = bool(generated_content)
                update_fields.extend(
                    ["content", "generated_at", "is_complete"]
                )

            if update_fields:
                update_fields.append("updated_at")
                section.save(update_fields=update_fields)

    approval.operation.generated_conops_at = generated_at
    approval.operation.save(update_fields=["generated_conops_at"])

    return application


@transaction.atomic
def save_conops_review(application, submitted_sections):
    """
    Save reviewed section text.

    Any section whose text changes is automatically locked so later
    regeneration cannot overwrite the user's revision.
    """
    for section in application.conops_sections.all():
        submitted = submitted_sections.get(section.pk)
        if submitted is None:
            continue

        new_content = _clean(submitted.get("content"))
        content_changed = new_content != section.content

        section.content = new_content
        section.locked = bool(
            submitted.get("locked")
            or content_changed
        )
        section.is_complete = bool(
            submitted.get("is_complete") and not content_changed
        )
        section.validated_at = (
            timezone.now()
            if section.is_complete
            else None
        )
        section.save(
            update_fields=[
                "content",
                "locked",
                "is_complete",
                "validated_at",
                "updated_at",
            ]
        )
