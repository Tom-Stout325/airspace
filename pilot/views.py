from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import PilotProfileForm
from .models import PilotProfile


@login_required
def dashboard(request):
    profile = PilotProfile.objects.filter(user=request.user).first()

    required_values = [
        request.user.first_name,
        request.user.last_name,
        request.user.email,
        getattr(profile, "phone", ""),
        getattr(profile, "street_address", ""),
        getattr(profile, "city", ""),
        getattr(profile, "state", ""),
        getattr(profile, "zip_code", ""),
        getattr(profile, "faa_certificate_number", ""),
    ]

    completed_fields = sum(
        bool(str(value or "").strip())
        for value in required_values
    )

    print("========== PROFILE DEBUG ==========")
    for name, value in {
        "first_name": request.user.first_name,
        "last_name": request.user.last_name,
        "email": request.user.email,
        "phone": getattr(profile, "phone", ""),
        "street_address": getattr(profile, "street_address", ""),
        "city": getattr(profile, "city", ""),
        "state": getattr(profile, "state", ""),
        "zip_code": getattr(profile, "zip_code", ""),
        "faa_certificate_number": getattr(profile, "faa_certificate_number", ""),
    }.items():
        print(f"{name:20} = {repr(value)}")
    print("===================================")


    completion_percent = round(
        completed_fields / len(required_values) * 100
    )

    context = {
        "profile": profile,
        "completion_percent": completion_percent,
    }

    return render(request, "pilot/dashboard.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    profile, _ = PilotProfile.objects.get_or_create(
        user=request.user,
        defaults={"phone": request.user.phone},
    )

    form = PilotProfileForm(
        request.POST or None,
        request.FILES or None,
        instance=profile,
        user=request.user,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Pilot profile saved.")
        return redirect("pilot:dashboard")

    return render(
        request,
        "pilot/profile_form.html",
        {
            "form": form,
            "profile": profile,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def profile_delete(request):
    profile = PilotProfile.objects.filter(
        user=request.user
    ).first()

    if request.method == "POST":
        if profile:
            profile.delete()

        request.user.first_name = ""
        request.user.last_name = ""


        user_update_fields = [
            "first_name",
            "last_name",
            "phone",
        ]

        if hasattr(request.user, "updated_at"):
            user_update_fields.append("updated_at")

        request.user.save(update_fields=user_update_fields)

        messages.success(
            request,
            "Pilot profile data was deleted. "
            "Your login account remains active.",
        )
        return redirect("pilot:dashboard")

    return render(
        request,
        "pilot/profile_confirm_delete.html",
        {"profile": profile},
    )

@login_required
def logo_download(request):
    profile = PilotProfile.objects.filter(user=request.user).first()
    if not profile or not profile.logo:
        raise Http404("Logo not found.")

    try:
        logo_file = profile.logo.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Logo not found.")

    return FileResponse(logo_file)
