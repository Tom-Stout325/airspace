from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from pathlib import Path

from django.db.models import Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_http_methods
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.text import slugify
from django.contrib.staticfiles import finders
from django.views.generic import DeleteView, ListView
from weasyprint import HTML

from .forms import (
    OperationAircraftForm,
    OperationApprovalForm,
    OperationApprovalTrackingForm,
    OperationsPlanningForm,
)
from .models import (
    ApprovalApplication,
    ApprovalType,
    ConopsSection,
    OperationAircraft,
    OperationApproval,
    OperationsPlanning,
)
from .conops import generate_conops, save_conops_review
from .services import (
    AddressSearchError,
    find_nearest_airport,
    search_openstreetmap_address,
)


class AirspacePortalView(LoginRequiredMixin, ListView):
    model = OperationsPlanning
    template_name = "airspace/operations_portal.html"
    context_object_name = "operations"
    def get_queryset(self):
        return OperationsPlanning.objects.filter(user=self.request.user).prefetch_related("approvals")[:5]
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = OperationsPlanning.objects.filter(user=self.request.user)
        ctx.update(total_operations=qs.count(), active_operations=qs.filter(status="active").count(), draft_operations=qs.filter(status="draft").count())
        return ctx


class OperationsPlanningListView(LoginRequiredMixin, ListView):
    model = OperationsPlanning
    template_name = "airspace/operations_planning_list.html"
    context_object_name = "operations"
    def get_queryset(self):
        return OperationsPlanning.objects.filter(user=self.request.user).prefetch_related("aircraft_assignments__drone", "approvals__approval_type")


@login_required
def operations_planning_create(request):
    form = OperationsPlanningForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        operation = form.save()
        messages.success(request, "Operation plan created. Add aircraft and FAA approvals next.")
        return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(request, "airspace/operations_planning_form.html", {"form": form, "page_title": "Create operation plan"})


@login_required
def operations_planning_edit(request, pk):
    operation = get_object_or_404(OperationsPlanning, pk=pk, user=request.user)
    form = OperationsPlanningForm(request.POST or None, instance=operation, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Operation plan updated.")
        return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(request, "airspace/operations_planning_form.html", {"form": form, "operation": operation, "page_title": "Edit operation plan"})


def _approval_conops_state(approval):
    """
    Return the CONOPS state for one required FAA approval.

    ApprovalApplication is unique per approval, but the code remains
    defensive in case legacy data exists before the uniqueness constraint.
    """
    application = next(iter(approval.applications.all()), None)

    if application is None:
        return {
            "application": None,
            "exists": False,
            "complete": False,
            "complete_count": 0,
            "total_count": 0,
        }

    sections = list(application.conops_sections.all())
    total_count = len(sections)
    complete_count = sum(
        1 for section in sections if section.is_complete
    )

    return {
        "application": application,
        "exists": total_count > 0,
        "complete": (
            total_count > 0
            and complete_count == total_count
        ),
        "complete_count": complete_count,
        "total_count": total_count,
    }


def _operation_workflow_context(operation):
    approvals = list(operation.approvals.all())
    planning_complete = operation.completion_percentage == 100

    approval_states = []
    for approval in approvals:
        approval_states.append(
            {
                "approval": approval,
                "conops": _approval_conops_state(approval),
            }
        )

    all_conops_exist = bool(approval_states) and all(
        item["conops"]["exists"] for item in approval_states
    )
    all_conops_complete = bool(approval_states) and all(
        item["conops"]["complete"] for item in approval_states
    )

    submitted_statuses = {
        "submitted",
        "faa_review",
        "additional_information",
        "approved",
        "denied",
        "expired",
        "withdrawn",
    }
    any_submitted = any(
        item["approval"].status in submitted_statuses
        or bool(item["approval"].faa_tracking_number)
        or item["approval"].submitted_at is not None
        for item in approval_states
    )
    all_submitted = bool(approval_states) and all(
        item["approval"].status in submitted_statuses
        or bool(item["approval"].faa_tracking_number)
        or item["approval"].submitted_at is not None
        for item in approval_states
    )
    all_approved = bool(approval_states) and all(
        item["approval"].status == "approved"
        for item in approval_states
    )

    workflow_steps = [
        {
            "key": "planning",
            "title": "Operation Planning",
            "complete": planning_complete,
            "active": not planning_complete,
            "description": (
                "Complete the operation, pilot, location, aircraft, risk, "
                "emergency, and approval-planning sections."
            ),
        },
        {
            "key": "conops",
            "title": "CONOPS Review",
            "complete": all_conops_complete,
            "active": planning_complete and not all_conops_complete,
            "description": (
                "Generate and review a CONOPS for each required FAA "
                "waiver or approval."
            ),
        },
        {
            "key": "submission",
            "title": "FAA Submission",
            "complete": all_submitted,
            "active": all_conops_complete and not all_submitted,
            "description": (
                "Submit through FAA DroneZone, then record the submission "
                "date and FAA tracking number."
            ),
        },
        {
            "key": "approval",
            "title": "FAA Decision",
            "complete": all_approved,
            "active": any_submitted and not all_approved,
            "description": (
                "Track FAA review, respond to requests, and upload the "
                "issued approval when received."
            ),
        },
        {
            "key": "operation",
            "title": "Flight Operation",
            "complete": False,
            "active": all_approved,
            "description": (
                "Future phase: preflight readiness, flight execution, and "
                "post-flight records."
            ),
        },
    ]

    next_action = None
    next_approval = None

    if not planning_complete:
        next_action = {
            "title": "Complete Operation Planning",
            "description": (
                "Finish the items marked Needs Attention before generating "
                "FAA submission documents."
            ),
            "url_name": "airspace:operations_planning_edit",
            "url_args": [operation.pk],
            "fragment": "",
            "button_label": "Continue Planning",
            "button_class": "btn-warning",
        }
    elif not approvals:
        next_action = {
            "title": "Add the Required FAA Approval",
            "description": (
                "Planning is complete, but no FAA waiver or approval has "
                "been selected for this operation."
            ),
            "url_name": "airspace:operation_approval_add",
            "url_args": [operation.pk],
            "fragment": "",
            "button_label": "Add Waiver / Approval",
            "button_class": "btn-success",
        }
    else:
        for item in approval_states:
            if not item["conops"]["exists"]:
                next_approval = item["approval"]
                next_action = {
                    "title": "Build the CONOPS",
                    "description": (
                        "Your operation plan is complete. Generate the "
                        "CONOPS for the next required FAA approval, then "
                        "review each section before submission."
                    ),
                    "url_name": "airspace:operation_conops_review",
                    "url_args": [
                        operation.pk,
                        item["approval"].pk,
                    ],
                    "fragment": "",
                    "button_label": "Build CONOPS",
                    "button_class": "btn-success",
                }
                break

        if next_action is None:
            for item in approval_states:
                if not item["conops"]["complete"]:
                    next_approval = item["approval"]
                    next_action = {
                        "title": "Review and Complete the CONOPS",
                        "description": (
                            "A CONOPS draft exists, but one or more sections "
                            "still need review and confirmation."
                        ),
                        "url_name": "airspace:operation_conops_review",
                        "url_args": [
                            operation.pk,
                            item["approval"].pk,
                        ],
                        "fragment": "",
                        "button_label": "Review CONOPS",
                        "button_class": "btn-success",
                    }
                    break

        if next_action is None:
            for item in approval_states:
                approval = item["approval"]
                is_submitted = (
                    approval.status in submitted_statuses
                    or bool(approval.faa_tracking_number)
                    or approval.submitted_at is not None
                )
                if not is_submitted:
                    next_approval = approval
                    next_action = {
                        "title": "Submit Through FAA DroneZone",
                        "description": (
                            "Planning and CONOPS review are complete. Use the "
                            "planning PDF and reviewed CONOPS while entering "
                            "the request in FAA DroneZone. After submission, "
                            "record the FAA tracking number here."
                        ),
                        "url_name": (
                            "airspace:operation_approval_tracking"
                        ),
                        "url_args": [
                            operation.pk,
                            approval.pk,
                        ],
                        "fragment": "",
                        "button_label": "Record FAA Submission",
                        "button_class": "btn-primary",
                    }
                    break

        if next_action is None:
            for item in approval_states:
                approval = item["approval"]
                if approval.status != "approved":
                    next_approval = approval
                    next_action = {
                        "title": "Track the FAA Review",
                        "description": (
                            "The request has been submitted. Record FAA "
                            "correspondence, status changes, additional "
                            "information requests, and the final decision."
                        ),
                        "url_name": (
                            "airspace:operation_approval_tracking"
                        ),
                        "url_args": [
                            operation.pk,
                            approval.pk,
                        ],
                        "fragment": "",
                        "button_label": "Manage FAA Record",
                        "button_class": "btn-primary",
                    }
                    break

        if next_action is None:
            next_action = {
                "title": "FAA Approval Recorded",
                "description": (
                    "All required FAA approvals are recorded as approved. "
                    "Review the approval documents and special provisions "
                    "before conducting the operation."
                ),
                "url_name": "airspace:operation_planning_pdf",
                "url_args": [operation.pk],
                "fragment": "",
                "button_label": "View Planning Package",
                "button_class": "btn-success",
            }

    completed_workflow_steps = sum(
        1 for step in workflow_steps if step["complete"]
    )

    return {
        "approval_workflow_states": approval_states,
        "workflow_steps": workflow_steps,
        "completed_workflow_steps": completed_workflow_steps,
        "total_workflow_steps": len(workflow_steps),
        "planning_complete": planning_complete,
        "all_conops_complete": all_conops_complete,
        "all_submitted": all_submitted,
        "all_approved": all_approved,
        "next_action": next_action,
        "next_approval": next_approval,
    }


@login_required
def operations_planning_detail(request, pk):
    operation = get_object_or_404(
        OperationsPlanning.objects.select_related(
            "pilot_profile",
            "nearest_airport_ref",
        ).prefetch_related(
            "aircraft_assignments__drone",
            "approvals__approval_type",
            "approvals__applications__conops_sections",
        ),
        pk=pk,
        user=request.user,
    )
    completion_sections = operation.completion_sections()
    workflow_context = _operation_workflow_context(operation)

    return render(
        request,
        "airspace/operations_planning_detail.html",
        {
            "operation": operation,
            "completion_sections": completion_sections,
            **workflow_context,
        },
    )


def _choice_labels(values, choices):
    lookup = dict(choices)
    return [lookup.get(value, value) for value in (values or [])]


def _pilot_pdf_context(operation):
    profile = operation.pilot_profile

    if profile is not None:
        profile_user = getattr(profile, "user", None)
        first_name = (
            getattr(profile_user, "first_name", "") or ""
        ).strip()
        last_name = (
            getattr(profile_user, "last_name", "") or ""
        ).strip()
        profile_name = " ".join(
            part for part in (first_name, last_name) if part
        ).strip()

        pilot_name = (
            (operation.pilot_name_manual or "").strip()
            or profile_name
            or (
                getattr(profile_user, "email", "") or ""
            ).strip()
        )
        certificate_number = (
            (operation.pilot_cert_manual or "").strip()
            or (
                getattr(profile, "faa_certificate_number", "")
                or getattr(profile, "license_number", "")
                or ""
            ).strip()
        )
        pilot_email = (
            getattr(profile_user, "email", "") or ""
        ).strip()
        pilot_phone = (
            getattr(profile, "phone", "")
            or getattr(profile, "phone_number", "")
            or ""
        ).strip()
    else:
        pilot_name = (operation.pilot_name_manual or "").strip()
        certificate_number = (
            operation.pilot_cert_manual or ""
        ).strip()
        pilot_email = ""
        pilot_phone = ""

    return {
        "pilot_name": pilot_name,
        "pilot_certificate_number": certificate_number,
        "pilot_email": pilot_email,
        "pilot_phone": pilot_phone,
    }


@login_required
@require_GET
def operation_planning_pdf(request, pk):
    operation = get_object_or_404(
        OperationsPlanning.objects.select_related(
            "pilot_profile",
            "pilot_profile__user",
            "nearest_airport_ref",
            "user",
        ).prefetch_related(
            "aircraft_assignments__drone",
            "approvals__approval_type",
        ),
        pk=pk,
        user=request.user,
    )

    generated_at = timezone.localtime()
    completion_sections = operation.completion_sections()

    logo_path = finders.find("images/AirSpace_logo.png")
    logo_uri = ""
    if logo_path:
        logo_uri = Path(logo_path).resolve().as_uri()

    context = {
        "operation": operation,
        "aircraft_assignments": operation.aircraft_assignments.all(),
        "approvals": operation.approvals.all(),
        "completion_sections": completion_sections,
        "generated_at": generated_at,
        "logo_uri": logo_uri,
        "timeframe_labels": _choice_labels(
            operation.timeframe,
            OperationsPlanning.TIMEFRAME_CHOICES,
        ),
        "purpose_labels": _choice_labels(
            operation.purpose_operations,
            OperationsPlanning.PURPOSE_OPERATIONS_CHOICES,
        ),
        "ground_environment_labels": _choice_labels(
            operation.ground_environment,
            OperationsPlanning.GROUND_ENVIRONMENT_CHOICES,
        ),
        "prepared_procedure_labels": _choice_labels(
            operation.prepared_procedures,
            OperationsPlanning.PREPARED_PROCEDURES_CHOICES,
        ),
        **_pilot_pdf_context(operation),
    }

    html_string = render_to_string(
        "airspace/pdf/operation_planning_pdf.html",
        context,
        request=request,
    )

    pdf_bytes = HTML(
        string=html_string,
        base_url=request.build_absolute_uri("/"),
    ).write_pdf()

    filename_base = slugify(operation.operation_title) or "operation-plan"
    filename = f"{filename_base}-planning.pdf"

    response = HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
    )
    disposition = (
        "attachment"
        if request.GET.get("download") == "1"
        else "inline"
    )
    response["Content-Disposition"] = (
        f'{disposition}; filename="{filename}"'
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def operation_conops_review(request, operation_pk, approval_pk):
    operation = get_object_or_404(
        OperationsPlanning,
        pk=operation_pk,
        user=request.user,
    )
    approval = get_object_or_404(
        OperationApproval.objects.select_related(
            "approval_type",
            "operation",
        ),
        pk=approval_pk,
        operation=operation,
    )

    application = generate_conops(
        approval,
        request.user,
        regenerate_unlocked=False,
    )

    if request.method == "POST":
        action = request.POST.get("action", "save")

        if action == "regenerate":
            application = generate_conops(
                approval,
                request.user,
                regenerate_unlocked=True,
            )
            messages.success(
                request,
                "Unlocked CONOPS sections were regenerated from the "
                "current operation plan.",
            )
            return redirect(
                "airspace:operation_conops_review",
                operation_pk=operation.pk,
                approval_pk=approval.pk,
            )

        submitted_sections = {}
        for section in application.conops_sections.all():
            submitted_sections[section.pk] = {
                "content": request.POST.get(
                    f"content_{section.pk}",
                    "",
                ),
                "locked": (
                    request.POST.get(f"locked_{section.pk}") == "on"
                ),
                "is_complete": (
                    request.POST.get(
                        f"is_complete_{section.pk}"
                    ) == "on"
                ),
            }

        save_conops_review(application, submitted_sections)
        messages.success(request, "CONOPS review saved.")
        return redirect(
            "airspace:operation_conops_review",
            operation_pk=operation.pk,
            approval_pk=approval.pk,
        )

    sections = application.conops_sections.order_by(
        "section_key",
    )
    complete_count = sections.filter(is_complete=True).count()
    total_count = sections.count()
    review_percentage = (
        round((complete_count / total_count) * 100)
        if total_count
        else 0
    )

    return render(
        request,
        "airspace/conops_review.html",
        {
            "operation": operation,
            "approval": approval,
            "application": application,
            "sections": sections,
            "complete_count": complete_count,
            "total_count": total_count,
            "review_percentage": review_percentage,
        },
    )


class OperationsPlanningDeleteView(LoginRequiredMixin, DeleteView):
    model = OperationsPlanning
    template_name = "airspace/operations_planning_confirm_delete.html"
    success_url = reverse_lazy("airspace:operations_planning_list")
    def get_queryset(self): return OperationsPlanning.objects.filter(user=self.request.user)


@login_required
def operation_aircraft_add(request, operation_pk):
    operation = get_object_or_404(OperationsPlanning, pk=operation_pk, user=request.user)
    form = OperationAircraftForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        assignment = form.save(commit=False); assignment.operation = operation; assignment.save()
        messages.success(request, "Aircraft added to operation.")
        return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(request, "airspace/operation_child_form.html", {"form": form, "operation": operation, "page_title": "Add aircraft"})


@login_required
def operation_aircraft_edit(request, operation_pk, pk):
    operation = get_object_or_404(OperationsPlanning, pk=operation_pk, user=request.user)
    assignment = get_object_or_404(OperationAircraft, pk=pk, operation=operation)
    form = OperationAircraftForm(request.POST or None, instance=assignment, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Aircraft assignment updated.")
        return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(request, "airspace/operation_child_form.html", {"form": form, "operation": operation, "page_title": "Edit aircraft"})


@login_required
def operation_aircraft_delete(request, operation_pk, pk):
    operation = get_object_or_404(OperationsPlanning, pk=operation_pk, user=request.user)
    assignment = get_object_or_404(OperationAircraft, pk=pk, operation=operation)
    if request.method == "POST": assignment.delete(); messages.success(request, "Aircraft removed."); return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(request, "airspace/operation_child_confirm_delete.html", {"object": assignment, "operation": operation, "label": "aircraft assignment"})


def _approval_type_regulations():
    return {
        str(item.pk): {
            "regulation": item.regulation or "",
            "description": item.description or "",
        }
        for item in ApprovalType.objects.filter(active=True)
    }


@login_required
def operation_approval_add(request, operation_pk):
    operation = get_object_or_404(OperationsPlanning, pk=operation_pk, user=request.user)
    form = OperationApprovalForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        approval = form.save(commit=False); approval.operation = operation; approval.save()
        messages.success(request, "FAA approval added.")
        return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(
        request,
        "airspace/operation_approval_form.html",
        {
            "form": form,
            "operation": operation,
            "page_title": "Add FAA Waiver / Approval",
            "approval_type_regulations": _approval_type_regulations(),
        },
    )


@login_required
def operation_approval_edit(request, operation_pk, pk):
    operation = get_object_or_404(OperationsPlanning, pk=operation_pk, user=request.user)
    approval = get_object_or_404(OperationApproval, pk=pk, operation=operation)
    form = OperationApprovalForm(request.POST or None, request.FILES or None, instance=approval)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "FAA approval updated.")
        return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(
        request,
        "airspace/operation_approval_form.html",
        {
            "form": form,
            "operation": operation,
            "approval": approval,
            "page_title": "Edit FAA Waiver / Approval Planning",
            "approval_type_regulations": _approval_type_regulations(),
        },
    )


@login_required
def operation_approval_tracking(request, operation_pk, pk):
    operation = get_object_or_404(
        OperationsPlanning,
        pk=operation_pk,
        user=request.user,
    )
    approval = get_object_or_404(
        OperationApproval,
        pk=pk,
        operation=operation,
    )
    form = OperationApprovalTrackingForm(
        request.POST or None,
        request.FILES or None,
        instance=approval,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(
            request,
            "FAA approval record updated.",
        )
        return redirect(
            "airspace:operations_planning_detail",
            pk=operation.pk,
        )

    return render(
        request,
        "airspace/operation_approval_tracking_form.html",
        {
            "form": form,
            "operation": operation,
            "approval": approval,
            "page_title": "FAA Submission and Approval Record",
        },
    )


@login_required
def operation_approval_delete(request, operation_pk, pk):
    operation = get_object_or_404(OperationsPlanning, pk=operation_pk, user=request.user)
    approval = get_object_or_404(OperationApproval, pk=pk, operation=operation)
    if request.method == "POST": approval.delete(); messages.success(request, "FAA approval removed."); return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(request, "airspace/operation_child_confirm_delete.html", {"object": approval, "operation": operation, "label": "FAA approval"})


# Compatibility entry point for the old guide URL.
@login_required
def airspace_helper(request):
    return redirect("airspace:operations_planning_list")

@login_required
@require_GET
def address_search(request):
    """
    Explicit OpenStreetMap/Nominatim address search.

    The browser calls this only when the user presses Search. It is not a
    type-ahead/autocomplete endpoint.
    """
    query = " ".join((request.GET.get("q") or "").split())
    if len(query) < 3:
        return JsonResponse(
            {"results": [], "error": "Enter at least three characters."},
            status=400,
        )

    try:
        results = search_openstreetmap_address(query)
    except AddressSearchError as exc:
        return JsonResponse(
            {"results": [], "error": str(exc)},
            status=503,
        )

    return JsonResponse({"results": results})


@login_required
@require_GET
def nearest_airport_lookup(request):
    latitude = request.GET.get("lat")
    longitude = request.GET.get("lon")
    airport, distance_nm = find_nearest_airport(latitude, longitude)

    if airport is None or distance_nm is None:
        return JsonResponse(
            {"found": False, "error": "No imported airport could be located."},
            status=404,
        )

    identifier = airport.faa_identifier or airport.icao or ""
    return JsonResponse(
        {
            "found": True,
            "airport": {
                "id": airport.pk,
                "faa_identifier": airport.faa_identifier or "",
                "icao": airport.icao or "",
                "identifier": identifier,
                "name": airport.name,
                "city": airport.city,
                "state": airport.state,
                "distance_nm": str(distance_nm),
                "label": str(airport),
            },
        }
    )

