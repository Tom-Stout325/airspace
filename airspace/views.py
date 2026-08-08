from django.contrib import messages
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
import base64
from html import escape
from io import BytesIO
import mimetypes
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
from pypdf import PdfReader, PdfWriter
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
from .conops import (
    ordered_conops_sections,
    CONOPS_DEFINITIONS,
    get_or_create_application,
    save_conops_review,
)
from .ai_conops import (
    OpenAIConopsError,
    generate_ai_conops,
    latest_conops_source_updated_at,
    openai_is_configured,
)
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
    form = OperationsPlanningForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        operation = form.save()
        messages.success(request, "Operation plan created. Add aircraft and FAA approvals next.")
        return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(request, "airspace/operations_planning_form.html", {"form": form, "page_title": "Create operation plan"})


@login_required
def operations_planning_edit(request, pk):
    operation = get_object_or_404(
        OperationsPlanning,
        pk=pk,
        user=request.user,
    )
    form = OperationsPlanningForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        instance=operation,
        user=request.user,
    )

    if request.method == "POST" and form.is_valid():
        planning_changed = form.has_changed()
        operation = form.save()

        if planning_changed:
            _invalidate_operation_conops(operation)

        messages.success(request, "Operation plan updated.")
        return redirect(
            "airspace:operations_planning_detail",
            pk=operation.pk,
        )

    return render(
        request,
        "airspace/operations_planning_form.html",
        {
            "form": form,
            "operation": operation,
            "page_title": "Edit operation plan",
        },
    )


def _invalidate_operation_conops(operation):
    """
    Mark existing generated CONOPS packages stale after planning-source
    changes without deleting the previous reviewed text.
    """
    for approval in operation.approvals.all():
        for application in approval.applications.all():
            application.conops_source_updated_at = None
            application.description_is_complete = False
            application.description_validated_at = None
            application.save(
                update_fields=[
                    "conops_source_updated_at",
                    "description_is_complete",
                    "description_validated_at",
                    "updated_at",
                ]
            )
            application.conops_sections.update(
                is_complete=False,
                validated_at=None,
            )


def _approval_conops_state(approval):
    """
    Return the AI CONOPS workflow state for one FAA approval.

    Existing sections alone are never enough to advance to FAA submission.
    The current package must have been generated by the AI engine, must
    contain the current section set and Description of Operations, must not
    be stale, and must be fully reviewed.
    """
    application = next(
        iter(approval.applications.all()),
        None,
    )

    if application is None:
        return {
            "application": None,
            "exists": False,
            "generated": False,
            "stale": False,
            "complete": False,
            "complete_count": 0,
            "total_count": 0,
        }

    sections = list(application.conops_sections.all())
    total_count = len(sections) + 1
    complete_count = int(application.description_is_complete) + sum(
        1
        for section in sections
        if section.is_complete
    )

    from .conops import CONOPS_DEFINITIONS

    expected_keys = {
        definition.key
        for definition in CONOPS_DEFINITIONS
    }
    actual_keys = {
        section.section_key
        for section in sections
    }

    generated = bool(
        application.ai_generated_at
        and application.ai_generation_model
        and (application.description or "").strip()
        and actual_keys == expected_keys
    )

    latest_source = latest_conops_source_updated_at(
        approval
    )

    stale = bool(
        generated
        and (
            application.conops_source_updated_at is None
            or (
                latest_source is not None
                and latest_source
                > application.conops_source_updated_at
            )
        )
    )

    complete = bool(
        generated
        and not stale
        and total_count > 0
        and complete_count == total_count
    )

    return {
        "application": application,
        "exists": generated,
        "generated": generated,
        "stale": stale,
        "complete": complete,
        "complete_count": complete_count,
        "total_count": total_count,
    }


def _approval_is_submitted(approval):
    submitted_statuses = {
        "submitted",
        "faa_review",
        "additional_information",
        "approved",
        "denied",
        "expired",
        "withdrawn",
    }
    return bool(
        approval.status in submitted_statuses
        or approval.faa_tracking_number
        or approval.submitted_at
    )


def _submission_workflow_steps(
    *, planning_complete, conops_generated, conops_stale,
    review_complete, submitted
):
    generated_current = bool(conops_generated and not conops_stale)
    states = [
        ("Complete Planning Documents", planning_complete),
        ("Generate CONOPS", generated_current),
        ("Review & Approve CONOPS", review_complete),
        ("Submit Application", submitted),
    ]
    current_assigned = False
    steps = []
    for title, complete in states:
        current = bool(not complete and not current_assigned)
        current_assigned = current_assigned or current
        steps.append(
            {
                "title": title,
                "complete": bool(complete),
                "current": current,
            }
        )
    return steps


def _operation_workflow_context(operation):
    approvals = list(operation.approvals.all())
    planning_complete = (
        operation.completion_percentage == 100
    )

    approval_states = [
        {
            "approval": approval,
            "conops": _approval_conops_state(approval),
        }
        for approval in approvals
    ]

    all_conops_complete = (
        bool(approval_states)
        and all(
            item["conops"]["complete"]
            for item in approval_states
        )
    )
    any_conops_stale = any(
        item["conops"]["stale"]
        for item in approval_states
    )

    any_submitted = any(
        _approval_is_submitted(item["approval"])
        for item in approval_states
    )
    all_submitted = (
        bool(approval_states)
        and all(
            _approval_is_submitted(item["approval"])
            for item in approval_states
        )
    )
    all_approved = (
        bool(approval_states)
        and all(
            item["approval"].status == "approved"
            for item in approval_states
        )
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
            "active": (
                planning_complete
                and not all_conops_complete
            ),
            "description": (
                "Generate and review the Description of Operations and "
                "CONOPS for each required FAA waiver or approval."
            ),
        },
        {
            "key": "submission",
            "title": "FAA Submission",
            "complete": all_submitted,
            "active": (
                all_conops_complete
                and not all_submitted
            ),
            "description": (
                "Submit through the applicable FAA system, then record the "
                "submission date and FAA tracking number."
            ),
        },
        {
            "key": "approval",
            "title": "FAA Decision",
            "complete": all_approved,
            "active": (
                any_submitted
                and not all_approved
            ),
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
            "url_name": (
                "airspace:operations_planning_edit"
            ),
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
        # Stale always takes priority over FAA submission.
        for item in approval_states:
            if item["conops"]["stale"]:
                next_approval = item["approval"]
                next_action = {
                    "title": (
                        "Planning Changed — Regenerate CONOPS"
                    ),
                    "description": (
                        "The planning record changed after the current "
                        "Description of Operations and CONOPS were generated. "
                        "Generate a new version from the updated planning "
                        "record, then review it again before FAA submission."
                    ),
                    "url_name": (
                        "airspace:operation_conops_review"
                    ),
                    "url_args": [
                        operation.pk,
                        item["approval"].pk,
                    ],
                    "fragment": "",
                    "button_label": "Regenerate CONOPS",
                    "button_class": "btn-warning",
                }
                break

        # No AI-generated package yet.
        if next_action is None:
            for item in approval_states:
                if not item["conops"]["generated"]:
                    next_approval = item["approval"]
                    next_action = {
                        "title": "Build the CONOPS",
                        "description": (
                            "Your operation plan is complete. Generate the "
                            "Description of Operations and full CONOPS with "
                            "ChatGPT, then review every section."
                        ),
                        "url_name": (
                            "airspace:operation_conops_review"
                        ),
                        "url_args": [
                            operation.pk,
                            item["approval"].pk,
                        ],
                        "fragment": "",
                        "button_label": "Build CONOPS",
                        "button_class": "btn-success",
                    }
                    break

        # AI package exists but has not been fully reviewed.
        if next_action is None:
            for item in approval_states:
                if not item["conops"]["complete"]:
                    next_approval = item["approval"]
                    next_action = {
                        "title": (
                            "Review and Complete the CONOPS"
                        ),
                        "description": (
                            "ChatGPT generated the current Description of "
                            "Operations and CONOPS, but one or more sections "
                            "still need RPIC review and confirmation."
                        ),
                        "url_name": (
                            "airspace:operation_conops_review"
                        ),
                        "url_args": [
                            operation.pk,
                            item["approval"].pk,
                        ],
                        "fragment": "",
                        "button_label": "Review CONOPS",
                        "button_class": "btn-success",
                    }
                    break

        # Only a current and fully reviewed package may advance here.
        if next_action is None:
            for item in approval_states:
                approval = item["approval"]
                if not _approval_is_submitted(approval):
                    next_approval = approval
                    next_action = {
                        "title": (
                            "Submit Through FAA DroneZone"
                        ),
                        "description": (
                            "Planning and CONOPS review are complete. Use "
                            "the reviewed Description of Operations, CONOPS, "
                            "and planning PDF while completing the FAA "
                            "application. Record the FAA tracking number "
                            "after submission."
                        ),
                        "url_name": (
                            "airspace:operation_approval_tracking"
                        ),
                        "url_args": [
                            operation.pk,
                            approval.pk,
                        ],
                        "fragment": "",
                        "button_label": (
                            "Record FAA Submission"
                        ),
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
                "url_name": (
                    "airspace:operation_planning_pdf"
                ),
                "url_args": [operation.pk],
                "fragment": "",
                "button_label": "View Planning Package",
                "button_class": "btn-success",
            }

    completed_workflow_steps = sum(
        1
        for step in workflow_steps
        if step["complete"]
    )

    all_conops_generated = bool(approval_states) and all(
        item["conops"]["generated"]
        for item in approval_states
    )
    submission_workflow_steps = _submission_workflow_steps(
        planning_complete=planning_complete,
        conops_generated=all_conops_generated,
        conops_stale=any_conops_stale,
        review_complete=all_conops_complete,
        submitted=all_submitted,
    )

    return {
        "approval_workflow_states": approval_states,
        "workflow_steps": workflow_steps,
        "completed_workflow_steps": (
            completed_workflow_steps
        ),
        "total_workflow_steps": len(workflow_steps),
        "planning_complete": planning_complete,
        "all_conops_complete": all_conops_complete,
        "any_conops_stale": any_conops_stale,
        "all_submitted": all_submitted,
        "all_approved": all_approved,
        "next_action": next_action,
        "next_approval": next_approval,
        "submission_workflow_steps": submission_workflow_steps,
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

    logo_path = finders.find("images/AirSpace_Logo.png")
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
    application = get_or_create_application(
        approval,
        request.user,
    )

    if request.method == "POST":
        action = request.POST.get("action", "save")

        description_text = request.POST.get(
            "description",
            application.description,
        ).strip()
        description_changed = (
            description_text != application.description
        )
        locked_description = (
            request.POST.get("locked_description") == "on"
            or description_changed
        )
        description_is_complete = bool(
            request.POST.get("description_is_complete") == "on"
            and (
                not description_changed
                or not application.description_is_complete
            )
        )
        description_updates = []
        if description_changed:
            application.description = description_text
            description_updates.append("description")
        if locked_description != application.locked_description:
            application.locked_description = locked_description
            description_updates.append("locked_description")
        if description_is_complete != application.description_is_complete:
            application.description_is_complete = description_is_complete
            application.description_validated_at = (
                timezone.now() if description_is_complete else None
            )
            description_updates.extend(
                ["description_is_complete", "description_validated_at"]
            )
        if description_updates:
            application.save(
                update_fields=description_updates + ["updated_at"]
            )

        submitted_sections = {}
        for section in application.conops_sections.all():
            submitted_sections[section.pk] = {
                "content": request.POST.get(
                    f"content_{section.pk}",
                    section.content,
                ),
                "locked": (
                    request.POST.get(
                        f"locked_{section.pk}"
                    ) == "on"
                ),
                "is_complete": (
                    request.POST.get(
                        f"is_complete_{section.pk}"
                    ) == "on"
                ),
            }

        if submitted_sections:
            save_conops_review(
                application,
                submitted_sections,
            )

        if action == "generate_ai":
            try:
                generate_ai_conops(
                    approval,
                    request.user,
                    regenerate_unlocked=True,
                )
            except OpenAIConopsError as exc:
                messages.error(
                    request,
                    "CONOPS generation failed. The existing Description of "
                    "Operations and CONOPS sections were not replaced. "
                    f"{exc}",
                )
            else:
                messages.success(
                    request,
                    "ChatGPT generated the Description of Operations "
                    "and refreshed all unprotected CONOPS sections.",
                )

            return redirect(
                "airspace:operation_conops_review",
                operation_pk=operation.pk,
                approval_pk=approval.pk,
            )

        messages.success(request, "CONOPS review saved.")
        return redirect(
            "airspace:operation_conops_review",
            operation_pk=operation.pk,
            approval_pk=approval.pk,
        )

    sections = ordered_conops_sections(application)
    complete_count = int(application.description_is_complete) + sum(
        1 for section in sections if section.is_complete
    )
    total_count = len(sections) + 1
    review_percentage = (
        round((complete_count / total_count) * 100)
        if total_count
        else 0
    )
    conops_state = _approval_conops_state(approval)
    submission_workflow_steps = _submission_workflow_steps(
        planning_complete=(operation.completion_percentage == 100),
        conops_generated=conops_state["generated"],
        conops_stale=conops_state["stale"],
        review_complete=conops_state["complete"],
        submitted=_approval_is_submitted(approval),
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
            "review_ready": conops_state["complete"],
            "submission_workflow_steps": submission_workflow_steps,
            "openai_configured": openai_is_configured(),
            "conops_is_stale": conops_state["stale"],
        },
    )


# AIRSPACE_DRONEZONE_APPLICATION_WORKSHEET_V1
def _decimal_coordinate_to_dms(value, positive, negative):
    if value is None:
        return None

    from decimal import Decimal, ROUND_HALF_UP

    coordinate = Decimal(str(value))
    direction = positive if coordinate >= 0 else negative
    coordinate = abs(coordinate)

    degrees = int(coordinate)
    minute_value = (coordinate - Decimal(degrees)) * Decimal("60")
    minutes = int(minute_value)
    seconds = (
        (minute_value - Decimal(minutes)) * Decimal("60")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if seconds == Decimal("60.00"):
        seconds = Decimal("0.00")
        minutes += 1
    if minutes == 60:
        minutes = 0
        degrees += 1

    return {
        "degrees": degrees,
        "minutes": minutes,
        "seconds": seconds,
        "direction": direction,
    }


def _display_model_choice(instance, field_name):
    display_method = getattr(instance, f"get_{field_name}_display", None)
    if callable(display_method):
        return display_method()
    return getattr(instance, field_name, "") or ""


def _operation_timezone_display(operation):
    labels = {
        "SST": "Samoa Time",
        "HAST": "Hawaii-Aleutian Time",
        "AKST": "Alaska Time (AT)",
        "PST": "Pacific Time (PT)",
        "MST": "Mountain Time (MT)",
        "CST": "Central Time (CT)",
        "EST": "Eastern Time (ET)",
        "AST": "Atlantic Time (AT)",
        "CHST": "Chamorro Time (ChST)",
    }
    value = operation.local_time_zone or ""
    return labels.get(value, _display_model_choice(operation, "local_time_zone"))


def _operation_map_data(operation):
    field = operation.operation_map
    if not field:
        return {"available": False, "is_pdf": False, "image_uri": "", "bytes": b""}

    field.open("rb")
    try:
        content = field.read()
    finally:
        field.close()

    suffix = Path(field.name or "").suffix.lower()
    if suffix == ".pdf":
        return {"available": True, "is_pdf": True, "image_uri": "", "bytes": content}

    mime_type = mimetypes.guess_type(field.name or "")[0] or "application/octet-stream"
    image_uri = (
        f"data:{mime_type};base64,"
        f"{base64.b64encode(content).decode('ascii')}"
    )
    return {"available": True, "is_pdf": False, "image_uri": image_uri, "bytes": content}


def _conops_page_overlay(*, page_number, total_pages, title, appendix=False):
    appendix_label = (
        '<div class="appendix">Appendix A — Operations Area Map</div>'
        if appendix
        else ""
    )
    html = f"""
        <style>
          @page {{ size: Letter; margin: 0; }}
          body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; }}
          .appendix {{
            position: fixed; top: .18in; left: .22in;
            padding: 4px 7px; background: white; color: SteelBlue;
            border: 1px solid SteelBlue; font-size: 10pt; font-weight: bold;
          }}
          .footer {{
            position: fixed; right: .25in; bottom: .18in; left: .25in;
            display: flex; justify-content: space-between;
            color: #667; font-size: 8pt;
          }}
        </style>
        {appendix_label}
        <div class="footer">
          <span>AirSpace CONOPS</span>
          <span>{escape(title)}</span>
          <span>Page {page_number} of {total_pages}</span>
        </div>
    """
    return HTML(string=html).write_pdf()


def _finalize_conops_pdf(document_pdf, *, title, map_pdf=b""):
    writer = PdfWriter()
    writer.append(BytesIO(document_pdf))
    first_map_page = len(writer.pages) if map_pdf else None
    if map_pdf:
        writer.append(BytesIO(map_pdf))

    total_pages = len(writer.pages)
    for index, page in enumerate(writer.pages):
        overlay_pdf = _conops_page_overlay(
            page_number=index + 1,
            total_pages=total_pages,
            title=title,
            appendix=(index == first_map_page),
        )
        overlay_page = PdfReader(BytesIO(overlay_pdf)).pages[0]
        overlay_page.scale_to(
            float(page.mediabox.width),
            float(page.mediabox.height),
        )
        page.merge_page(overlay_page)

    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _relevant_existing_waivers(user, current_approval):
    candidates = (
        OperationApproval.objects
        .filter(operation__user=user)
        .exclude(pk=current_approval.pk)
        .select_related("approval_type", "operation")
        .order_by("-updated_at")
    )

    relevant_statuses = {
        "submitted",
        "faa_review",
        "additional_information",
        "approved",
    }

    return [
        item
        for item in candidates
        if (
            item.status in relevant_statuses
            or bool(item.faa_tracking_number)
            or bool(item.approval_number)
        )
    ]


@login_required
@require_GET
def operation_application_worksheet_pdf(request, operation_pk, approval_pk):
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
    application = get_object_or_404(
        ApprovalApplication,
        approval=approval,
        user=request.user,
    )

    saved_sections = {
        section.section_key: section
        for section in application.conops_sections.all()
    }
    sections = [
        saved_sections[definition.key]
        for definition in CONOPS_DEFINITIONS
        if definition.key in saved_sections
    ]

    if not application.description or not sections:
        messages.warning(
            request,
            "Generate the Description of Operations before creating the application worksheet.",
        )
        return redirect(
            "airspace:operation_conops_review",
            operation_pk=operation.pk,
            approval_pk=approval.pk,
        )

    expected_keys = {definition.key for definition in CONOPS_DEFINITIONS}
    actual_keys = set(saved_sections)
    conops_generated = bool(
        application.ai_generated_at
        and application.ai_generation_model
        and actual_keys == expected_keys
    )

    conops_stale = False
    if conops_generated and hasattr(application, "conops_source_updated_at"):
        source_timestamp = application.conops_source_updated_at
        if source_timestamp is None:
            conops_stale = True
        else:
            try:
                from .ai_conops import latest_conops_source_updated_at
                latest_source = latest_conops_source_updated_at(approval)
            except ImportError:
                latest_source = None
            conops_stale = bool(
                latest_source is not None and latest_source > source_timestamp
            )

    all_sections_complete = bool(
        application.description_is_complete
        and sections
        and all(section.is_complete for section in sections)
    )
    package_ready = bool(
        conops_generated and not conops_stale and all_sections_complete
    )

    timeframe_options = [
        {
            "value": value,
            "label": label,
            "checked": value in (operation.timeframe or []),
        }
        for value, label in OperationsPlanning.TIMEFRAME_CHOICES
    ]

    latitude_dms = _decimal_coordinate_to_dms(operation.location_latitude, "N", "S")
    longitude_dms = _decimal_coordinate_to_dms(operation.location_longitude, "E", "W")
    relevant_waivers = _relevant_existing_waivers(request.user, approval)
    pilot_context = _pilot_pdf_context(operation)

    responsible_party = (
        pilot_context["pilot_name"]
        or f"{request.user.first_name} {request.user.last_name}".strip()
        or request.user.email
    )

    nearest_airport = operation.nearest_airport_ref
    if nearest_airport:
        nearest_airport_label = " / ".join(
            value
            for value in [
                nearest_airport.faa_identifier,
                nearest_airport.icao,
                nearest_airport.name,
            ]
            if value
        )
    else:
        nearest_airport_label = operation.nearest_airport or ""

    logo_path = finders.find("images/AirSpace_Logo.png")
    if not logo_path:
        logo_path = finders.find("images/airspace-logo.png")
    logo_uri = Path(logo_path).resolve().as_uri() if logo_path else ""

    context = {
        "operation": operation,
        "approval": approval,
        "application": application,
        "sections": sections,
        "aircraft_assignments": operation.aircraft_assignments.all(),
        "generated_at": timezone.localtime(),
        "logo_uri": logo_uri,
        "package_ready": package_ready,
        "conops_generated": conops_generated,
        "conops_stale": conops_stale,
        "all_sections_complete": all_sections_complete,
        "responsible_party": responsible_party,
        "timeframe_options": timeframe_options,
        "frequency_display": _display_model_choice(operation, "frequency"),
        "local_time_zone_display": _operation_timezone_display(operation),
        "dronezone_radius_display": _display_model_choice(operation, "dronezone_radius"),
        "airspace_class_display": _display_model_choice(operation, "airspace_class"),
        "latitude_dms": latitude_dms,
        "longitude_dms": longitude_dms,
        "nearest_airport_label": nearest_airport_label,
        "relevant_waivers": relevant_waivers,
        "has_relevant_waivers": bool(relevant_waivers),
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
        **pilot_context,
    }

    html_string = render_to_string(
        "airspace/pdf/application_worksheet.html",
        context,
        request=request,
    )
    pdf_bytes = HTML(
        string=html_string,
        base_url=request.build_absolute_uri("/"),
    ).write_pdf()

    filename = (
        f"{slugify(operation.operation_title) or 'operation'}"
        "-dronezone-application-worksheet.pdf"
    )
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    disposition = "attachment" if request.GET.get("download") == "1" else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def operation_conops_pdf(request, operation_pk, approval_pk):
    operation = get_object_or_404(
        OperationsPlanning.objects.select_related("user"),
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
    application = get_object_or_404(
        ApprovalApplication,
        approval=approval,
        user=request.user,
    )
    sections = ordered_conops_sections(application)

    if not application.description and not sections:
        messages.warning(
            request,
            "Generate the CONOPS before opening the PDF.",
        )
        return redirect(
            "airspace:operation_conops_review",
            operation_pk=operation.pk,
            approval_pk=approval.pk,
        )

    logo_path = finders.find("images/AirSpace_Logo.png")
    if not logo_path:
        logo_path = finders.find("images/airspace-logo.png")
    logo_uri = (
        Path(logo_path).resolve().as_uri()
        if logo_path
        else ""
    )
    operation_map = _operation_map_data(operation)

    html_string = render_to_string(
        "airspace/pdf/conops_pdf.html",
        {
            "operation": operation,
            "approval": approval,
            "application": application,
            "sections": sections,
            "generated_at": timezone.localtime(),
            "logo_uri": logo_uri,
            "all_sections_complete": bool(
                application.description_is_complete
                and sections
                and all(
                    section.is_complete
                    for section in sections
                )
            ),
            "operation_map_available": operation_map["available"],
            "operation_map_is_pdf": operation_map["is_pdf"],
            "operation_map_image_uri": operation_map["image_uri"],
        },
        request=request,
    )

    pdf_bytes = HTML(
        string=html_string,
        base_url=request.build_absolute_uri("/"),
    ).write_pdf()
    pdf_bytes = _finalize_conops_pdf(
        pdf_bytes,
        title=operation.operation_title,
        map_pdf=(operation_map["bytes"] if operation_map["is_pdf"] else b""),
    )

    filename = (
        f"{slugify(operation.operation_title) or 'operation'}"
        "-conops.pdf"
    )
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
        assignment = form.save(commit=False)
        assignment.operation = operation
        assignment.save()
        _invalidate_operation_conops(operation)
        messages.success(request, "Aircraft added to operation.")
        return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(request, "airspace/operation_child_form.html", {"form": form, "operation": operation, "page_title": "Add aircraft"})


@login_required
def operation_aircraft_edit(request, operation_pk, pk):
    operation = get_object_or_404(OperationsPlanning, pk=operation_pk, user=request.user)
    assignment = get_object_or_404(OperationAircraft, pk=pk, operation=operation)
    form = OperationAircraftForm(request.POST or None, instance=assignment, user=request.user)
    if request.method == "POST" and form.is_valid():
        assignment_changed = form.has_changed()
        form.save()
        if assignment_changed:
            _invalidate_operation_conops(operation)
        messages.success(request, "Aircraft assignment updated.")
        return redirect("airspace:operations_planning_detail", pk=operation.pk)
    return render(request, "airspace/operation_child_form.html", {"form": form, "operation": operation, "page_title": "Edit aircraft"})


@login_required
def operation_aircraft_delete(request, operation_pk, pk):
    operation = get_object_or_404(OperationsPlanning, pk=operation_pk, user=request.user)
    assignment = get_object_or_404(OperationAircraft, pk=pk, operation=operation)
    if request.method == "POST":
        assignment.delete()
        _invalidate_operation_conops(operation)
        messages.success(request, "Aircraft removed.")
        return redirect(
            "airspace:operations_planning_detail",
            pk=operation.pk,
        )
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
        approval = form.save(commit=False)
        approval.operation = operation
        approval.save()
        _invalidate_operation_conops(operation)
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
        approval_changed = form.has_changed()
        form.save()
        if approval_changed:
            _invalidate_operation_conops(operation)
        messages.success(request, "FAA approval updated.")
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
