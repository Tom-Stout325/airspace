from django.contrib import admin

from .models import Aircraft, PilotProfile


@admin.register(PilotProfile)
class PilotProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "license_number", "total_flight_hours", "updated_at")
    search_fields = ("user__email", "user__first_name", "user__last_name", "license_number")


@admin.register(Aircraft)
class AircraftAdmin(admin.ModelAdmin):
    list_display = ("brand", "model", "registration_number", "user", "active")
    list_filter = ("active",)
    search_fields = ("brand", "model", "registration_number", "user__email")
