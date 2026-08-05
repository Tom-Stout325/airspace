# airspace/models.py
from __future__ import annotations

from decimal import Decimal
from math import radians, sin, cos, sqrt, atan2

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models




# ==========================================================
# CONTROLLED AIRSPACE REQUIREMENTS (FAA WAIVER DESCRIPTION)
# ==========================================================

CONTROLLED_AIRSPACE_CLASSES = {"B", "C", "D", "E"}


def _has_text(v) -> bool:
    return bool((v or "").strip()) if isinstance(v, str) else bool(v)


def _is_controlled_airspace(planning) -> bool:
    return (getattr(planning, "airspace_class", "") or "").strip().upper() in CONTROLLED_AIRSPACE_CLASSES


def _validate_controlled_airspace_required_fields(planning) -> dict:
    if not _is_controlled_airspace(planning):
        return {}

    errors = {}
    
    def add(field: str, msg: str) -> None:
        errors.setdefault(field, []).append(msg)

    op_area = (getattr(planning, "operation_area_type", "") or "").strip().lower()
    
    if not op_area:
        add(
            "operation_area_type",
            "Required for controlled airspace: define the operation area type (radius/corridor/polygon/site).",
        )

    containment_ok = (
        _has_text(getattr(planning, "containment_method", "")) or
        _has_text(getattr(planning, "containment_notes", ""))
    )
    
    if not containment_ok:
        add(
            "containment_method",
            "Required for controlled airspace: choose a containment method or provide containment notes.",
        )
        add(
            "containment_notes",
            "Required for controlled airspace: describe how containment is enforced/verified on-site (no inventing).",
        )

    if op_area == "corridor":
        if getattr(planning, "corridor_length_ft", None) is None:
            add("corridor_length_ft", "Required when operation area type is 'corridor': provide corridor length (ft).")
        if getattr(planning, "corridor_width_ft", None) is None:
            add("corridor_width_ft", "Required when operation area type is 'corridor': provide corridor width (ft).")

    # ----- ATC coordination: require procedural content (not just a name) -----
    atc_method = (getattr(planning, "atc_coordination_method", "") or "").strip()
    atc_phone = (getattr(planning, "atc_phone", "") or "").strip()
    atc_freq = (getattr(planning, "atc_frequency", "") or "").strip()
    atc_checkin = (getattr(planning, "atc_checkin_procedure", "") or "").strip()

    has_contact_detail = bool(atc_phone or atc_freq)
    atc_ok = bool(atc_checkin) or (bool(atc_method) and has_contact_detail)

    if not atc_ok:
        add(
            "atc_checkin_procedure",
            "Required for controlled airspace: describe check-in / coordination steps (when/how, what info, and termination procedure).",
        )
        add(
            "atc_coordination_method",
            "Required for controlled airspace if no check-in procedure is provided: select phone/radio/both/other.",
        )
        add("atc_phone", "Provide if coordination uses phone (or if phone is part of 'both').")
        add("atc_frequency", "Provide if coordination uses radio (or if radio is part of 'both').")

    if not _has_text(getattr(planning, "atc_deviation_triggers", "")):
        add(
            "atc_deviation_triggers",
            "Required for controlled airspace: define deviation/termination triggers (traffic, weather, direction, etc.).",
        )

    # ----- Lost link / flyaway -----
    llb = (getattr(planning, "lost_link_behavior", "") or "").strip()
    if not llb:
        add("lost_link_behavior", "Required for controlled airspace: select lost-link behavior (RTH/hover/land).")

    if not _has_text(getattr(planning, "lost_link_actions", "")):
        add(
            "lost_link_actions",
            "Required for controlled airspace: provide step-by-step lost-link actions (who does what, who is notified, and how ops terminate).",
        )

    if llb == "rth" and getattr(planning, "rth_altitude_ft_agl", None) is None:
        add("rth_altitude_ft_agl", "Required when lost-link behavior is RTH: provide RTH altitude (ft AGL).")

    if not _has_text(getattr(planning, "flyaway_actions", "")):
        add(
            "flyaway_actions",
            "Required for controlled airspace: provide flyaway actions (tracking/last-known position capture and facility notification).",
        )

    return errors


def _ownership_error() -> str:
    return "You do not have permission to use this object."


def _model_has_user_fk(obj) -> bool:
    """
    True if the related model instance appears to be user-owned.
    (We avoid importing the other app models here.)
    """
    return obj is not None and hasattr(obj, "user_id")



class WaiverPlanning(models.Model):
    """
    Holds planning details that are not part of the FAA waiver form itself but
    are critical for the waiver application and Description of Operations /
    CONOPS: aircraft, pilot, dates, location, safety features, and operational
    profile.
    """

    # -------------------------
    # Choices
    # -------------------------
    TIMEFRAME_CHOICES = [
        ("sunrise_noon", "Sunrise to Noon"),
        ("noon_4pm", "Noon to 4 PM"),
        ("4pm_sunset", "4 PM to Sunset"),
        ("night", "Night"),
    ]

    FREQUENCY_CHOICES = [
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("biweekly", "Bi-weekly"),
        ("monthly", "Monthly"),
    ]

    AIRSPACE_CLASS_CHOICES = [
        ("B", "Class B"),
        ("C", "Class C"),
        ("D", "Class D"),
        ("E", "Class E"),
        ("G", "Class G"),
    ]

    PURPOSE_OPERATIONS_CHOICES = [
        ("event_filming", "Event filming / broadcast"),
        ("pro_photography", "Professional aerial photography"),
        ("mapping_survey", "Mapping / survey"),
        ("infrastructure_inspection", "Infrastructure inspection"),
        ("public_safety", "Public safety / incident support"),
        ("training_proficiency", "Training / proficiency flights"),
        ("real_estate", "Real estate photography"),
    ]

    # --- Operational Profile & Environment ---
    OP_AIRCRAFT_COUNT_CHOICES = [
        ("single", "Single aircraft"),
        ("multi_sequential", "Multiple aircraft (sequential use)"),
        ("multi_simultaneous", "Multiple aircraft (simultaneous use)"),
    ]

    GROUND_ENVIRONMENT_CHOICES = [
        ("residential", "Residential property / housing"),
        ("commercial", "Commercial buildings / business areas"),
        ("industrial", "Industrial or construction sites"),
        ("agricultural", "Agricultural land / open fields"),
        ("forested", "Forested or rural terrain"),
        ("water", "Water features (lakes, rivers, coastlines)"),
        ("roadways", "Roadways / parking areas"),
        ("pedestrian", "Pedestrian walkways / public access areas"),
        ("recreational", "Recreational areas (parks, trails, fields)"),
        ("infrastructure", "Critical infrastructure (utilities, towers, pipelines)"),
        ("unpopulated", "Unpopulated or remote terrain"),
        ("crowd_sparse", "Sparse people present"),
        ("crowd_moderate", "Moderate public presence"),
        ("crowd_dense", "Dense gatherings / event crowds"),
    ]


    PREPARED_PROCEDURES_CHOICES = [
        ("preflight", "Pre-flight checklist used"),
        ("postflight", "Post-flight checklist used"),
        ("lost_link", "Lost-link / flyaway procedure in place"),
        ("emergency_lz", "Emergency landing zones pre-identified"),
    ]

    # -------------------------
    # Ownership
    # -------------------------
    user                         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="waiver_planning_entries")

    # -------------------------
    # Operation basics
    # -------------------------
    operation_title              = models.CharField(max_length=255, help_text="Short title for this operation (e.g., 'NHRA Nationals FPV Coverage').")
    start_date                   = models.DateField(help_text="First date on which operations will occur.")
    end_date                     = models.DateField(null=True, blank=True, help_text="Last date on which operations will occur (optional if single day).")
    timeframe                    = ArrayField(models.CharField(max_length=20, choices=TIMEFRAME_CHOICES), blank=True, default=list, help_text="Select all timeframes you expect to operate.")
    frequency                    = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, blank=True, help_text="How often operations will occur during this date range.")
    local_time_zone              = models.CharField(max_length=64, blank=True, help_text="Local time zone for the operation (e.g., America/New_York).")
    proposed_agl                 = models.PositiveIntegerField(null=True, blank=True, help_text="Maximum planned altitude AGL in feet.")

    # -------------------------
    # Aircraft
    # -------------------------
    aircraft                     = models.ForeignKey("pilot.Aircraft", null=True, blank=True, on_delete=models.SET_NULL, related_name="waiver_planning_entries")
    aircraft_manual              = models.CharField(max_length=255, blank=True, help_text="If needed, manually describe any additional aircraft types.")

    # -------------------------
    # Pilot
    # -------------------------
    pilot_profile                = models.ForeignKey("pilot.PilotProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="waiver_planning_entries")
    pilot_name_manual            = models.CharField(max_length=255, blank=True)
    pilot_cert_manual            = models.CharField(max_length=255, blank=True)
    pilot_flight_hours           = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True, help_text="Approximate total UAS flight hours.")

    # -------------------------
    # Waivers
    # -------------------------
    operates_under_10739         = models.BooleanField(default=False)
    oop_waiver_document          = models.FileField(upload_to="waivers/", null=True, blank=True)
    oop_waiver_number            = models.CharField(max_length=100, blank=True)
    operates_under_107145        = models.BooleanField(default=False)
    mv_waiver_document           = models.FileField(upload_to="waivers/", null=True, blank=True)
    mv_waiver_number             = models.CharField(max_length=100, blank=True)

    # -------------------------
    # Purpose of Operations
    # -------------------------
    purpose_operations           = ArrayField(models.CharField(max_length=50, choices=PURPOSE_OPERATIONS_CHOICES), blank=True, default=list)
    purpose_operations_details   = models.TextField(blank=True, null=True)

    # -------------------------
    # Venue & Location
    # -------------------------
    venue_name                   = models.CharField(max_length=255, blank=True)
    street_address               = models.CharField(max_length=255, blank=True)
    location_city                = models.CharField(max_length=100, blank=True)
    location_state               = models.CharField(max_length=100, blank=True)
    zip_code                     = models.CharField(max_length=20, blank=True)
    location_latitude            = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_longitude           = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    airspace_class               = models.CharField(max_length=1, choices=AIRSPACE_CLASS_CHOICES, blank=True)
    location_radius              = models.CharField(max_length=20, blank=True, null=True)
    nearest_airport              = models.CharField(max_length=255, blank=True)
    nearest_airport_ref          = models.ForeignKey("airspace.Airport", null=True, blank=True, on_delete=models.SET_NULL, related_name="waiver_planning_entries")
    distance_to_airport_nm       = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # -------------------------
    # Launch & Safety
    # -------------------------
    launch_location              = models.CharField(max_length=255, blank=True)
    uses_drone_detection         = models.BooleanField(default=False)
    uses_flight_tracking         = models.BooleanField(default=False)
    has_visual_observer          = models.BooleanField(default=False)
    insurance_provider           = models.CharField(max_length=255, blank=True)
    insurance_coverage_limit     = models.CharField(max_length=100, blank=True)
    safety_features_notes        = models.TextField(blank=True)

    # -------------------------
    # Operational Profile
    # -------------------------
    aircraft_count               = models.CharField(max_length=25, choices=OP_AIRCRAFT_COUNT_CHOICES, blank=True)
    flight_duration              = models.CharField(max_length=50, blank=True)
    flights_per_day              = models.PositiveIntegerField(null=True, blank=True)
    ground_environment           = ArrayField(models.CharField(max_length=50, choices=GROUND_ENVIRONMENT_CHOICES), blank=True, default=list)
    ground_environment_other     = models.TextField(blank=True)
    estimated_crowd_size         = models.CharField(max_length=50, blank=True)
    prepared_procedures          = ArrayField(models.CharField(max_length=30, choices=PREPARED_PROCEDURES_CHOICES), blank=True, default=list)
    operation_area_type          = models.CharField(max_length=20, choices=[("radius","Radius"),("corridor","Corridor"),("polygon","Polygon"),("site","Site")], default="radius")
    containment_method           = models.CharField(max_length=20, choices=[("geofence","Geofence"),("visual_markers","Visual markers"),("map_overlays","Map overlays"),("combination","Combination")], blank=True)
    containment_notes            = models.TextField(blank=True)
    corridor_length_ft           = models.PositiveIntegerField(null=True, blank=True)
    corridor_width_ft            = models.PositiveIntegerField(null=True, blank=True)
    max_groundspeed_mph          = models.PositiveIntegerField(null=True, blank=True)

    # -------------------------
    # Emergency / Lost Link
    # -------------------------
    lost_link_behavior           = models.CharField(max_length=20, choices=[("rth","RTH"),("hover","Hover"),("land","Land")], blank=True)
    rth_altitude_ft_agl          = models.PositiveIntegerField(null=True, blank=True, help_text="If using RTH, the programmed RTH altitude in feet AGL.")
    lost_link_actions            = models.TextField(blank=True)
    flyaway_actions              = models.TextField(blank=True)

    # -------------------------
    # ATC / Communications
    # -------------------------
    atc_facility_name            = models.CharField(max_length=255, blank=True)
    atc_coordination_method      = models.CharField(max_length=20, choices=[("phone","Phone"),("radio","Radio"),("both","Phone + Radio"),("other","Other")], blank=True)
    atc_phone                    = models.CharField(max_length=50, blank=True)
    atc_frequency                = models.CharField(max_length=50, blank=True)
    atc_checkin_procedure        = models.TextField(blank=True)
    atc_deviation_triggers       = models.TextField(blank=True)

    # -------------------------
    # Weather & Crew
    # -------------------------
    max_wind_mph                 = models.PositiveIntegerField(null=True, blank=True)
    min_visibility_sm            = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    weather_go_nogo              = models.TextField(blank=True)
    crew_count                   = models.PositiveIntegerField(null=True, blank=True)
    crew_briefing_procedure      = models.TextField(blank=True)
    radio_discipline             = models.CharField(max_length=20, choices=[("sterile","Sterile"),("standard","Standard")], blank=True)

    # -------------------------
    # Timestamps
    # -------------------------
    generated_description_at     = models.DateTimeField(null=True, blank=True)
    created_at                   = models.DateTimeField(auto_now_add=True)
    updated_at                   = models.DateTimeField(auto_now=True)



    # -------------------------
    # Convenience helpers
    # -------------------------
    def debug_summary(self):
        """
        Temporary debugging helper.
        Use in shell / logs to confirm what is actually saved.
        """
        return {
            "aircraft_id": self.aircraft_id,
            "aircraft_manual": self.aircraft_manual,
            "pilot_profile_id": self.pilot_profile_id,
            "pilot_name_manual": self.pilot_name_manual,
            "pilot_cert_manual": self.pilot_cert_manual,
            "pilot_flight_hours": self.pilot_flight_hours,
        }

    def pilot_display_name(self) -> str:
        """
        Best available pilot display name:
        1) manual override (pilot_name_manual)
        2) PilotProfile user's first/last
        3) PilotProfile user's email (last resort)
        """
        manual = (self.pilot_name_manual or "").strip()
        if manual:
            return manual

        profile = getattr(self, "pilot_profile", None)
        if not profile or not getattr(profile, "user", None):
            return ""

        first = (profile.user.first_name or "").strip()
        last = (profile.user.last_name or "").strip()
        if first or last:
            return f"{first} {last}".strip()

        return (profile.user.email or "").strip()

    def pilot_cert_display(self) -> str:
        """
        Best available Part 107 certificate / license number:
        1) manual override (pilot_cert_manual)
        2) PilotProfile.license_number
        """
        manual = (self.pilot_cert_manual or "").strip()
        if manual:
            return manual

        profile = getattr(self, "pilot_profile", None)
        return (getattr(profile, "license_number", "") or "").strip()

    def pilot_hours_display(self) -> str:
        return "" if self.pilot_flight_hours is None else f"{self.pilot_flight_hours:.1f}"

    def aircraft_display(self) -> str:
        if self.aircraft:
            return str(self.aircraft)
        if self.aircraft_manual:
            return self.aircraft_manual
        return ""

    def timeframe_codes(self):
        """
        Returns timeframe as a list of codes.
        Supports both ArrayField (native list) and legacy CSV storage.
        """
        if not self.timeframe:
            return []
        if isinstance(self.timeframe, (list, tuple)):
            return list(self.timeframe)
        return [c.strip() for c in str(self.timeframe).split(",") if c.strip()]

    def apply_aircraft_safety_profile(self):
        """
        If an aircraft with a DroneSafetyProfile is selected and safety_features_notes
        is currently empty/whitespace, copy the profile's safety_features in.

        We *don't* overwrite existing notes so you can safely customize them.
        """
        if self.aircraft and not (self.safety_features_notes or "").strip():
            profile = getattr(self.aircraft, "drone_safety_profile", None)
            if profile and profile.safety_features:
                self.safety_features_notes = profile.safety_features

    def clean(self):
        """
        Ownership + integrity guards (server-side, admin-safe).
        Also enforces controlled-airspace FAA fields so the waiver description
        cannot be forced to invent Paragraph 2 procedures.
        """
        super().clean()
        errors = {}

        # If Equipment/PilotProfile are user-owned models, enforce same-owner
        if self.aircraft and _model_has_user_fk(self.aircraft):
            if self.aircraft.user_id != self.user_id:
                errors["aircraft"] = _ownership_error()

        if self.pilot_profile and _model_has_user_fk(self.pilot_profile):
            if self.pilot_profile.user_id != self.user_id:
                errors["pilot_profile"] = _ownership_error()

        if self.oop_waiver_document and _model_has_user_fk(self.oop_waiver_document):
            if self.oop_waiver_document.user_id != self.user_id:
                errors["oop_waiver_document"] = _ownership_error()

        if self.mv_waiver_document and _model_has_user_fk(self.mv_waiver_document):
            if self.mv_waiver_document.user_id != self.user_id:
                errors["mv_waiver_document"] = _ownership_error()

        # CONTROLLED AIRSPACE: enforce FAA-specific fields so Description Paragraph 2 is never forced to invent
        ca_errors = _validate_controlled_airspace_required_fields(self)
        for field, msgs in (ca_errors or {}).items():
            # normalize to list
            if isinstance(msgs, str):
                msgs = [msgs]
            else:
                msgs = list(msgs)

            if field in errors:
                existing = errors[field]
                if isinstance(existing, str):
                    errors[field] = [existing] + msgs
                else:
                    errors[field] = list(existing) + msgs
            else:
                errors[field] = msgs

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Apply safety features from aircraft profile if appropriate
        self.apply_aircraft_safety_profile()

        # Auto-fill 107.39 waiver number from attached document if available
        if self.operates_under_10739 and self.oop_waiver_document and not self.oop_waiver_number:
            number = getattr(self.oop_waiver_document, "waiver_number", None)
            if number:
                self.oop_waiver_number = number

        # Auto-fill 107.145 waiver number from attached document if available
        if self.operates_under_107145 and self.mv_waiver_document and not self.mv_waiver_number:
            number = getattr(self.mv_waiver_document, "waiver_number", None)
            if number:
                self.mv_waiver_number = number

        # If you have an update_decimal_coords helper elsewhere, call it safely
        if hasattr(self, "update_decimal_coords"):
            self.update_decimal_coords()

        # -------------------------------------------------
        # Airport FK + distance (keeps legacy nearest_airport)
        # -------------------------------------------------
        try:
            NM_PER_KM = Decimal("0.539956803")
            EARTH_RADIUS_KM = Decimal("6371.0088")

            def haversine_nm(lat1, lon1, lat2, lon2) -> Decimal:
                phi1 = radians(float(lat1))
                phi2 = radians(float(lat2))
                dphi = radians(float(lat2 - lat1))
                dlambda = radians(float(lon2 - lon1))
                a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
                c = 2 * atan2(sqrt(a), sqrt(1 - a))
                km = Decimal(str(float(EARTH_RADIUS_KM) * c))
                return (km * NM_PER_KM).quantize(Decimal("0.01"))

            # If FK not set, try to map from legacy ICAO char field
            if not self.nearest_airport_ref_id:
                code = (getattr(self, "nearest_airport", "") or "").strip().upper()
                if code:
                    self.nearest_airport_ref = Airport.objects.filter(icao=code).first()

            # Only compute distance when we have enough data
            if (
                self.nearest_airport_ref_id
                and self.location_latitude is not None
                and self.location_longitude is not None
                and self.nearest_airport_ref is not None
                and getattr(self.nearest_airport_ref, "latitude", None) is not None
                and getattr(self.nearest_airport_ref, "longitude", None) is not None
            ):
                self.distance_to_airport_nm = haversine_nm(
                    self.location_latitude,
                    self.location_longitude,
                    self.nearest_airport_ref.latitude,
                    self.nearest_airport_ref.longitude,
                )
            else:
                self.distance_to_airport_nm = None

        except Exception:
            # Never block saves if airport table isn't loaded yet or during migrations
            pass

        # HARDEN: validate ownership & integrity on every save
        self.full_clean()

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.operation_title} ({self.user})"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Waiver Planning Entry"
        verbose_name_plural = "Waiver Planning Entries"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]




class WaiverApplication(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="waiver_applications",
    )
    planning = models.ForeignKey(
        WaiverPlanning,
        on_delete=models.CASCADE,
        related_name="applications",
    )

    description = models.TextField(
        blank=True,
        help_text="Generated Description of Operations for this waiver.",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
    )
    locked_description = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        errors = {}

        # HARDEN: planning must belong to same user
        if self.planning_id and self.planning and self.planning.user_id != self.user_id:
            errors["planning"] = _ownership_error()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Waiver Application for {self.planning.operation_title} ({self.user})"

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]


# ------------------------------------
#               C O N O P S
# ------------------------------------
class ConopsSection(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conops_sections",
    )

    application = models.ForeignKey(
        "airspace.WaiverApplication",
        on_delete=models.CASCADE,
        related_name="conops_sections",
    )

    section_key = models.SlugField(
        max_length=50,
        db_index=True,
        help_text="Internal identifier, e.g. 'purpose_of_operations'",
    )

    title = models.CharField(
        max_length=255,
        help_text="Section title shown in the CONOPS document",
    )

    content = models.TextField(blank=True)

    locked = models.BooleanField(default=False)

    is_complete = models.BooleanField(default=False)
    validated_at = models.DateTimeField(null=True, blank=True)

    generated_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        errors = {}

        # HARDEN: section owner must match application owner
        if self.application_id and self.application and self.application.user_id != self.user_id:
            errors["application"] = _ownership_error()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "section_key"],
                name="uniq_conops_section_per_application_key",
            )
        ]
        indexes = [
            models.Index(fields=["application", "section_key"]),
        ]


    def __str__(self):
        return f"{self.application_id} – {self.title}"


class Airport(models.Model):
    """
    FAA NASR airport reference data.
    Used for controlled airspace planning and distance calculations.
    """

    icao = models.CharField(
        max_length=4,
        unique=True,
        help_text="ICAO airport identifier (e.g. KIND)",
    )

    name = models.CharField(
        max_length=255,
        help_text="Official airport name from FAA NASR",
    )

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        help_text="Airport Reference Point latitude (decimal degrees)",
    )

    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        help_text="Airport Reference Point longitude (decimal degrees)",
    )

    # ---- Reference-only fields (optional but recommended) ----
    street_address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    zip_code = models.CharField(max_length=10, blank=True)

    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["icao"]

    def __str__(self):
        return f"{self.icao} – {self.name}"
#-----------------------------------------------------------------------------------------------------------------


