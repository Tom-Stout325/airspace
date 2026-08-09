from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import forms

from drones.models import Drone
from pilot.models import PilotProfile

from .models import (
    ApprovalType,
    CREWED_AIRCRAFT_CONFLICT_RESPONSE_NO_VO,
    CREWED_AIRCRAFT_CONFLICT_RESPONSE_VO,
    OperationAircraft,
    OperationApproval,
    OperationsPlanning,
)


class DateInput(forms.DateInput):
    input_type = "date"


class OperationsPlanningForm(forms.ModelForm):
    COORDINATE_QUANTIZER = Decimal("0.000001")

    # Nominatim and other mapping sources commonly return more than six
    # decimal places. The form accepts the higher-precision input and then
    # normalizes it to the six decimal places supported by the model.
    location_latitude = forms.DecimalField(
        required=False,
        max_digits=18,
        decimal_places=12,
        label="Operation Latitude",
    )
    location_longitude = forms.DecimalField(
        required=False,
        max_digits=18,
        decimal_places=12,
        label="Operation Longitude",
    )
    launch_latitude = forms.DecimalField(
        required=False,
        max_digits=18,
        decimal_places=12,
        label="Launch Latitude",
    )
    launch_longitude = forms.DecimalField(
        required=False,
        max_digits=18,
        decimal_places=12,
        label="Launch Longitude",
    )

    address_search = forms.CharField(
        required=False,
        label="Search for the Operation Address",
        help_text=(
            "Enter a venue, business, landmark, or street address, then select "
            "Search. Choosing a result fills the address and coordinates below."
        ),
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": (
                    "Example: Sonoma Raceway or 29355 Arnold Drive, Sonoma, CA"
                ),
                "autocomplete": "off",
                "inputmode": "search",
            }
        ),
    )

    timeframe = forms.MultipleChoiceField(
        choices=OperationsPlanning.TIMEFRAME_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    purpose_operations = forms.MultipleChoiceField(
        choices=OperationsPlanning.PURPOSE_OPERATIONS_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    ground_environment = forms.MultipleChoiceField(
        choices=OperationsPlanning.GROUND_ENVIRONMENT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    prepared_procedures = forms.MultipleChoiceField(
        choices=OperationsPlanning.PREPARED_PROCEDURES_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = OperationsPlanning
        exclude = [
            "user",
            "aircraft",
            "distance_to_airport_nm",
            "generated_conops_at",
            "aircraft_manual",
            "operation_area_geojson",
            "location_radius_ft",
            "minimum_planned_altitude_agl",
            "max_groundspeed_mph",
            "maximum_distance_from_pilot_ft",
            "maximum_distance_from_launch_ft",
            "safety_features_notes",
            "aircraft_failure_actions",
            "atc_facility_name",
            "atc_coordination_method",
            "atc_phone",
            "atc_frequency",
            "atc_checkin_procedure",
            "atc_deviation_triggers",
            "radio_discipline",
        ]

        labels = {
            "status": "Planning Status",
            "operation_title": "Operation Name",
            "operation_description": "Mission Description",
            "start_date": "Proposed Start Date",
            "end_date": "Proposed End Date",
            "frequency": "Operation Frequency",
            "local_time_zone": "Local Time Zone",
            "dronezone_radius": "DroneZone Requested Radius",
            "purpose_operations_details": "Mission Details",
            "aircraft_use": "Aircraft Deployment",
            "pilot_profile": "Remote Pilot in Command (RPIC)",
            "pilot_name_manual": "RPIC Name (Manual Entry)",
            "pilot_cert_manual": "FAA Remote Pilot Certificate Number",
            "pilot_flight_hours": "RPIC Flight Experience (Hours)",
            "venue_name": "Venue or Site Name",
            "street_address": "Operation Site Address",
            "location_city": "City",
            "location_state": "State",
            "zip_code": "ZIP Code",
            "location_latitude": "Operation Latitude",
            "location_longitude": "Operation Longitude",
            "launch_location": "Primary Launch Site",
            "launch_latitude": "Launch Latitude",
            "launch_longitude": "Launch Longitude",
            "recovery_location": "Landing Location",
            "airspace_class": "Airspace Classification",
            "nearest_airport": "Nearest Airport Identifier (Manual)",
            "nearest_airport_ref": "Nearest Airport",
            "operation_area_type": "Operational Area Geometry",
            "operation_area_description": "Operational Area Description",
            "operational_boundary_description": (
                "Operational Boundary Description"
            ),
            "corridor_length_ft": "Corridor Length (Feet)",
            "corridor_width_ft": "Corridor Width (Feet)",
            "operation_map": "Operating Area Map",
            "operation_map_notes": "Map Notes",
            "containment_method": "Primary Containment Method",
            "containment_notes": "Containment Procedures",
            "maximum_planned_altitude_agl": "Maximum Planned Altitude (AGL)",
            "planned_bvlos": "Operation Includes BVLOS Flight",
            "flight_duration": "Typical Flight Duration",
            "flights_per_day": "Estimated Flights per Day",
            "ground_environment_other": "Other Ground Environment Details",
            "estimated_crowd_size": "Estimated Maximum Crowd Size",
            "ground_risk_mitigation": "Ground Risk Controls",
            "air_risk_mitigation": "Airspace Risk Controls",
            "crewed_aircraft_conflict_response": (
                "Crewed Aircraft Conflict Response"
            ),
            "operations_over_people": (
                "Operations Over People / Open-Air Assemblies"
            ),
            "crowd_mitigation": (
                "Operations Over People / Crowd Mitigation"
            ),
            "additional_operational_information": (
                "Additional Operational Information / Controls"
            ),
            "uses_drone_detection": "Drone Detection System Used",
            "uses_flight_tracking": "Crewed Aircraft Traffic Awareness Used",
            "flight_tracking_service": "Crewed Aircraft Tracking Service",
            "has_visual_observer": "Visual Observer Used",
            "insurance_provider": "Insurance Provider",
            "insurance_coverage_limit": "Liability Coverage Limit",
            "lost_link_behavior": "Programmed Lost-Link Behavior",
            "rth_altitude_ft_agl": "Return-to-Home Altitude (AGL)",
            "lost_link_actions": "Lost-Link Procedures",
            "flyaway_actions": "Flyaway Procedures",
            "emergency_response_plan": "Emergency Response Procedures",
            "emergency_landing_areas": "Emergency Landing Areas",
            "injury_or_property_damage_actions": "Injury or Property Damage Response",
            "incident_reporting_procedure": "Incident Reporting Procedures",
            "termination_conditions": "Operation Suspension and Termination Criteria",
            "crew_communications_method": "Crew Communications Method",
            "communications_failure_actions": "Communications Failure Procedures",
            "uses_standard_part_107_weather_minimums": "Use Standard Part 107 Weather Minimums",
            "max_wind_mph": "Maximum Operating Wind (MPH)",
            "min_visibility_sm": "Minimum Flight Visibility (Statute Miles)",
            "minimum_cloud_ceiling_ft": "Operator Minimum Cloud Ceiling (Feet)",
            "minimum_distance_below_clouds_ft": "Minimum Distance Below Clouds (Feet)",
            "minimum_horizontal_cloud_clearance_ft": "Minimum Horizontal Distance from Clouds (Feet)",
            "weather_source": "Weather Information Sources",
            "weather_go_nogo": "Weather Go / No-Go Criteria",
            "night_lighting_description": "Night Lighting Plan",
            "crew_count": "Total Crew Members",
            "crew_briefing_procedure": "Crew Briefing Notes",
        }

        help_texts = {
            "status": "Use Draft while information is still being collected. Advance the status only when the plan is ready for review or use.",
            "operation_title": "Use a short, recognizable name such as 'NHRA Finals Broadcast Coverage'.",
            "operation_description": "Summarize what the crew will do, why the flights are needed, and the general operating concept.",
            "start_date": "Enter the first proposed day of flight operations.",
            "end_date": "Leave blank for a one-day operation. Otherwise enter the final proposed operating date.",
            "frequency": "Describe how often flights are expected during the selected date range.",
            "local_time_zone": (
                "Select the same standard-time-zone option that will be "
                "entered in FAA DroneZone. AirSpace preserves the FAA label "
                "rather than converting it to daylight-saving terminology."
            ),
            "dronezone_radius": (
                "Select the radius that will be entered in the FAA DroneZone "
                "airspace-authorization application. This does not replace "
                "the detailed operating-area map or containment description."
            ),
            "purpose_operations_details": "Add details not clear from the selected mission type, including deliverables, client needs, or event coverage.",
            "aircraft_use": "Indicate whether one aircraft, multiple aircraft used in sequence, or multiple aircraft used simultaneously are planned.",
            "pilot_profile": "Select the saved pilot profile for the person who will serve as Remote Pilot in Command.",
            "pilot_name_manual": "Use only when the RPIC does not yet have a saved pilot profile.",
            "pilot_cert_manual": "Use only when the certificate number is not available from the selected pilot profile.",
            "pilot_flight_hours": "Enter the RPIC's approximate total UAS flight experience.",
            "location_latitude": "Enter the approximate center of the operation in decimal degrees.",
            "location_longitude": "Enter the approximate center of the operation in decimal degrees.",
            "launch_location": "Describe the primary takeoff point in terms the crew can identify on site.",
            "launch_latitude": "Optional decimal-degree coordinate for the launch point.",
            "launch_longitude": "Optional decimal-degree coordinate for the launch point.",
            "recovery_location": "Describe the planned normal landing location.",
            "airspace_class": "Select the class of airspace containing the operation. Leave blank if it has not yet been confirmed.",
            "nearest_airport_ref": "Select the nearest airport from the imported FAA airport data.",
            "nearest_airport": "Use only when the airport is not available in the dropdown.",
            "operation_area_type": "Choose the shape that best describes the planned operating area. The exact boundary will later be defined on a map.",
            "operation_area_description": "Describe the lateral boundaries using roads, buildings, property lines, venue features, or other recognizable references.",
            "operational_boundary_description": (
                "Describe recognizable boundaries of the operating area and "
                "any areas the aircraft must not enter. Examples include "
                "roads, fences, buildings, property lines, runways, spectator "
                "areas, or boundaries shown on the operation map."
            ),
            "corridor_length_ft": (
                "Required when Operational Area Geometry is Corridor."
            ),
            "corridor_width_ft": (
                "Required when Operational Area Geometry is Corridor."
            ),
            "operation_map": (
                "Upload the annotated map that will be included with the standalone CONOPS. Use the exact operating location rather than relying only on a facility mailing address."
            ),
            "operation_map_notes": (
                "Optional: identify what the colors, lines, labels, or shaded areas on the uploaded map represent."
            ),
            "containment_method": "Select the primary method used to keep the aircraft inside the defined operational area.",
            "containment_notes": "Explain how the boundary will be established, monitored, and enforced during the operation.",
            "maximum_planned_altitude_agl": "Enter the highest altitude planned above the surface directly beneath the aircraft.",
            "planned_bvlos": "Select this only when any portion of the flight is expected to occur beyond the RPIC's visual line of sight.",
            "flight_duration": "Enter a typical duration such as '12 minutes' or '20-25 minutes'.",
            "flights_per_day": "Estimate the maximum number of separate flights expected during a normal operating day.",
            "ground_environment_other": "Describe relevant ground conditions not represented by the available choices.",
            "estimated_crowd_size": "Estimate the greatest number of people expected within or immediately adjacent to the operating area.",
            "ground_risk_mitigation": "Describe how people, vehicles, and property will be protected. Examples include access control, barriers, spotters, restricted zones, scheduling, and emergency landing areas.",
            "air_risk_mitigation": "Describe how the crew will identify and avoid crewed aircraft or other airspace conflicts. Examples include visual observers, ADS-B awareness, altitude limits, ATC coordination, and immediate landing procedures.",
            "crewed_aircraft_conflict_response": (
                "Standard AirSpace response for a potential conflict with a "
                "crewed aircraft. Review and edit if your operation requires "
                "a different procedure."
            ),
            "operations_over_people": (
                "Select the planning position that accurately describes the "
                "operation. AirSpace will not infer Part 107 eligibility from "
                "crowd size or access controls."
            ),
            "crowd_mitigation": (
                "Describe how the RPIC will prevent or mitigate flight over "
                "non-participants, spectators, crowds, or open-air assemblies. "
                "Include barriers, controlled access, flight-path restrictions, "
                "designated operating areas, or other applicable controls."
            ),
            "additional_operational_information": (
                "Enter any additional information relevant to the FAA's "
                "evaluation that is not captured elsewhere, such as prior "
                "operating experience at the location, facility-specific "
                "procedures, previous FAA coordination, unusual hazards, or "
                "additional risk controls."
            ),
            "uses_drone_detection": "Select when a dedicated system will detect other unmanned aircraft near the operation.",
            "uses_flight_tracking": "Select when the RPIC or visual observer will use a system or application to monitor nearby crewed-aircraft traffic. This supplements visual scanning and ATC coordination; it does not replace see-and-avoid responsibilities.",
            "flight_tracking_service": "Enter the actual service or application used for supplemental crewed-aircraft awareness. Leave blank when no named service is planned.",
            "has_visual_observer": "Select when one or more visual observers will assist the RPIC.",
            "insurance_coverage_limit": "Enter the liability limit, such as '$1,000,000' or '$5,000,000'.",
            "lost_link_behavior": "Select the aircraft's programmed response after control-link loss.",
            "rth_altitude_ft_agl": "Enter the programmed Return-to-Home altitude above ground level.",
            "lost_link_actions": "Describe the crew's steps after link loss, including monitoring, area control, notifications, and when the operation is terminated.",
            "flyaway_actions": "Describe how the crew will track the aircraft, record its last known position, notify affected parties, and protect people below.",
            "emergency_response_plan": "Describe who stops the operation, secures the area, contacts emergency services or ATC, preserves flight records, and completes required reporting.",
            "emergency_landing_areas": "Identify preselected areas where the aircraft can land safely without creating additional risk.",
            "injury_or_property_damage_actions": "Describe immediate medical, scene-control, notification, documentation, and reporting actions.",
            "incident_reporting_procedure": "Explain who documents and reports an incident, which records are preserved, and what internal or FAA notifications may apply.",
            "termination_conditions": "Identify objective conditions requiring the operation to pause or end, such as crewed aircraft, loss of communications, worsening weather, unexpected people or vehicles, equipment warnings, or loss of containment.",
            "crew_communications_method": "Describe the primary method used by the RPIC, visual observers, and support crew to communicate.",
            "communications_failure_actions": "Describe what the crew will do if radios, headsets, phones, or other required communications become unavailable.",
            "uses_standard_part_107_weather_minimums": "When selected, AirSpace uses 3 statute miles of flight visibility, 500 feet below clouds, and 2,000 feet horizontally from clouds. Clear the checkbox to enter more conservative or approval-specific values.",
            "max_wind_mph": "Enter the operation's wind limit. Use the lower of the aircraft limit and the crew's approved operational limit.",
            "min_visibility_sm": "Part 107 requires at least 3 statute miles of flight visibility unless specifically waived.",
            "minimum_cloud_ceiling_ft": "Enter the minimum cloud ceiling the crew will accept for this operation based on altitude, terrain, and risk.",
            "minimum_distance_below_clouds_ft": "Part 107 requires the aircraft to remain at least 500 feet below clouds unless specifically waived.",
            "minimum_horizontal_cloud_clearance_ft": "Part 107 requires the aircraft to remain at least 2,000 feet horizontally from clouds unless specifically waived.",
            "weather_source": "List the sources used to obtain current and forecast conditions, such as METARs, TAFs, NWS, or an on-site weather station.",
            "weather_go_nogo": "Describe the measurable weather conditions that permit flight and the conditions that require delay, suspension, or cancellation.",
            "night_lighting_description": "Describe aircraft anti-collision lighting, ground lighting, crew dark adaptation, and any additional night procedures.",
            "crew_count": "Include the RPIC, visual observers, payload operators, and other operational crew.",
            "crew_briefing_procedure": "Record operation-specific briefing topics or deviations from the standard crew briefing. Leave blank when the standard briefing fully applies.",
        }

        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "operation_description": forms.Textarea(attrs={"rows": 4}),
            "purpose_operations_details": forms.Textarea(attrs={"rows": 3}),
            "operation_area_description": forms.Textarea(attrs={"rows": 3}),
            "operational_boundary_description": forms.Textarea(attrs={"rows": 3}),
            "containment_notes": forms.Textarea(attrs={"rows": 3}),
            "ground_environment_other": forms.Textarea(attrs={"rows": 3}),
            "ground_risk_mitigation": forms.Textarea(attrs={"rows": 4}),
            "air_risk_mitigation": forms.Textarea(attrs={"rows": 4}),
            "crewed_aircraft_conflict_response": forms.Textarea(attrs={"rows": 5}),
            "crowd_mitigation": forms.Textarea(attrs={"rows": 4}),
            "additional_operational_information": forms.Textarea(attrs={"rows": 4}),
            "lost_link_actions": forms.Textarea(attrs={"rows": 4}),
            "flyaway_actions": forms.Textarea(attrs={"rows": 4}),
            "emergency_response_plan": forms.Textarea(attrs={"rows": 5}),
            "emergency_landing_areas": forms.Textarea(attrs={"rows": 3}),
            "injury_or_property_damage_actions": forms.Textarea(attrs={"rows": 4}),
            "incident_reporting_procedure": forms.Textarea(attrs={"rows": 4}),
            "termination_conditions": forms.Textarea(attrs={"rows": 4}),
            "communications_failure_actions": forms.Textarea(attrs={"rows": 4}),
            "weather_go_nogo": forms.Textarea(attrs={"rows": 4}),
            "night_lighting_description": forms.Textarea(attrs={"rows": 4}),
            "crew_briefing_procedure": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        pilot_profiles = (
            PilotProfile.objects.filter(user=user)
            if user
            else PilotProfile.objects.none()
        )
        self.fields["pilot_profile"].queryset = pilot_profiles
        self.pilot_profile_data = {
            str(profile.pk): {
                "faa_certificate_number": profile.faa_certificate_number or "",
            }
            for profile in pilot_profiles
        }

        if not self.is_bound and self.instance.pilot_profile_id:
            selected_pilot = pilot_profiles.filter(
                pk=self.instance.pilot_profile_id,
            ).first()
            if selected_pilot is not None:
                self.initial["pilot_cert_manual"] = (
                    selected_pilot.faa_certificate_number or ""
                ).strip()

        self.fields["nearest_airport_ref"].queryset = (
            self.fields["nearest_airport_ref"]
            .queryset.filter(active=True)
            .order_by("name")
        )

        self.fields["nearest_airport"].widget.attrs.update(
            {
                "readonly": True,
                "aria-readonly": "true",
            }
        )
        self.fields["crewed_aircraft_conflict_response"].widget.attrs.update(
            {
                "data-vo-standard": CREWED_AIRCRAFT_CONFLICT_RESPONSE_VO,
                "data-no-vo-standard": (
                    CREWED_AIRCRAFT_CONFLICT_RESPONSE_NO_VO
                ),
            }
        )

        checkbox_groups = {
            "timeframe",
            "purpose_operations",
            "ground_environment",
            "prepared_procedures",
        }

        for name, field in self.fields.items():
            widget = field.widget

            if name in checkbox_groups:
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")

            if isinstance(widget, (forms.TextInput, forms.NumberInput, forms.Select)):
                widget.attrs.setdefault("autocomplete", "off")

    def clean(self):
        cleaned = super().clean()
        pilot_profile = cleaned.get("pilot_profile")
        if pilot_profile:
            cleaned["pilot_cert_manual"] = (
                pilot_profile.faa_certificate_number or ""
            ).strip()

        if cleaned.get("uses_standard_part_107_weather_minimums"):
            cleaned["min_visibility_sm"] = Decimal("3.0")
            cleaned["minimum_distance_below_clouds_ft"] = 500
            cleaned["minimum_horizontal_cloud_clearance_ft"] = 2000

        conflict_response = (
            cleaned.get("crewed_aircraft_conflict_response") or ""
        ).strip()
        has_visual_observer = bool(cleaned.get("has_visual_observer"))
        if has_visual_observer and (
            not conflict_response
            or conflict_response == CREWED_AIRCRAFT_CONFLICT_RESPONSE_NO_VO
        ):
            cleaned["crewed_aircraft_conflict_response"] = (
                CREWED_AIRCRAFT_CONFLICT_RESPONSE_VO
            )
        elif not has_visual_observer and (
            not conflict_response
            or conflict_response == CREWED_AIRCRAFT_CONFLICT_RESPONSE_VO
        ):
            cleaned["crewed_aircraft_conflict_response"] = (
                CREWED_AIRCRAFT_CONFLICT_RESPONSE_NO_VO
            )
        elif (
            not has_visual_observer
            and "visual observer" in conflict_response.casefold()
        ):
            self.add_error(
                "crewed_aircraft_conflict_response",
                "Remove or revise the Visual Observer procedure when no "
                "Visual Observer is selected.",
            )
        return cleaned

    def _clean_coordinate(self, field_name):
        value = self.cleaned_data.get(field_name)

        if value in (None, ""):
            return None

        try:
            return Decimal(str(value)).quantize(
                self.COORDINATE_QUANTIZER,
                rounding=ROUND_HALF_UP,
            )
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise forms.ValidationError(
                "Enter a valid coordinate."
            ) from exc

    def clean_location_latitude(self):
        return self._clean_coordinate("location_latitude")

    def clean_location_longitude(self):
        return self._clean_coordinate("location_longitude")

    def clean_launch_latitude(self):
        return self._clean_coordinate("launch_latitude")

    def clean_launch_longitude(self):
        return self._clean_coordinate("launch_longitude")

    def save(self, commit=True):
        instance = super().save(commit=False)

        if self.user and not instance.user_id:
            instance.user = self.user

        if commit:
            instance.save()

        return instance


class OperationAircraftForm(forms.ModelForm):
    class Meta:
        model = OperationAircraft
        fields = [
            "drone",
            "planned_payload",
            "registration_verified",
            "remote_id_verified",
            "preflight_airworthiness_verified",
            "current_firmware_installed",
            "operation_specific_safety_notes",
        ]

        labels = {
            "drone": "Aircraft",
            "planned_payload": "Payload or Attached Equipment",
            "registration_verified": "FAA Registration Verified",
            "remote_id_verified": "Remote ID Verified",
            "preflight_airworthiness_verified": (
                "Aircraft Airworthiness Verified"
            ),
            "current_firmware_installed": "Current Firmware Installed",
            "operation_specific_safety_notes": (
                "Aircraft-Specific Safety Notes"
            ),
        }

        help_texts = {
            "drone": (
                "Select an active aircraft from your inventory. "
                "You may assign multiple aircraft to the same operation, "
                "but each aircraft can only be assigned once."
            ),
            "planned_payload": (
                "List any camera, sensor, lighting system, propeller guards, "
                "parachute, Remote ID module, or other equipment attached for "
                "this operation. Leave blank for the standard configuration."
            ),
            "registration_verified": (
                "Confirm that the FAA registration is current, displayed on "
                "the aircraft, and matches the saved aircraft record."
            ),
            "remote_id_verified": (
                "Confirm that Remote ID information has been checked and the "
                "aircraft will broadcast as required for the operation."
            ),
            "preflight_airworthiness_verified": (
                "Confirm that the aircraft, batteries, propellers, motors, "
                "sensors, controls, and attached equipment are safe to operate."
            ),
            "current_firmware_installed": (
                "Confirm that the aircraft and controller use the current "
                "manufacturer-approved firmware, unless a documented reason "
                "requires another approved version."
            ),
            "operation_specific_safety_notes": (
                "Enter only safety information unique to this aircraft's use "
                "during this operation. Leave blank when the saved drone "
                "safety profile fully applies."
            ),
        }

        widgets = {
            "operation_specific_safety_notes": forms.Textarea(
                attrs={"rows": 4}
            ),
        }

    def __init__(
        self,
        *args,
        user=None,
        operation=None,
        **kwargs,
    ):
        self.operation = operation
        super().__init__(*args, **kwargs)

        queryset = (
            Drone.objects.filter(
                user=user,
                status=Drone.Status.ACTIVE,
            )
            .order_by(
                "manufacturer",
                "model",
                "nickname",
            )
            if user
            else Drone.objects.none()
        )

        # When adding a new assignment, don't show drones already
        # assigned to this operation.
        if operation is not None:
            assigned_drone_ids = (
                operation.aircraft_assignments
                .values_list("drone_id", flat=True)
            )

            if self.instance.pk:
                assigned_drone_ids = assigned_drone_ids.exclude(
                    pk=self.instance.pk
                )

            queryset = queryset.exclude(
                pk__in=assigned_drone_ids
            )

            # When editing, the currently selected aircraft must
            # remain available in the dropdown.
            if self.instance.pk and self.instance.drone_id:
                current = Drone.objects.filter(
                    pk=self.instance.drone_id,
                    user=user,
                )
                queryset = (
                    queryset | current
                ).distinct().order_by(
                    "manufacturer",
                    "model",
                    "nickname",
                )

        self.fields["drone"].queryset = queryset

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault(
                    "class",
                    "form-check-input",
                )
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault(
                    "class",
                    "form-select",
                )
            else:
                field.widget.attrs.setdefault(
                    "class",
                    "form-control",
                )

    def clean_drone(self):
        drone = self.cleaned_data["drone"]

        if self.operation is None:
            return drone

        duplicate = (
            self.operation.aircraft_assignments
            .filter(drone=drone)
        )

        if self.instance.pk:
            duplicate = duplicate.exclude(
                pk=self.instance.pk
            )

        if duplicate.exists():
            raise forms.ValidationError(
                "This aircraft is already assigned to the operation."
            )

        return drone


class OperationApprovalForm(forms.ModelForm):
    """
    Planning-only form for identifying the required FAA approval and
    developing the safety case.
    """

    RISK_MITIGATION_CHOICES = [
        ("restricted_access", "Restricted access to the operating area"),
        ("barriers", "Physical barriers or clearly marked boundaries"),
        ("spotters", "Ground spotters or safety personnel"),
        ("security", "Security or event staff controlling access"),
        ("temporary_closure", "Temporary road, lane, or area closure"),
        ("public_notification", "Public or participant notification"),
        ("visual_observer", "Visual observer monitoring the airspace"),
        ("crewed_traffic_awareness", "Crewed-aircraft traffic awareness system"),
        ("atc_coordination", "ATC or airport coordination"),
        ("immediate_landing", "Immediate landing or flight suspension trigger"),
        ("reduced_altitude", "Reduced operating altitude"),
        ("defined_boundary", "Defined and monitored operating boundary"),
        ("geofencing", "Geofencing or programmed containment"),
        ("emergency_landing", "Preselected emergency landing areas"),
    ]
    EQUIVALENT_SAFETY_CHOICES = [
        ("additional_observers", "Additional visual observers"),
        ("reduced_area", "Reduced or tightly controlled operating area"),
        ("reduced_altitude", "Reduced operating altitude"),
        ("reduced_speed", "Reduced aircraft speed"),
        ("smaller_aircraft", "Smaller or lower-energy aircraft"),
        ("remote_location", "Remote or access-controlled location"),
        ("additional_training", "Additional pilot or crew training"),
        ("enhanced_emergency", "Enhanced emergency procedures"),
        ("enhanced_communications", "Additional crew or ATC communications"),
        ("redundant_systems", "Redundant aircraft or command-and-control systems"),
        ("traffic_monitoring", "Dedicated crewed-aircraft traffic monitoring"),
        ("operational_limits", "More conservative weather or operating limits"),
    ]

    risk_mitigation_options = forms.MultipleChoiceField(
        choices=RISK_MITIGATION_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Risk Mitigation Builder",
        help_text="Select the controls that apply, then generate and review the statement.",
    )
    equivalent_safety_options = forms.MultipleChoiceField(
        choices=EQUIVALENT_SAFETY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Equivalent Level of Safety Builder",
        help_text="Select the controls that compensate for the requested relief, then generate and review the statement.",
    )

    class Meta:
        model = OperationApproval
        fields = [
            "approval_type",
            "requested_operation",
            "safety_justification",
            "risk_mitigations",
            "equivalent_level_of_safety",
        ]
        labels = {
            "approval_type": "FAA Waiver / Approval Type",
            "requested_operation": "Requested Operation",
            "safety_justification": "Safety Justification",
            "risk_mitigations": "Risk Mitigations",
            "equivalent_level_of_safety": (
                "Equivalent Level of Safety"
            ),
        }
        help_texts = {
            "approval_type": (
                "Select the FAA waiver or authorization required for this "
                "operation. The associated regulation is supplied by the "
                "waiver-type database."
            ),
            "requested_operation": (
                "Describe exactly what you are asking the FAA to permit. "
                "Include the aircraft, location, operating condition, and "
                "the specific activity requiring relief or authorization."
            ),
            "safety_justification": (
                "Explain why the proposed operation can be conducted safely "
                "despite the regulation or restriction involved."
            ),
            "risk_mitigations": (
                "Describe the personnel, procedures, equipment, boundaries, "
                "communications, and other controls that reduce the identified "
                "risks."
            ),
            "equivalent_level_of_safety": (
                "Explain how the combined mitigations provide safety equal "
                "to or greater than operating in full compliance with the "
                "underlying regulation."
            ),
        }
        widgets = {
            "requested_operation": forms.Textarea(attrs={"rows": 4}),
            "safety_justification": forms.Textarea(attrs={"rows": 5}),
            "risk_mitigations": forms.Textarea(attrs={"rows": 6}),
            "equivalent_level_of_safety": forms.Textarea(
                attrs={"rows": 5}
            ),
        }

    def __init__(self, *args, operation=None, **kwargs):
        self.operation = operation
        super().__init__(*args, **kwargs)

        approval_types = ApprovalType.objects.filter(active=True)

        if operation is not None:
            existing_type_ids = operation.approvals.values_list(
                "approval_type_id",
                flat=True,
            )

            if self.instance.pk:
                existing_type_ids = existing_type_ids.exclude(
                    pk=self.instance.pk,
                )

            approval_types = approval_types.exclude(
                pk__in=existing_type_ids,
            )

        self.fields["approval_type"].queryset = approval_types.order_by(
            "category",
            "display_order",
            "name",
        )

        if operation is not None and not self.is_bound and not (
            self.instance.safety_justification or ""
        ).strip():
            statement = self.build_aircraft_safety_statement(operation)
            if statement:
                self.initial["safety_justification"] = statement

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    @staticmethod
    def build_aircraft_safety_statement(operation):
        features = []
        seen = set()
        for assignment in operation.aircraft_assignments.select_related("drone"):
            raw = (
                assignment.safety_features_snapshot
                or assignment.drone.safety_features
                or ""
            )
            for line in raw.replace("•", "\n").splitlines():
                feature = line.strip(" -\t\r\n")
                if feature and feature.casefold() not in seen:
                    seen.add(feature.casefold())
                    features.append(feature)

        if not features:
            return ""
        if len(features) == 1:
            feature_text = features[0]
        elif len(features) == 2:
            feature_text = " and ".join(features)
        else:
            feature_text = ", ".join(features[:-1]) + ", and " + features[-1]

        return (
            "The operation will be conducted using aircraft equipped with "
            f"{feature_text}. These systems will supplement the RPIC's "
            "procedures, visual scanning, crew coordination, and established "
            "operating limitations."
        )

    def clean(self):
        cleaned = super().clean()
        approval_type = cleaned.get("approval_type")

        if self.operation is not None and approval_type is not None:
            duplicate = self.operation.approvals.filter(
                approval_type=approval_type,
            )
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)

            if duplicate.exists():
                self.add_error(
                    "approval_type",
                    (
                        "This waiver or approval has already been added to "
                        "the operation. Open the existing record to edit it."
                    ),
                )

        if (
            approval_type
            and approval_type.code == "controlled-airspace"
        ):
            cleaned["equivalent_level_of_safety"] = ""

        return cleaned


class OperationApprovalTrackingForm(forms.ModelForm):
    """
    Submission and issued-approval record. This form is intentionally
    separate from waiver planning.
    """

    class Meta:
        model = OperationApproval
        fields = [
            "status",
            "faa_tracking_number",
            "approval_number",
            "approval_document",
            "submitted_at",
            "approved_at",
            "effective_date",
            "expiration_date",
            "special_provisions",
            "reviewer_notes",
        ]
        labels = {
            "status": "Approval Status",
            "faa_tracking_number": "FAA Tracking Number",
            "approval_number": "FAA Approval Number",
            "approval_document": "Issued Approval Document",
            "submitted_at": "Submitted to FAA",
            "approved_at": "Approved by FAA",
            "effective_date": "Effective Date",
            "expiration_date": "Expiration Date",
            "special_provisions": (
                "FAA Special Provisions / Conditions"
            ),
            "reviewer_notes": "FAA Correspondence and Reviewer Notes",
        }
        help_texts = {
            "status": (
                "Update this as the request moves from planning through "
                "submission, FAA review, approval, denial, or expiration."
            ),
            "faa_tracking_number": (
                "Enter the tracking or reference number issued after the "
                "request is submitted."
            ),
            "approval_number": (
                "Enter the waiver or authorization number shown on the "
                "issued approval."
            ),
            "approval_document": (
                "Upload the issued FAA approval, waiver, or authorization."
            ),
            "submitted_at": (
                "Record when the request was submitted to the FAA."
            ),
            "approved_at": (
                "Record when the FAA issued its decision."
            ),
            "effective_date": (
                "Enter the first date on which the approval may be used."
            ),
            "expiration_date": (
                "Enter the final date on which the approval remains valid."
            ),
            "special_provisions": (
                "Copy or summarize the operating conditions and limitations "
                "included in the issued approval."
            ),
            "reviewer_notes": (
                "Record requests for additional information, FAA feedback, "
                "correspondence, or internal follow-up notes."
            ),
        }
        widgets = {
            "submitted_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
            "approved_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
            "effective_date": DateInput(),
            "expiration_date": DateInput(),
            "special_provisions": forms.Textarea(attrs={"rows": 5}),
            "reviewer_notes": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")
