from __future__ import annotations

from decimal import Decimal
from math import atan2, cos, radians, sin, sqrt

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models


class Airport(models.Model):
    faa_identifier = models.CharField(
        max_length=10,
        unique=True,
        null=True,
        blank=True,
        help_text="FAA location identifier from APT_BASE.ARPT_ID.",
    )
    icao = models.CharField(
        max_length=4,
        unique=True,
        null=True,
        blank=True,
        help_text="ICAO identifier when assigned.",
    )
    name = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=10, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["icao"]

    def __str__(self):
        identifier = self.faa_identifier or self.icao or "No identifier"
        if self.icao and self.faa_identifier and self.icao != self.faa_identifier:
            identifier = f"{self.faa_identifier} / {self.icao}"
        location = ", ".join(part for part in [self.city, self.state] if part)
        suffix = f" — {location}" if location else ""
        return f"{identifier} — {self.name}{suffix}"


class OperationsPlanning(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PLANNING = "planning", "Planning"
        READY = "ready", "Ready for Review"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        ARCHIVED = "archived", "Archived"

    TIMEFRAME_CHOICES = [
        ("sunrise_noon", "Sunrise to Noon"),
        ("noon_4pm", "Noon to 4 PM"),
        ("4pm_sunset", "4 PM to Sunset"),
        ("night", "Night"),
    ]
    FREQUENCY_CHOICES = [
        ("once", "One-time operation"), ("daily", "Daily"),
        ("weekly", "Weekly"), ("biweekly", "Bi-weekly"),
        ("monthly", "Monthly"), ("variable", "Variable / as needed"),
    ]
    AIRSPACE_CLASS_CHOICES = [
        ("B", "Class B"), ("C", "Class C"), ("D", "Class D"),
        ("E", "Class E"), ("G", "Class G"), ("U", "Not yet determined"),
    ]
    PURPOSE_OPERATIONS_CHOICES = [
        ("event_filming", "Event filming / broadcast"),
        ("pro_photography", "Professional aerial photography"),
        ("mapping_survey", "Mapping / survey"),
        ("infrastructure_inspection", "Infrastructure inspection"),
        ("public_safety", "Public safety / incident support"),
        ("training_proficiency", "Training / proficiency flights"),
        ("real_estate", "Real estate photography"),
        ("agriculture", "Agricultural operations"),
        ("research", "Research / testing"),
        ("delivery", "Package or payload delivery"),
        ("other", "Other"),
    ]
    AIRCRAFT_USE_CHOICES = [
        ("single", "Single aircraft"),
        ("multi_sequential", "Multiple aircraft used sequentially"),
        ("multi_simultaneous", "Multiple aircraft operated simultaneously"),
    ]
    GROUND_ENVIRONMENT_CHOICES = [
        ("residential", "Residential property / housing"),
        ("commercial", "Commercial buildings / business areas"),
        ("industrial", "Industrial or construction sites"),
        ("agricultural", "Agricultural land / open fields"),
        ("forested", "Forested or rural terrain"), ("water", "Water features"),
        ("roadways", "Roadways / parking areas"),
        ("pedestrian", "Pedestrian walkways / public access areas"),
        ("recreational", "Recreational areas"),
        ("infrastructure", "Critical infrastructure"),
        ("unpopulated", "Unpopulated or remote terrain"),
        ("crowd_sparse", "Sparse people present"),
        ("crowd_moderate", "Moderate public presence"),
        ("crowd_dense", "Dense gathering or event crowd"),
    ]
    PREPARED_PROCEDURES_CHOICES = [
        ("preflight", "Pre-flight checklist"), ("postflight", "Post-flight checklist"),
        ("lost_link", "Lost-link procedure"), ("flyaway", "Flyaway procedure"),
        ("emergency_lz", "Emergency landing zones identified"),
        ("crew_briefing", "Crew briefing procedure"),
        ("weather", "Weather go/no-go procedure"),
        ("incident_response", "Incident response procedure"),
        ("atc_coordination", "ATC coordination procedure"),
    ]
    OPERATION_AREA_CHOICES = [
        ("radius", "Radius"), ("corridor", "Corridor"),
        ("polygon", "Polygon"), ("site", "Defined site"),
        ("route", "Route"), ("multiple_sites", "Multiple sites"),
    ]
    CONTAINMENT_CHOICES = [
        ("geofence", "Geofence"), ("visual_markers", "Visual markers"),
        ("map_overlays", "Map overlays"), ("physical_barriers", "Physical barriers"),
        ("combination", "Combination"), ("other", "Other"),
    ]
    LOST_LINK_CHOICES = [
        ("rth", "Return to Home"), ("hover", "Hover"),
        ("land", "Land immediately"), ("route_continue", "Continue programmed route"),
        ("custom", "Custom procedure"),
    ]
    ATC_METHOD_CHOICES = [
        ("phone", "Phone"), ("radio", "Radio"), ("both", "Phone and radio"),
        ("digital", "Digital coordination"), ("other", "Other"),
    ]
    RADIO_DISCIPLINE_CHOICES = [
        ("sterile", "Sterile communications"),
        ("standard", "Standard communications"), ("other", "Other"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="operation_plans")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    operation_title = models.CharField(max_length=255)
    operation_description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    timeframe = ArrayField(models.CharField(max_length=20, choices=TIMEFRAME_CHOICES), blank=True, default=list)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, blank=True)
    local_time_zone = models.CharField(max_length=64, blank=True)
    purpose_operations = ArrayField(models.CharField(max_length=50, choices=PURPOSE_OPERATIONS_CHOICES), blank=True, default=list)
    purpose_operations_details = models.TextField(blank=True)

    aircraft = models.ManyToManyField("drones.Drone", through="OperationAircraft", related_name="operation_plans", blank=True)
    aircraft_use = models.CharField(max_length=30, choices=AIRCRAFT_USE_CHOICES, blank=True)
    aircraft_manual = models.CharField(max_length=255, blank=True)

    pilot_profile = models.ForeignKey("pilot.PilotProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="operation_plans")
    pilot_name_manual = models.CharField(max_length=255, blank=True)
    pilot_cert_manual = models.CharField(max_length=255, blank=True)
    pilot_flight_hours = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)

    venue_name = models.CharField(max_length=255, blank=True)
    street_address = models.CharField(max_length=255, blank=True)
    location_city = models.CharField(max_length=100, blank=True)
    location_state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    location_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    launch_location = models.CharField(max_length=255, blank=True)
    launch_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    launch_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    recovery_location = models.CharField(max_length=255, blank=True)
    airspace_class = models.CharField(max_length=1, choices=AIRSPACE_CLASS_CHOICES, blank=True)
    nearest_airport = models.CharField(max_length=255, blank=True)
    nearest_airport_ref = models.ForeignKey("airspace.Airport", null=True, blank=True, on_delete=models.SET_NULL, related_name="operation_plans")
    distance_to_airport_nm = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

    operation_area_type = models.CharField(max_length=30, choices=OPERATION_AREA_CHOICES, default="radius")
    operation_area_description = models.TextField(blank=True)
    operation_area_geojson = models.JSONField(null=True, blank=True)
    location_radius_ft = models.PositiveIntegerField(null=True, blank=True)
    corridor_length_ft = models.PositiveIntegerField(null=True, blank=True)
    corridor_width_ft = models.PositiveIntegerField(null=True, blank=True)
    containment_method = models.CharField(max_length=30, choices=CONTAINMENT_CHOICES, blank=True)
    containment_notes = models.TextField(blank=True)

    minimum_planned_altitude_agl = models.PositiveIntegerField(null=True, blank=True)
    maximum_planned_altitude_agl = models.PositiveIntegerField(null=True, blank=True)
    max_groundspeed_mph = models.PositiveIntegerField(null=True, blank=True)
    maximum_distance_from_pilot_ft = models.PositiveIntegerField(null=True, blank=True)
    maximum_distance_from_launch_ft = models.PositiveIntegerField(null=True, blank=True)
    planned_bvlos = models.BooleanField(default=False)
    flight_duration = models.CharField(max_length=50, blank=True)
    flights_per_day = models.PositiveIntegerField(null=True, blank=True)

    ground_environment = ArrayField(models.CharField(max_length=50, choices=GROUND_ENVIRONMENT_CHOICES), blank=True, default=list)
    ground_environment_other = models.TextField(blank=True)
    estimated_crowd_size = models.CharField(max_length=50, blank=True)
    ground_risk_mitigation = models.TextField(blank=True)
    air_risk_mitigation = models.TextField(blank=True)

    uses_drone_detection = models.BooleanField(default=False)
    uses_flight_tracking = models.BooleanField(default=False)
    has_visual_observer = models.BooleanField(default=False)
    safety_features_notes = models.TextField(blank=True)
    insurance_provider = models.CharField(max_length=255, blank=True)
    insurance_coverage_limit = models.CharField(max_length=100, blank=True)

    lost_link_behavior = models.CharField(max_length=30, choices=LOST_LINK_CHOICES, blank=True)
    rth_altitude_ft_agl = models.PositiveIntegerField(null=True, blank=True)
    lost_link_actions = models.TextField(blank=True)
    flyaway_actions = models.TextField(blank=True)
    emergency_response_plan = models.TextField(blank=True)
    emergency_landing_areas = models.TextField(blank=True)
    aircraft_failure_actions = models.TextField(blank=True)
    injury_or_property_damage_actions = models.TextField(blank=True)
    incident_reporting_procedure = models.TextField(blank=True)
    termination_conditions = models.TextField(blank=True)

    atc_facility_name = models.CharField(max_length=255, blank=True)
    atc_coordination_method = models.CharField(max_length=20, choices=ATC_METHOD_CHOICES, blank=True)
    atc_phone = models.CharField(max_length=50, blank=True)
    atc_frequency = models.CharField(max_length=50, blank=True)
    atc_checkin_procedure = models.TextField(blank=True)
    atc_deviation_triggers = models.TextField(blank=True)
    crew_communications_method = models.CharField(max_length=100, blank=True)
    communications_failure_actions = models.TextField(blank=True)
    radio_discipline = models.CharField(max_length=20, choices=RADIO_DISCIPLINE_CHOICES, blank=True)

    max_wind_mph = models.PositiveIntegerField(null=True, blank=True)
    min_visibility_sm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    minimum_cloud_ceiling_ft = models.PositiveIntegerField(null=True, blank=True)
    minimum_distance_below_clouds_ft = models.PositiveIntegerField(null=True, blank=True)
    minimum_horizontal_cloud_clearance_ft = models.PositiveIntegerField(null=True, blank=True)
    weather_source = models.CharField(max_length=255, blank=True)
    weather_go_nogo = models.TextField(blank=True)
    night_lighting_description = models.TextField(blank=True)

    crew_count = models.PositiveIntegerField(null=True, blank=True)
    crew_briefing_procedure = models.TextField(blank=True)
    prepared_procedures = ArrayField(models.CharField(max_length=30, choices=PREPARED_PROCEDURES_CHOICES), blank=True, default=list)
    generated_conops_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @staticmethod
    def _value_present(value):
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set)):
            return bool(value)
        return value is not None and value is not False

    def completion_sections(self):
        """
        Return operation-planning completion details without storing derived
        progress in the database.

        Each section is complete only when its core planning information is
        present. Optional details do not block completion.
        """
        pilot_name_present = bool(
            self.pilot_profile_id
            or (self.pilot_name_manual or "").strip()
        )
        pilot_certificate_present = bool(
            (self.pilot_cert_manual or "").strip()
            or (
                self.pilot_profile_id
                and (
                    getattr(
                        self.pilot_profile,
                        "faa_certificate_number",
                        "",
                    )
                    or getattr(
                        self.pilot_profile,
                        "license_number",
                        "",
                    )
                )
            )
        )

        aircraft_assignments = list(
            self.aircraft_assignments.all()
        ) if self.pk else []

        aircraft_ready = bool(aircraft_assignments) and all(
            assignment.registration_verified
            and assignment.remote_id_verified
            and assignment.preflight_airworthiness_verified
            and assignment.current_firmware_installed
            for assignment in aircraft_assignments
        )

        approvals = list(self.approvals.all()) if self.pk else []
        approvals_complete = bool(approvals) and all(
            approval.planning_complete
            for approval in approvals
        )

        section_definitions = [
            {
                "key": "operation",
                "title": "Operation Details",
                "requirements": [
                    ("Operation name", self.operation_title),
                    ("Mission description", self.operation_description),
                    ("Start date", self.start_date),
                    ("Operating period", self.timeframe),
                    ("Mission type", self.purpose_operations),
                ],
            },
            {
                "key": "pilot",
                "title": "Remote Pilot",
                "requirements": [
                    ("RPIC selected or entered", pilot_name_present),
                    (
                        "FAA Remote Pilot certificate number",
                        pilot_certificate_present,
                    ),
                ],
            },
            {
                "key": "location",
                "title": "Location and Airspace",
                "requirements": [
                    (
                        "Operation address or venue",
                        self.venue_name or self.street_address,
                    ),
                    ("Operation latitude", self.location_latitude),
                    ("Operation longitude", self.location_longitude),
                    ("Launch location", self.launch_location),
                    ("Landing location", self.recovery_location),
                    ("Airspace classification", self.airspace_class),
                    ("Nearest airport", self.nearest_airport_ref_id),
                ],
            },
            {
                "key": "aircraft",
                "title": "Aircraft",
                "requirements": [
                    ("At least one aircraft assigned", aircraft_assignments),
                    (
                        "Aircraft readiness confirmations complete",
                        aircraft_ready,
                    ),
                ],
            },
            {
                "key": "risk",
                "title": "Ground and Air Risk Controls",
                "requirements": [
                    ("Ground risk controls", self.ground_risk_mitigation),
                    ("Airspace risk controls", self.air_risk_mitigation),
                ],
            },
            {
                "key": "emergency",
                "title": "Emergency Response Planning",
                "requirements": [
                    ("Lost-link procedures", self.lost_link_actions),
                    (
                        "Emergency response procedures",
                        self.emergency_response_plan,
                    ),
                    (
                        "Suspension and termination criteria",
                        self.termination_conditions,
                    ),
                ],
            },
            {
                "key": "approvals",
                "title": "Required FAA Approvals",
                "requirements": [
                    ("At least one approval selected", approvals),
                    (
                        "Approval planning information complete",
                        approvals_complete,
                    ),
                ],
            },
        ]

        sections = []
        for definition in section_definitions:
            missing = [
                label
                for label, value in definition["requirements"]
                if not self._value_present(value)
            ]
            sections.append(
                {
                    "key": definition["key"],
                    "title": definition["title"],
                    "complete": not missing,
                    "missing": missing,
                }
            )

        return sections

    @property
    def completion_percentage(self):
        sections = self.completion_sections()
        if not sections:
            return 0
        complete_count = sum(
            1 for section in sections if section["complete"]
        )
        return round((complete_count / len(sections)) * 100)

    @property
    def completed_section_count(self):
        return sum(
            1
            for section in self.completion_sections()
            if section["complete"]
        )

    @property
    def total_section_count(self):
        return len(self.completion_sections())

    def clean(self):
        super().clean()
        errors = {}
        if self.end_date and self.start_date and self.end_date < self.start_date:
            errors["end_date"] = "The operation end date cannot be before the start date."
        if self.minimum_planned_altitude_agl is not None and self.maximum_planned_altitude_agl is not None and self.minimum_planned_altitude_agl > self.maximum_planned_altitude_agl:
            errors["minimum_planned_altitude_agl"] = "Minimum altitude cannot exceed maximum altitude."
        if self.pilot_profile_id and self.user_id and self.pilot_profile.user_id != self.user_id:
            errors["pilot_profile"] = "You do not have permission to use this pilot profile."
        if self.operation_area_type == "corridor":
            if self.corridor_length_ft is None: errors["corridor_length_ft"] = "Enter the corridor length."
            if self.corridor_width_ft is None: errors["corridor_width_ft"] = "Enter the corridor width."
        if self.lost_link_behavior == "rth" and self.rth_altitude_ft_agl is None:
            errors["rth_altitude_ft_agl"] = "Enter the programmed RTH altitude."
        if errors: raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self._update_airport_distance()
        self.full_clean()
        return super().save(*args, **kwargs)

    def _update_airport_distance(self):
        try:
            if not self.nearest_airport_ref_id and self.nearest_airport:
                self.nearest_airport_ref = Airport.objects.filter(icao=self.nearest_airport.strip().upper(), active=True).first()
            airport = self.nearest_airport_ref
            if not airport or self.location_latitude is None or self.location_longitude is None:
                self.distance_to_airport_nm = None
                return
            p1, p2 = radians(float(self.location_latitude)), radians(float(airport.latitude))
            dp = radians(float(airport.latitude - self.location_latitude))
            dl = radians(float(airport.longitude - self.location_longitude))
            a = sin(dp/2)**2 + cos(p1)*cos(p2)*sin(dl/2)**2
            km = Decimal(str(6371.0088 * (2 * atan2(sqrt(a), sqrt(1-a)))))
            self.distance_to_airport_nm = (km * Decimal("0.539956803")).quantize(Decimal("0.01"))
        except Exception:
            self.distance_to_airport_nm = None

    def primary_aircraft_assignment(self):
        return self.aircraft_assignments.select_related("drone").filter(is_primary=True).first() if self.pk else None

    def __str__(self):
        return self.operation_title

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "status", "-created_at"], name="operation_user_status_idx")]


class OperationAircraft(models.Model):
    """
    Connects an inventory drone to a planned operation.

    The assignment stores an operation-time snapshot of the drone's safety
    features and readiness confirmations without introducing primary/backup
    role concepts that are not needed for the FAA planning workflow.
    """

    operation = models.ForeignKey(
        OperationsPlanning,
        on_delete=models.CASCADE,
        related_name="aircraft_assignments",
    )
    drone = models.ForeignKey(
        "drones.Drone",
        on_delete=models.PROTECT,
        related_name="operation_assignments",
    )

    planned_payload = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Optional camera, sensor, lighting system, propeller guards, "
            "parachute, Remote ID module, or other attached equipment."
        ),
    )

    registration_verified = models.BooleanField(
        default=False,
        help_text=(
            "Confirm that the FAA registration is current, displayed on the "
            "aircraft, and matches the aircraft record."
        ),
    )
    remote_id_verified = models.BooleanField(
        default=False,
        help_text=(
            "Confirm that the aircraft's Remote ID information has been "
            "checked and is operating as required."
        ),
    )
    preflight_airworthiness_verified = models.BooleanField(
        default=False,
        help_text=(
            "Confirm that the aircraft, batteries, propellers, motors, "
            "sensors, controls, and attached equipment are in a condition "
            "for safe operation."
        ),
    )
    current_firmware_installed = models.BooleanField(
        default=False,
        help_text=(
            "Confirm that the aircraft and controller are running the current "
            "manufacturer-approved firmware, unless a documented operational "
            "reason requires another approved version."
        ),
    )

    safety_features_snapshot = models.TextField(
        blank=True,
        help_text=(
            "Snapshot copied automatically from the selected drone's saved "
            "safety features."
        ),
    )
    operation_specific_safety_notes = models.TextField(
        blank=True,
        help_text=(
            "Optional safety information unique to this aircraft's use during "
            "this operation. Examples include additional lighting, propeller "
            "guards, payload handling, reduced operating limits, special "
            "battery procedures, or environmental restrictions. Leave blank "
            "when the standard drone safety profile fully applies."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.operation_id
            and self.drone_id
            and self.operation.user_id != self.drone.user_id
        ):
            errors["drone"] = (
                "The selected drone does not belong to the operation owner."
            )

        if errors:
            raise ValidationError(errors)

    def apply_drone_snapshot(self):
        if self.drone_id and not (self.safety_features_snapshot or "").strip():
            self.safety_features_snapshot = (
                self.drone.safety_features or ""
            ).strip()

    def save(self, *args, **kwargs):
        self.apply_drone_snapshot()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.operation} — {self.drone}"

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["operation", "drone"],
                name="unique_drone_per_operation",
            ),
        ]


class ApprovalType(models.Model):
    CATEGORY_CHOICES = [
        ("airspace", "Airspace Authorization"),
        ("operational_waiver", "Operational Waiver"),
        ("tfr", "TFR Waiver"), ("other", "Other FAA Approval"),
    ]
    code = models.SlugField(unique=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    regulation = models.CharField(max_length=50, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    requires_atc_coordination = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta: ordering = ["category", "display_order", "name"]
    def __str__(self): return f"{self.regulation} — {self.name}" if self.regulation else self.name


class OperationApproval(models.Model):
    STATUS_CHOICES = [
        ("planning", "Planning"),
        ("ready", "Ready to Submit"),
        ("submitted", "Submitted"),
        ("faa_review", "FAA Review"),
        (
            "additional_information",
            "Additional Information Requested",
        ),
        ("approved", "Approved"),
        ("denied", "Denied"),
        ("expired", "Expired"),
        ("withdrawn", "Withdrawn"),
    ]

    operation = models.ForeignKey(
        OperationsPlanning,
        on_delete=models.CASCADE,
        related_name="approvals",
    )
    approval_type = models.ForeignKey(
        ApprovalType,
        on_delete=models.PROTECT,
        related_name="operation_approvals",
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="planning",
    )

    requested_operation = models.TextField(
        blank=True,
        help_text=(
            "Describe exactly what permission or authorization is requested "
            "for this operation."
        ),
    )
    safety_justification = models.TextField(
        blank=True,
        help_text=(
            "Explain why the proposed operation can be conducted safely."
        ),
    )
    risk_mitigations = models.TextField(
        blank=True,
        help_text=(
            "Describe the personnel, procedures, equipment, and operational "
            "controls that reduce the risks created by the requested operation."
        ),
    )
    equivalent_level_of_safety = models.TextField(
        blank=True,
        help_text=(
            "Explain how the proposed controls provide a level of safety "
            "equal to or greater than compliance with the regulation."
        ),
    )

    # Submission and approval management fields. These are edited separately
    # from the planning form.
    faa_tracking_number = models.CharField(
        max_length=100,
        blank=True,
    )
    approval_number = models.CharField(
        max_length=100,
        blank=True,
    )
    approval_document = models.FileField(
        upload_to="operation_approvals/",
        blank=True,
        null=True,
    )
    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    effective_date = models.DateField(
        null=True,
        blank=True,
    )
    expiration_date = models.DateField(
        null=True,
        blank=True,
    )
    special_provisions = models.TextField(
        blank=True,
        help_text=(
            "Record special provisions, conditions, or operating limitations "
            "included in the issued FAA approval."
        ),
    )
    reviewer_notes = models.TextField(
        blank=True,
        help_text=(
            "Optional notes about FAA correspondence, reviewer requests, "
            "or internal follow-up."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def planning_complete(self):
        return all(
            (
                bool(self.approval_type_id),
                bool((self.requested_operation or "").strip()),
                bool((self.safety_justification or "").strip()),
                bool((self.risk_mitigations or "").strip()),
                bool(
                    (
                        self.equivalent_level_of_safety
                        or ""
                    ).strip()
                ),
            )
        )

    @property
    def regulation_display(self):
        if not self.approval_type_id:
            return ""
        return self.approval_type.regulation or ""

    def clean(self):
        super().clean()

        if (
            self.expiration_date
            and self.effective_date
            and self.expiration_date < self.effective_date
        ):
            raise ValidationError(
                {
                    "expiration_date": (
                        "Expiration cannot be before the effective date."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.operation}: {self.approval_type}"

    class Meta:
        ordering = [
            "approval_type__display_order",
            "approval_type__name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["operation", "approval_type"],
                name="unique_approval_type_per_operation",
            )
        ]


class ApprovalApplication(models.Model):
    STATUS_CHOICES = [("draft", "Draft"), ("submitted", "Submitted")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="approval_applications")
    approval = models.ForeignKey(OperationApproval, on_delete=models.CASCADE, related_name="applications")
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    locked_description = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.approval_id and self.user_id and self.approval.operation.user_id != self.user_id:
            raise ValidationError({"approval": "You do not have permission to use this approval."})

    def save(self, *args, **kwargs):
        self.full_clean(); return super().save(*args, **kwargs)

    def __str__(self): return f"Application for {self.approval}"


class ConopsSection(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conops_sections")
    application = models.ForeignKey(ApprovalApplication, on_delete=models.CASCADE, related_name="conops_sections")
    section_key = models.SlugField(max_length=50, db_index=True)
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True)
    locked = models.BooleanField(default=False)
    is_complete = models.BooleanField(default=False)
    validated_at = models.DateTimeField(null=True, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.application_id and self.user_id and self.application.user_id != self.user_id:
            raise ValidationError({"application": "You do not have permission to use this application."})

    class Meta:
        constraints = [models.UniqueConstraint(fields=["application", "section_key"], name="uniq_conops_section_per_application_key")]

    def __str__(self): return f"{self.application_id} – {self.title}"
