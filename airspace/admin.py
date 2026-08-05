# airspace/admin.py

from __future__ import annotations

from django.contrib import admin
from django.core.exceptions import ValidationError

from .models import WaiverPlanning, WaiverApplication, ConopsSection, Airport



@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ("icao", "name", "city", "state", "active")
    list_filter = ("active", "state")
    search_fields = ("icao", "name", "city", "state")
    ordering = ("icao",)
    
    
class ConopsSectionInline(admin.TabularInline):
    model = ConopsSection
    extra = 0
    fields = (
        "section_key",
        "title",
        "locked",
        "is_complete",
        "generated_at",
        "validated_at",
        "updated_at",
    )
    readonly_fields = ("generated_at", "validated_at", "updated_at")
    ordering = ("id",)
    show_change_link = True


@admin.register(WaiverPlanning)
class WaiverPlanningAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "operation_title",
        "user",
        "start_date",
        "end_date",
        "airspace_class",
        "location_city",
        "location_state",
        "aircraft",
        "pilot_profile",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "airspace_class",
        "operates_under_10739",
        "operates_under_107145",
        "uses_drone_detection",
        "uses_flight_tracking",
        "has_visual_observer",
        "created_at",
        "updated_at",
    )
    search_fields = (
        "operation_title",
        "venue_name",
        "street_address",
        "location_city",
        "location_state",
        "zip_code",
        "nearest_airport",
        "oop_waiver_number",
        "mv_waiver_number",
        "pilot_name_manual",
        "pilot_cert_manual",
        "aircraft_manual",
        "atc_facility_name",
        "atc_phone",
        "atc_frequency",
        "user__email",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    raw_id_fields = ("user",)
    autocomplete_fields = ("aircraft", "pilot_profile", "nearest_airport_ref")

    fieldsets = (
        ("Ownership", {"fields": ("user",)}),

        (
            "Operation Basics",
            {"fields": ("operation_title", "start_date", "end_date", "timeframe", "frequency", "local_time_zone", "proposed_agl")},
        ),

        ("Aircraft", {"fields": ("aircraft", "aircraft_manual")}),

        ("Pilot", {"fields": ("pilot_profile", "pilot_name_manual", "pilot_cert_manual", "pilot_flight_hours")}),

        (
            "Existing Waivers",
            {"fields": ("operates_under_10739", "oop_waiver_document", "oop_waiver_number", "operates_under_107145", "mv_waiver_document", "mv_waiver_number")},
        ),

        ("Purpose", {"fields": ("purpose_operations", "purpose_operations_details")}),

        (
            "Venue & Location",
            {
                "fields": (
                    "venue_name",
                    "street_address",
                    "location_city",
                    "location_state",
                    "zip_code",
                    "location_latitude",
                    "location_longitude",
                    "airspace_class",
                    "location_radius",
                    "nearest_airport",
                    "nearest_airport_ref",
                    "distance_to_airport_nm",
                )
            },
        ),

        (
            "Launch & Safety",
            {"fields": ("launch_location", "uses_drone_detection", "uses_flight_tracking", "has_visual_observer", "insurance_provider", "insurance_coverage_limit", "safety_features_notes")},
        ),

        (
            "Operational Profile",
            {
                "fields": (
                    "aircraft_count",
                    "flight_duration",
                    "flights_per_day",
                    "ground_environment",
                    "ground_environment_other",
                    "estimated_crowd_size",
                    "prepared_procedures",
                    "operation_area_type",
                    "containment_method",
                    "containment_notes",
                    "corridor_length_ft",
                    "corridor_width_ft",
                    "max_groundspeed_mph",
                )
            },
        ),

        (
            "Emergency & Lost Link",
            {"fields": ("lost_link_behavior", "rth_altitude_ft_agl", "lost_link_actions", "flyaway_actions")},
        ),

        (
            "ATC & Communications",
            {"fields": ("atc_facility_name", "atc_coordination_method", "atc_phone", "atc_frequency", "atc_checkin_procedure", "atc_deviation_triggers")},
        ),

        ("Weather & Crew", {"fields": ("max_wind_mph", "min_visibility_sm", "weather_go_nogo", "crew_count", "crew_briefing_procedure", "radio_discipline")}),

        ("Timestamps", {"fields": ("generated_description_at", "created_at", "updated_at")}),
    )

    readonly_fields = ("generated_description_at", "created_at", "updated_at", "distance_to_airport_nm")

    def save_model(self, request, obj, form, change):
        """
        Ensure model.clean()/full_clean() errors show as nice admin form errors.
        """
        try:
            obj.full_clean()
        except ValidationError as e:
            form.add_error(None, e)
            return
        super().save_model(request, obj, form, change)


@admin.register(WaiverApplication)
class WaiverApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "planning",
        "user",
        "status",
        "locked_description",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "locked_description", "created_at", "updated_at")
    search_fields = (
        "planning__operation_title",
        "planning__venue_name",
        "planning__location_city",
        "planning__location_state",
        "user__email",
        "user__email",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    raw_id_fields = ("user", "planning")
    autocomplete_fields = ("planning",)
    inlines = (ConopsSectionInline,)

    fieldsets = (
        ("Links", {"fields": ("user", "planning")}),
        ("Application", {"fields": ("status", "locked_description", "description")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(ConopsSection)
class ConopsSectionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "application",
        "user",
        "section_key",
        "title",
        "locked",
        "is_complete",
        "generated_at",
        "validated_at",
        "updated_at",
    )
    list_filter = ("locked", "is_complete", "generated_at", "validated_at", "updated_at")
    search_fields = (
        "section_key",
        "title",
        "content",
        "application__planning__operation_title",
        "application__user__email",
        "application__user__email",
    )
    date_hierarchy = "updated_at"
    ordering = ("application_id", "id")
    raw_id_fields = ("application", "user")
    autocomplete_fields = ("application", "user")
    readonly_fields = ("generated_at", "validated_at", "updated_at")
