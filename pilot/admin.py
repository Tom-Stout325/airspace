from django.contrib import admin

from .models import PilotProfile


@admin.register(PilotProfile)
class PilotProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "faa_certificate_number", "total_flight_hours", "updated_at")
    search_fields = ("user__email", "user__first_name", "user__last_name", "faa_certificate_number")

