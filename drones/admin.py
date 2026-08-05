from django.contrib import admin
from .models import Drone, DroneSafetyProfile

@admin.register(Drone)
class DroneAdmin(admin.ModelAdmin):
    list_display = ("manufacturer", "model", "nickname", "faa_registration_number", "status", "safety_profile", "user")
    list_filter = ("status", "manufacturer", "safety_profile__brand")
    search_fields = ("manufacturer", "model", "nickname", "serial_number", "faa_registration_number", "user__email")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("safety_profile",)

@admin.register(DroneSafetyProfile)
class DroneSafetyProfileAdmin(admin.ModelAdmin):
    list_display = ("full_display_name", "brand", "model_name", "year_released", "is_enterprise", "active")
    list_filter = ("brand", "is_enterprise", "active")
    search_fields = ("full_display_name", "brand", "model_name", "aka_names")
    ordering = ("brand", "model_name")
