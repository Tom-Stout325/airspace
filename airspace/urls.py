from django.urls import path
from .views import (
    AirspacePortalView, OperationsPlanningDeleteView, OperationsPlanningListView,
    airspace_helper, operation_aircraft_add, operation_aircraft_delete,
    operation_aircraft_edit, operation_approval_add, operation_approval_delete,
    operation_approval_edit, operation_approval_tracking,
    operation_conops_review, operation_conops_pdf,
    operation_faa_package_pdf,
    operation_planning_pdf, operations_planning_create,
    operations_planning_detail,
    operations_planning_edit, address_search, nearest_airport_lookup,
)

app_name = "airspace"
urlpatterns = [
    path("api/address-search/", address_search, name="address_search"),
    path("api/nearest-airport/", nearest_airport_lookup, name="nearest_airport_lookup"),
    path("portal/", AirspacePortalView.as_view(), name="airspace_portal"),
    path("guide/", airspace_helper, name="airspace_guide"),
    path("operations/", OperationsPlanningListView.as_view(), name="operations_planning_list"),
    path("operations/new/", operations_planning_create, name="operations_planning_create"),
    path("operations/<int:pk>/", operations_planning_detail, name="operations_planning_detail"),
    path(
        "operations/<int:pk>/planning-pdf/",
        operation_planning_pdf,
        name="operation_planning_pdf",
    ),
    path("operations/<int:pk>/edit/", operations_planning_edit, name="operations_planning_edit"),
    path("operations/<int:pk>/delete/", OperationsPlanningDeleteView.as_view(), name="operations_planning_delete"),
    path("operations/<int:operation_pk>/aircraft/add/", operation_aircraft_add, name="operation_aircraft_add"),
    path("operations/<int:operation_pk>/aircraft/<int:pk>/edit/", operation_aircraft_edit, name="operation_aircraft_edit"),
    path("operations/<int:operation_pk>/aircraft/<int:pk>/delete/", operation_aircraft_delete, name="operation_aircraft_delete"),
    path("operations/<int:operation_pk>/approvals/add/", operation_approval_add, name="operation_approval_add"),
    path("operations/<int:operation_pk>/approvals/<int:pk>/edit/", operation_approval_edit, name="operation_approval_edit"),
    path(
        "operations/<int:operation_pk>/approvals/<int:approval_pk>/conops/",
        operation_conops_review,
        name="operation_conops_review",
    ),
    path(
        "operations/<int:operation_pk>/approvals/<int:approval_pk>/conops/pdf/",
        operation_conops_pdf,
        name="operation_conops_pdf",
    ),
    path(
        "operations/<int:operation_pk>/approvals/<int:approval_pk>/faa-package/pdf/",
        operation_faa_package_pdf,
        name="operation_faa_package_pdf",
    ),
    path(
        "operations/<int:operation_pk>/approvals/<int:pk>/tracking/",
        operation_approval_tracking,
        name="operation_approval_tracking",
    ),
    path("operations/<int:operation_pk>/approvals/<int:pk>/delete/", operation_approval_delete, name="operation_approval_delete"),
    # Temporary aliases so existing navbar links do not fail immediately.
    path("waiver/planning/", OperationsPlanningListView.as_view(), name="waiver_planning_list"),
    path("waiver/planning/new/", operations_planning_create, name="waiver_planning_new"),
]
