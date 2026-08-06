from django.contrib import admin

from .models import (
    ApprovalApplication,
    ApprovalType,
    Airport,
    ConopsSection,
    OperationAircraft,
    OperationApproval,
    OperationsPlanning,
)


class OperationAircraftInline(admin.TabularInline):
    model = OperationAircraft
    extra = 0
    fields = (
        "drone",
        "planned_payload",
        "registration_verified",
        "remote_id_verified",
        "preflight_airworthiness_verified",
        "current_firmware_installed",
    )


class OperationApprovalInline(admin.TabularInline):
    model = OperationApproval
    extra = 0


@admin.register(OperationsPlanning)
class OperationsPlanningAdmin(admin.ModelAdmin):
    list_display = (
        "operation_title",
        "user",
        "status",
        "start_date",
        "end_date",
        "airspace_class",
    )
    list_filter = ("status", "airspace_class", "planned_bvlos")
    search_fields = (
        "operation_title",
        "venue_name",
        "location_city",
        "user__email",
    )
    inlines = (OperationAircraftInline, OperationApprovalInline)


@admin.register(OperationAircraft)
class OperationAircraftAdmin(admin.ModelAdmin):
    list_display = (
        "operation",
        "drone",
        "registration_verified",
        "remote_id_verified",
        "preflight_airworthiness_verified",
        "current_firmware_installed",
    )
    list_filter = (
        "registration_verified",
        "remote_id_verified",
        "preflight_airworthiness_verified",
        "current_firmware_installed",
    )
    search_fields = (
        "operation__operation_title",
        "drone__manufacturer",
        "drone__model",
        "drone__nickname",
        "drone__serial_number",
    )


@admin.register(ApprovalType)
class ApprovalTypeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "regulation",
        "category",
        "active",
        "display_order",
    )
    list_filter = ("category", "active", "requires_atc_coordination")
    search_fields = ("name", "regulation", "code")


admin.site.register(Airport)
admin.site.register(OperationApproval)
admin.site.register(ApprovalApplication)
admin.site.register(ConopsSection)
