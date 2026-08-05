from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import PilotProfileForm
from .models import PilotProfile


@login_required
def dashboard(request):
    profile = PilotProfile.objects.filter(user=request.user).first()
    required_values = [
        request.user.first_name, request.user.last_name, request.user.email,
        getattr(profile, "street_address", ""), getattr(profile, "city", ""),
        getattr(profile, "state", ""), getattr(profile, "zip_code", ""),
        getattr(profile, "phone", ""), getattr(profile, "license_number", ""),
    ]
    completion_percent = round(sum(bool(str(v).strip()) for v in required_values) / len(required_values) * 100)
    return render(request, "pilot/dashboard.html", {"profile": profile, "completion_percent": completion_percent})


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    profile, _ = PilotProfile.objects.get_or_create(user=request.user, defaults={"phone": request.user.phone})
    form = PilotProfileForm(request.POST or None, instance=profile, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Pilot profile saved.")
        return redirect("pilot:dashboard")
    return render(request, "pilot/profile_form.html", {"form": form, "profile": profile})


@login_required
@require_http_methods(["GET", "POST"])
def profile_delete(request):
    profile = PilotProfile.objects.filter(user=request.user).first()
    if request.method == "POST":
        if profile:
            profile.delete()
        request.user.first_name = ""
        request.user.last_name = ""
        request.user.phone = ""
        request.user.save(update_fields=["first_name", "last_name", "phone", "updated_at"])
        messages.success(request, "Pilot profile data was deleted. Your login account remains active.")
        return redirect("pilot:dashboard")
    return render(request, "pilot/profile_confirm_delete.html", {"profile": profile})
