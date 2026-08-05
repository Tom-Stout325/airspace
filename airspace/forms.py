# airspace/forms.py
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms
from dal_select2.widgets import ModelSelect2
from django.contrib import messages
from django.utils import timezone

from pilot.models import Aircraft
from pilot.models import PilotProfile
from .models import Airport, WaiverApplication, WaiverPlanning

from .models import _validate_controlled_airspace_required_fields 







TZ_CHOICES = [
    ("America/New_York", "America/New_York"),
    ("America/Chicago", "America/Chicago"),
    ("America/Denver", "America/Denver"),
    ("America/Los_Angeles", "America/Los_Angeles"),
]

RADIUS_CHOICES = [
    ("0.1", "1/10th NM"),
    ("0.25", "1/4th NM"),
    ("0.5", "1/2 NM"),
    ("0.75", "3/4th NM"),
    ("1.0", "1 NM"),
    ("1-2", "1–2 NM"),
    ("2-3", "2–3 NM"),
    ("blanket", "Blanket Area / Wide Area"),
]

DIRECTION_NS_CHOICES = [("N", "N"), ("S", "S")]
DIRECTION_EW_CHOICES = [("E", "E"), ("W", "W")]

TIMEFRAME_CHOICES = [
    ("sunrise_noon", "Sunrise to Noon"),
    ("noon_4pm", "Noon to 4 PM"),
    ("4pm_sunset", "4 PM to Sunset"),
    ("night", "Night"),
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


def _dms_to_decimal(deg, minutes, seconds, direction) -> Decimal:
    """
    Convert DMS parts to signed decimal degrees.
    Returns Decimal quantized to 6 dp (to match model DecimalField).
    """
    deg = Decimal(deg)
    minutes = Decimal(minutes)
    seconds = Decimal(seconds)

    value = deg + (minutes / Decimal(60)) + (seconds / Decimal(3600))
    if direction in ("S", "W"):
        value = -value
    return value.quantize(Decimal("0.000001"))


def _qs_user_scoped(qs, user):
    """
    If the queryset's model has a 'user' field, scope by it.
    Otherwise return qs unchanged (for global tables like Airport).
    """
    if user is None:
        return qs

    model = qs.model
    if any(f.name == "user" for f in model._meta.fields):
        return qs.filter(user=user)

    return qs



class WaiverPlanningForm(forms.ModelForm):
    """
    Main planning form for the Airspace waiver workflow.
    """

    timeframe = forms.MultipleChoiceField(
        choices=TIMEFRAME_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Requested Timeframes",
    )
    purpose_operations = forms.MultipleChoiceField(
        choices=PURPOSE_OPERATIONS_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Purpose of Drone Operations",
    )
    ground_environment = forms.MultipleChoiceField(
        choices=GROUND_ENVIRONMENT_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Ground Environment",
    )
    prepared_procedures = forms.MultipleChoiceField(
        choices=PREPARED_PROCEDURES_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Operational Procedures",
    )

    # --- DMS fields for latitude/longitude (form-only fields) ---
    lat_deg = forms.IntegerField(required=False, min_value=0, max_value=90)
    lat_min = forms.IntegerField(required=False, min_value=0, max_value=59)
    lat_sec = forms.DecimalField(
        required=False,
        min_value=0,
        max_value=Decimal("59.999"),
        decimal_places=3,
    )
    lat_dir = forms.ChoiceField(required=False, choices=DIRECTION_NS_CHOICES)

    lon_deg = forms.IntegerField(required=False, min_value=0, max_value=180)
    lon_min = forms.IntegerField(required=False, min_value=0, max_value=59)
    lon_sec = forms.DecimalField(
        required=False,
        min_value=0,
        max_value=Decimal("59.999"),
        decimal_places=3,
    )
    lon_dir = forms.ChoiceField(required=False, choices=DIRECTION_EW_CHOICES)

    local_time_zone = forms.ChoiceField(
        choices=TZ_CHOICES,
        required=False,
        label="Local time zone",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = WaiverPlanning
        fields = [
            # --- Operation basics ---
            "operation_title",
            "start_date",
            "end_date",
            "timeframe",
            "frequency",
            "local_time_zone",
            "proposed_agl",

            # --- Aircraft ---
            "aircraft",
            "aircraft_manual",

            # --- Pilot ---
            "pilot_profile",
            "pilot_name_manual",
            "pilot_cert_manual",
            "pilot_flight_hours",

            # --- Venue & Location ---
            "venue_name",
            "street_address",
            "location_city",
            "location_state",
            "zip_code",
            "airspace_class",
            "location_radius",
            "nearest_airport_ref",
            "nearest_airport",
            "distance_to_airport_nm",
            "launch_location",

            # --- 107.39 OOP ---
            "operates_under_10739",
            "oop_waiver_document",
            "oop_waiver_number",

            # --- 107.145 Moving Vehicles ---
            "operates_under_107145",
            "mv_waiver_document",
            "mv_waiver_number",

            # --- Safety / VO / insurance ---
            "uses_drone_detection",
            "uses_flight_tracking",
            "has_visual_observer",
            "insurance_provider",
            "insurance_coverage_limit",
            "safety_features_notes",

            # --- Purpose / profile ---
            "purpose_operations",
            "purpose_operations_details",
            "aircraft_count",
            "flight_duration",
            "flights_per_day",
            "estimated_crowd_size",
            "ground_environment",
            "ground_environment_other",
            "prepared_procedures",

            # --- Area definition / containment ---
            "operation_area_type",
            "containment_method",
            "containment_notes",
            "corridor_length_ft",
            "corridor_width_ft",
            "max_groundspeed_mph",

            # --- Emergency / lost link ---
            "lost_link_behavior",
            "rth_altitude_ft_agl",
            "lost_link_actions",
            "flyaway_actions",

            # --- ATC / communications ---
            "atc_facility_name",
            "atc_coordination_method",
            "atc_phone",
            "atc_frequency",
            "atc_checkin_procedure",
            "atc_deviation_triggers",

            # --- Weather & crew ---
            "max_wind_mph",
            "min_visibility_sm",
            "weather_go_nogo",
            "crew_count",
            "crew_briefing_procedure",
            "radio_discipline",

            # hidden / stored decimals (we control saving behavior)
            "location_latitude",
            "location_longitude",
        ]


        widgets = {
            "operation_title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g., NHRA Nationals FPV Coverage"}
            ),
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "frequency": forms.Select(attrs={"class": "form-select"}),
            "proposed_agl": forms.NumberInput(attrs={"min": "0", "class": "form-control"}),

            "aircraft": forms.Select(attrs={"class": "form-select"}),
            "aircraft_manual": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g., Avata 2, Mini 4 Pro"}
            ),

            "pilot_profile": forms.Select(attrs={"class": "form-select"}),
            "pilot_name_manual": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "If not in Pilot Profiles"}
            ),
            "pilot_cert_manual": forms.TextInput(attrs={"class": "form-control"}),
            "pilot_flight_hours": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),

            "venue_name": forms.TextInput(attrs={"class": "form-control"}),
            "street_address": forms.TextInput(attrs={"class": "form-control"}),
            "location_city": forms.TextInput(attrs={"class": "form-control", "placeholder": "City"}),
            "location_state": forms.TextInput(attrs={"class": "form-control", "placeholder": "State (e.g. IN)"}),
            "zip_code": forms.TextInput(attrs={"class": "form-control"}),

            "airspace_class": forms.Select(attrs={"class": "form-select"}),
            "location_radius": forms.Select(attrs={"class": "form-select"}),

            "nearest_airport_ref": ModelSelect2(
                url="airspace:airport-autocomplete",
                attrs={
                    "data-placeholder": "Type ICAO or airport name (e.g., KIND)",
                    "data-minimum-input-length": 1,
                },
            ),
            "nearest_airport": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Manual fallback (e.g., KIND – Indianapolis Intl)"}
            ),

            "purpose_operations_details": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "flight_duration": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. 5–10 minutes"}
            ),
            "estimated_crowd_size": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. ~15,000 (if known)"}
            ),
            "flights_per_day": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "ground_environment_other": forms.Textarea(attrs={"class": "form-control", "rows": 2}),

            # Keep decimals hidden (we control these)
            "location_latitude": forms.HiddenInput(),
            "location_longitude": forms.HiddenInput(),
            "operation_area_type": forms.Select(attrs={"class": "form-select"}),
            "containment_method": forms.Select(attrs={"class": "form-select"}),
            "containment_notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "corridor_length_ft": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "corridor_width_ft": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "max_groundspeed_mph": forms.NumberInput(attrs={"class": "form-control", "min": 0}),

            "lost_link_behavior": forms.Select(attrs={"class": "form-select"}),
            "rth_altitude_ft_agl": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "lost_link_actions": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "flyaway_actions": forms.Textarea(attrs={"class": "form-control", "rows": 3}),

            "atc_facility_name": forms.TextInput(attrs={"class": "form-control"}),
            "atc_coordination_method": forms.Select(attrs={"class": "form-select"}),
            "atc_phone": forms.TextInput(attrs={"class": "form-control"}),
            "atc_frequency": forms.TextInput(attrs={"class": "form-control"}),
            "atc_checkin_procedure": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "atc_deviation_triggers": forms.Textarea(attrs={"class": "form-control", "rows": 3}),

            "max_wind_mph": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "min_visibility_sm": forms.NumberInput(attrs={"class": "form-control", "step": "0.1", "min": 0}),
            "weather_go_nogo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "crew_count": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "crew_briefing_procedure": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "radio_discipline": forms.Select(attrs={"class": "form-select"}),

            
        }

    def _should_lock_distance(self, cleaned=None) -> bool:
        """
        Lock distance_to_airport_nm when we have enough inputs to compute it.
        Works for both initial render (instance) and POST (cleaned).
        """
        if cleaned is not None:
            airport = cleaned.get("nearest_airport_ref")
            lat = cleaned.get("location_latitude")
            lon = cleaned.get("location_longitude")
            return bool(airport and lat is not None and lon is not None)

        airport = getattr(self.instance, "nearest_airport_ref", None)
        lat = getattr(self.instance, "location_latitude", None)
        lon = getattr(self.instance, "location_longitude", None)
        return bool(airport and lat is not None and lon is not None)


    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        if self.user is not None:
            self.instance.user = self.user
            
        if "distance_to_airport_nm" in self.fields:
            if self._should_lock_distance():
                f = self.fields["distance_to_airport_nm"]
                f.disabled = True
                f.required = False
                f.help_text = "Auto-calculated from selected airport + coordinates."
                f.widget.attrs.update({
                    "class": "form-control",
                    "readonly": "readonly",
                })


        for name, field in self.fields.items():
            w = field.widget
            if w.__class__.__module__.startswith("dal"):
                continue
            if isinstance(w, forms.Select):
                w.attrs.setdefault("class", "form-select")
            elif isinstance(w, (forms.TextInput, forms.Textarea, forms.NumberInput, forms.DateInput)):
                w.attrs.setdefault("class", "form-control")

        if not (self.initial.get("local_time_zone") or getattr(self.instance, "local_time_zone", None)):
            self.initial["local_time_zone"] = TZ_CHOICES[0][0] if TZ_CHOICES else None

        if "location_radius" in self.fields:
            self.fields["location_radius"].widget = forms.Select(
                choices=[("", "Select Radius")] + RADIUS_CHOICES,
                attrs={"class": "form-select"},
            )

        for name in ["lat_deg", "lat_min", "lat_sec", "lon_deg", "lon_min", "lon_sec"]:
            if name in self.fields:
                self.fields[name].widget.attrs.setdefault("class", "form-control form-control-sm")
        for name in ["lat_dir", "lon_dir"]:
            if name in self.fields:
                self.fields[name].widget.attrs.setdefault("class", "form-select form-select-sm")

        if "pilot_profile" in self.fields:
            qs = PilotProfile.objects.select_related("user")
            if self.user is not None:
                qs = qs.filter(user=self.user)

            qs = qs.order_by("user__first_name", "user__last_name", "user__email")
            self.fields["pilot_profile"].queryset = qs

            def label_from_instance(obj):
                full_name = f"{obj.user.first_name} {obj.user.last_name}".strip()
                return full_name or obj.user.email

            self.fields["pilot_profile"].label_from_instance = label_from_instance


        if "aircraft" in self.fields:
            qs = Aircraft.objects.filter(active=True)
            qs = _qs_user_scoped(qs, self.user).order_by("brand", "model")
            self.fields["aircraft"].queryset = qs


        if "nearest_airport_ref" in self.fields:
            self.fields["nearest_airport_ref"].queryset = Airport.objects.filter(active=True).order_by("icao")


    def _selected_pilot(self):
        """
        Only return a pilot profile owned by the current user (when user is provided).
        PilotProfile pk is int (default).
        """
        if self.is_bound:
            raw = (self.data.get("pilot_profile") or "").strip()
            if raw.isdigit():
                qs = PilotProfile.objects.select_related("user").filter(pk=int(raw))
                qs = _qs_user_scoped(qs, self.user)
                return qs.first()
            return None

        pilot = getattr(self.instance, "pilot_profile", None)
        if pilot and self.user is not None and hasattr(pilot, "user_id") and pilot.user_id != self.user.id:
            return None
        return pilot


    def _selected_aircraft(self):
        """
        Only return an aircraft owned by the current user (when user is provided).
        UUID-safe aircraft lookup.
        """
        if self.is_bound:
            raw = (self.data.get("aircraft") or "").strip()
            if not raw or not raw.isdigit():
                return None

            qs = Aircraft.objects.filter(pk=int(raw))
            qs = _qs_user_scoped(qs, self.user)
            return qs.first()

        ac = getattr(self.instance, "aircraft", None)
        if ac and self.user is not None and hasattr(ac, "user_id") and ac.user_id != self.user.id:
            return None
        return ac


    def clean(self):
        cleaned = super().clean()

        # -------------------------------------------------
        # Ownership enforcement (server-side)
        # -------------------------------------------------
        if self.user is not None:
            pilot = cleaned.get("pilot_profile")
            if pilot is not None and hasattr(pilot, "user_id") and pilot.user_id != self.user.id:
                self.add_error("pilot_profile", "Invalid selection.")

            aircraft = cleaned.get("aircraft")
            if aircraft is not None and hasattr(aircraft, "user_id") and aircraft.user_id != self.user.id:
                self.add_error("aircraft", "Invalid selection.")

            for doc_field in ("oop_waiver_document", "mv_waiver_document"):
                doc = cleaned.get(doc_field)
                if doc is not None and hasattr(doc, "user_id") and doc.user_id != self.user.id:
                    self.add_error(doc_field, "Invalid selection.")

        # -------------------------------------------------
        # Pilot auto-fill (server-side)
        # -------------------------------------------------
        pilot_obj = self._selected_pilot()
        if pilot_obj:
            # Certificate
            if not cleaned.get("pilot_cert_manual") and (pilot_obj.license_number or "").strip():
                cleaned["pilot_cert_manual"] = pilot_obj.license_number

            # Flight hours
            if not cleaned.get("pilot_flight_hours"):
                total_seconds = pilot_obj.flight_time_total()
                if total_seconds:
                    cleaned["pilot_flight_hours"] = round(total_seconds / 3600, 1)

        # -------------------------------------------------
        # DMS -> Decimal coords (authoritative)
        # -------------------------------------------------
        lat_parts = [
            cleaned.get("lat_deg"),
            cleaned.get("lat_min"),
            cleaned.get("lat_sec"),
            cleaned.get("lat_dir"),
        ]
        lon_parts = [
            cleaned.get("lon_deg"),
            cleaned.get("lon_min"),
            cleaned.get("lon_sec"),
            cleaned.get("lon_dir"),
        ]

        lat_complete = all(part not in (None, "") for part in lat_parts)
        lon_complete = all(part not in (None, "") for part in lon_parts)

        if lat_complete:
            try:
                cleaned["location_latitude"] = _dms_to_decimal(
                    cleaned["lat_deg"], cleaned["lat_min"], cleaned["lat_sec"], cleaned["lat_dir"]
                )
            except (InvalidOperation, ValueError, TypeError):
                self.add_error("lat_sec", "Invalid latitude value.")

        if lon_complete:
            try:
                cleaned["location_longitude"] = _dms_to_decimal(
                    cleaned["lon_deg"], cleaned["lon_min"], cleaned["lon_sec"], cleaned["lon_dir"]
                )
            except (InvalidOperation, ValueError, TypeError):
                self.add_error("lon_sec", "Invalid longitude value.")

        # HARDEN: If DMS not provided, do NOT accept posted hidden coords.
        # Keep the instance values (edit mode) or None (new).
        if not lat_complete:
            cleaned["location_latitude"] = getattr(self.instance, "location_latitude", None)
        if not lon_complete:
            cleaned["location_longitude"] = getattr(self.instance, "location_longitude", None)

        # -------------------------------------------------
        # Distance-to-airport handling
        # - If airport FK + coords exist, the MODEL computes distance in save().
        #   So we *clear* any user-entered value to avoid stale/confusing persistence.
        # - Otherwise, accept manual distance if they typed it.
        # -------------------------------------------------
        if self._should_lock_distance(cleaned):
            cleaned["distance_to_airport_nm"] = None

        return cleaned


    def save(self, commit=True):
        instance = super().save(commit=False)

        # FK fields explicitly (prevents silent drops)
        instance.aircraft = self.cleaned_data.get("aircraft")
        instance.pilot_profile = self.cleaned_data.get("pilot_profile")
        instance.nearest_airport_ref = self.cleaned_data.get("nearest_airport_ref")

        # DMS -> model decimals (authoritative)
        instance.location_latitude = self.cleaned_data.get("location_latitude")
        instance.location_longitude = self.cleaned_data.get("location_longitude")

        # Safety features fallback (server-side)
        if instance.aircraft and not (instance.safety_features_notes or "").strip():
            profile = getattr(instance.aircraft, "drone_safety_profile", None)
            if profile and (profile.safety_features or "").strip():
                instance.safety_features_notes = profile.safety_features

        # Distance: allow manual entry ONLY when we're NOT in auto-compute mode.
        if not self._should_lock_distance(self.cleaned_data):
            instance.distance_to_airport_nm = self.cleaned_data.get("distance_to_airport_nm")
        else:
            # Clear any manual/stale value; model.save() will compute if it can.
            instance.distance_to_airport_nm = None

        if commit:
            instance.save()
            self.save_m2m()

        return instance



class WaiverApplicationDescriptionForm(forms.ModelForm):
    """
    Step 2: Big text box that holds the Description of Operations.
    """

    class Meta:
        model = WaiverApplication
        fields = ["description"]
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 18,
                    "placeholder": "Description of Operations will appear here…",
                }
            )
        }











class WaiverReadinessForm(forms.Form):
    """
    Worksheet form: collect required info before building a WaiverPlanning + WaiverApplication.
    This does NOT save anything by default.
    """

    # -------------------------
    # Operation basics
    # -------------------------
    operation_title         = forms.CharField(required=True, help_text="Short title for this operation (e.g., 'NHRA Nationals FPV Coverage').")
    start_date              = forms.DateField(required=True, widget=forms.DateInput(attrs={"type": "date"}), help_text="First date on which operations will occur.")
    end_date                = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}), help_text="Last date on which operations will occur (optional if single day).")
    timeframe               = forms.MultipleChoiceField(required=False, choices=WaiverPlanning.TIMEFRAME_CHOICES, widget=forms.CheckboxSelectMultiple, help_text="Select all timeframes you expect to operate.")
    frequency               = forms.ChoiceField(required=False, choices=[("", "---------")] + WaiverPlanning.FREQUENCY_CHOICES, help_text="How often operations will occur during this date range.")
    local_time_zone         = forms.CharField(required=False, help_text="Local time zone (e.g., America/New_York).")
    proposed_agl            = forms.IntegerField(required=False, min_value=1, help_text="Maximum planned altitude AGL in feet.")

    # -------------------------
    # Aircraft
    # -------------------------
    aircraft                = forms.ModelChoiceField(required=False, queryset=Aircraft.objects.none(), help_text="Select a drone from your equipment list (optional).")
    aircraft_manual         = forms.CharField(required=False, help_text="If needed, manually describe any additional aircraft types.")

    # -------------------------
    # Pilot
    # -------------------------
    pilot_profile           = forms.ModelChoiceField(required=False, queryset=PilotProfile.objects.none(), help_text="Select a pilot profile (optional).")
    pilot_name_manual       = forms.CharField(required=False, help_text="If not using a profile, enter the RPIC full name.")
    pilot_cert_manual       = forms.CharField(required=False, help_text="If not using a profile, enter the Part 107 certificate number.")
    pilot_flight_hours      = forms.DecimalField(required=False, max_digits=7, decimal_places=1, help_text="Approximate total UAS flight hours.")

    # -------------------------
    # Waivers
    # -------------------------
    operates_under_10739    = forms.BooleanField(required=False, help_text="Check if operating under an approved §107.39 waiver.")
    oop_waiver_document     = forms.FileField(required=False, help_text="Upload your approved §107.39 waiver document (optional).")
    oop_waiver_number       = forms.CharField(required=False, help_text="Example: 107W-2024-01234 (optional if document contains it).")

    operates_under_107145   = forms.BooleanField(required=False, help_text="Check if operating under an approved §107.145 waiver.")
    mv_waiver_document      = forms.FileField(required=False, help_text="Upload your approved §107.145 waiver document (optional).")
    mv_waiver_number        = forms.CharField(required=False, help_text="Example: 107W-2024-04567 (optional if document contains it).")

    # -------------------------
    # Purpose of Operations
    # -------------------------
    purpose_operations      = forms.MultipleChoiceField(required=False, choices=WaiverPlanning.PURPOSE_OPERATIONS_CHOICES, widget=forms.CheckboxSelectMultiple, help_text="Select all purposes that apply.")
    purpose_operations_details = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="Add context: what exactly you’re doing, why, and how.")

    # -------------------------
    # Venue & Location
    # -------------------------
    venue_name              = forms.CharField(required=False, help_text="Venue name (e.g., 'Lucas Oil Raceway').")
    street_address          = forms.CharField(required=False, help_text="Street address of the venue or operation area.")
    location_city           = forms.CharField(required=False, help_text="City where operations occur.")
    location_state          = forms.CharField(required=False, help_text="State where operations occur.")
    zip_code                = forms.CharField(required=False, help_text="ZIP code for the operation location.")
    location_latitude       = forms.DecimalField(required=False, max_digits=9, decimal_places=6, help_text="Decimal latitude for center point (optional but recommended).")
    location_longitude      = forms.DecimalField(required=False, max_digits=9, decimal_places=6, help_text="Decimal longitude for center point (optional but recommended).")
    airspace_class          = forms.ChoiceField(required=False, choices=[("", "---------")] + WaiverPlanning.AIRSPACE_CLASS_CHOICES, help_text="Airspace class at the operation area (B/C/D/E/G).")
    location_radius         = forms.CharField(required=False, help_text="Radius / footprint description (e.g., '0.5 NM' or 'venue footprint').")
    nearest_airport         = forms.CharField(required=False, help_text="Nearest airport identifier/name (e.g., 'KIND').")
    nearest_airport_ref     = forms.ModelChoiceField(required=False, queryset=Airport.objects.all(), help_text="Select an airport reference (preferred).")

    # -------------------------
    # Launch & Safety
    # -------------------------
    launch_location         = forms.CharField(required=False, help_text="Typical launch/staging location description.")
    uses_drone_detection    = forms.BooleanField(required=False, help_text="Will you use a drone detection system (e.g., AirSentinel)?")
    uses_flight_tracking    = forms.BooleanField(required=False, help_text="Will you monitor ADS-B/flight tracking (e.g., FlightAware)?")
    has_visual_observer     = forms.BooleanField(required=False, help_text="Will Visual Observers be used?")
    insurance_provider      = forms.CharField(required=False, help_text="Insurance provider name (optional).")
    insurance_coverage_limit= forms.CharField(required=False, help_text="Coverage limit (e.g., '$5,000,000') (optional).")
    safety_features_notes   = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="Safety features, redundancies, geofencing, briefing notes, etc.")

    # -------------------------
    # Operational Profile
    # -------------------------
    aircraft_count          = forms.ChoiceField(required=False, choices=[("", "---------")] + WaiverPlanning.OP_AIRCRAFT_COUNT_CHOICES, help_text="Single/multiple aircraft (sequential/simultaneous).")
    flight_duration         = forms.CharField(required=False, help_text="Typical flight duration (e.g., 5–10 min).")
    flights_per_day         = forms.IntegerField(required=False, min_value=0, help_text="Approximate flights per day.")
    ground_environment      = forms.MultipleChoiceField(required=False, choices=WaiverPlanning.GROUND_ENVIRONMENT_CHOICES, widget=forms.CheckboxSelectMultiple, help_text="Select environment types present.")
    ground_environment_other= forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), help_text="Add any environment types not listed.")
    estimated_crowd_size    = forms.CharField(required=False, help_text="Estimated maximum crowd size (optional).")
    prepared_procedures     = forms.MultipleChoiceField(required=False, choices=WaiverPlanning.PREPARED_PROCEDURES_CHOICES, widget=forms.CheckboxSelectMultiple, help_text="Select procedures/checklists used.")

    operation_area_type     = forms.ChoiceField(required=False, choices=WaiverPlanning._meta.get_field("operation_area_type").choices, help_text="Radius/corridor/polygon/site.")
    containment_method      = forms.ChoiceField(required=False, choices=[("", "---------")] + WaiverPlanning._meta.get_field("containment_method").choices, help_text="How the area is contained (geofence/markers/etc.).")
    containment_notes       = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="How containment is briefed, verified, and enforced on-site.")
    corridor_length_ft      = forms.IntegerField(required=False, min_value=0, help_text="If corridor operations: length in feet.")
    corridor_width_ft       = forms.IntegerField(required=False, min_value=0, help_text="If corridor operations: width in feet.")
    max_groundspeed_mph     = forms.IntegerField(required=False, min_value=0, help_text="Max groundspeed in mph (optional).")

    # -------------------------
    # Emergency / Lost Link
    # -------------------------
    lost_link_behavior      = forms.ChoiceField(required=False, choices=[("", "---------")] + WaiverPlanning._meta.get_field("lost_link_behavior").choices, help_text="RTH / hover / land.")
    rth_altitude_ft_agl     = forms.IntegerField(required=False, min_value=0, help_text="If using RTH: the programmed RTH altitude (ft AGL).")
    lost_link_actions       = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="Step-by-step actions for a lost link.")
    flyaway_actions         = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="Step-by-step actions for a flyaway (tracking, last-known location, notifications).")

    # -------------------------
    # ATC / Communications
    # -------------------------
    atc_facility_name       = forms.CharField(required=False, help_text="Tower/TRACON/approach/airport ops facility name if known.")
    atc_coordination_method = forms.ChoiceField(required=False, choices=[("", "---------")] + WaiverPlanning._meta.get_field("atc_coordination_method").choices, help_text="Phone / radio / both / other.")
    atc_phone               = forms.CharField(required=False, help_text="If phone coordination: best contact number.")
    atc_frequency           = forms.CharField(required=False, help_text="If radio coordination: frequency.")
    atc_checkin_procedure   = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="When/how you check-in, what info you provide, and termination steps.")
    atc_deviation_triggers  = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="Triggers for immediate termination or coordination (traffic, weather, etc.).")

    # -------------------------
    # Weather & Crew
    # -------------------------
    max_wind_mph            = forms.IntegerField(required=False, min_value=0, help_text="Max wind in mph (optional).")
    min_visibility_sm       = forms.DecimalField(required=False, max_digits=4, decimal_places=1, help_text="Minimum visibility in statute miles (optional).")
    weather_go_nogo         = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="Additional go/no-go rules (gust spread, precip, lightning, ceiling).")
    crew_count              = forms.IntegerField(required=False, min_value=0, help_text="Total crew count (optional).")
    crew_briefing_procedure = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="Pre-ops briefing: boundaries, roles, comms, abort triggers.")
    radio_discipline        = forms.ChoiceField(required=False, choices=[("", "---------")] + WaiverPlanning._meta.get_field("radio_discipline").choices, help_text="Sterile vs standard comms discipline.")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # User-scoped dropdowns
        if user is not None:
            self.fields["aircraft"].queryset = Aircraft.objects.filter(user=user, active=True).order_by("brand", "model", "id")
            self.fields["pilot_profile"].queryset = PilotProfile.objects.filter(user=user).order_by("id")


    def apply_controlled_airspace_validation(self, *, user) -> None:
        """
        Run the same controlled-airspace requirements you enforce on the model,
        but against this worksheet’s cleaned_data.
        """
        # Build an in-memory WaiverPlanning instance with your exact field names
        planning = WaiverPlanning(user=user, **self.cleaned_data)
        ca_errors = _validate_controlled_airspace_required_fields(planning) or {}
        for field, msgs in ca_errors.items():
            if isinstance(msgs, str):
                msgs = [msgs]
            for msg in msgs:
                self.add_error(field, msg)