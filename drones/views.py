from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from .forms import DroneForm, DroneSafetyProfileForm
from .models import Drone, DroneSafetyProfile
from .services import find_best_drone_profile


def _user_drone_or_404(request, pk):
    return get_object_or_404(Drone, pk=pk, user=request.user)

@login_required
def drone_list(request):
    return render(request, "drones/drone_list.html", {"drones": Drone.objects.filter(user=request.user).select_related("safety_profile")})

@login_required
def drone_detail(request, pk):
    return render(request, "drones/drone_detail.html", {"drone": _user_drone_or_404(request, pk)})

@login_required
@require_http_methods(["GET", "POST"])
def drone_create(request):
    form = DroneForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        drone = form.save(commit=False)
        drone.user = request.user
        drone.save()
        messages.success(request, "Drone added to your inventory. Safety features were populated when a matching profile was found.")
        return redirect("drones:detail", pk=drone.pk)
    return render(request, "drones/drone_form.html", {"form": form, "drone": None})

@login_required
@require_http_methods(["GET", "POST"])
def drone_update(request, pk):
    drone = _user_drone_or_404(request, pk)
    old_certificate_name = drone.faa_certificate.name if drone.faa_certificate else ""
    form = DroneForm(request.POST or None, request.FILES or None, instance=drone)
    if request.method == "POST" and form.is_valid():
        updated_drone = form.save()
        new_certificate_name = updated_drone.faa_certificate.name if updated_drone.faa_certificate else ""
        if old_certificate_name and old_certificate_name != new_certificate_name:
            updated_drone.faa_certificate.storage.delete(old_certificate_name)
        messages.success(request, "Drone updated.")
        return redirect("drones:detail", pk=updated_drone.pk)
    return render(request, "drones/drone_form.html", {"form": form, "drone": drone})

@login_required
@require_http_methods(["GET", "POST"])
def drone_delete(request, pk):
    drone = _user_drone_or_404(request, pk)
    if request.method == "POST":
        certificate_name = drone.faa_certificate.name if drone.faa_certificate else ""
        certificate_storage = drone.faa_certificate.storage if drone.faa_certificate else None
        drone.delete()
        if certificate_name and certificate_storage:
            certificate_storage.delete(certificate_name)
        messages.success(request, "Drone deleted from your inventory.")
        return redirect("drones:list")
    return render(request, "drones/drone_confirm_delete.html", {"drone": drone})

@login_required
def faa_certificate_download(request, pk):
    drone = _user_drone_or_404(request, pk)
    if not drone.faa_certificate:
        raise Http404("FAA certificate not found.")
    try:
        certificate_file = drone.faa_certificate.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("FAA certificate not found.")
    return FileResponse(certificate_file, as_attachment=True, filename=drone.faa_certificate.name.rsplit("/", 1)[-1])

@login_required
@require_GET
def drone_profile_suggest(request):
    profile_id = (request.GET.get("profile_id") or "").strip()
    name = (request.GET.get("name") or "").strip()
    brand = (request.GET.get("brand") or "").strip() or None

    if profile_id.isdigit():
        profile = DroneSafetyProfile.objects.filter(pk=profile_id, active=True).first()
    else:
        profile = find_best_drone_profile(brand, name) if name else None

    if not profile:
        return JsonResponse({"found": False})
    return JsonResponse({
        "found": True, "id": profile.pk, "full_display_name": profile.full_display_name,
        "brand": profile.brand, "model_name": profile.model_name,
        "safety_features": profile.safety_features,
    })

@staff_member_required
def drone_safety_profile_list(request):
    sort = request.GET.get("sort", "brand")
    direction = "desc" if request.GET.get("dir") == "desc" else "asc"
    sort_map = {"brand": "brand", "model": "model_name", "display": "full_display_name", "year": "year_released", "active": "active"}
    sort_key = sort_map.get(sort, "brand")
    profiles = DroneSafetyProfile.objects.order_by(f"-{sort_key}" if direction == "desc" else sort_key)
    return render(request, "drones/drone_safety_profile_list.html", {"profiles": profiles, "sort": sort, "dir": direction})

@staff_member_required
@require_http_methods(["GET", "POST"])
def drone_safety_profile_create(request):
    form = DroneSafetyProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Drone safety profile created.")
        return redirect("drones:drone_safety_profile_list")
    return render(request, "drones/drone_safety_profile_form.html", {"form": form, "title": "Create Drone Safety Profile"})

@staff_member_required
@require_http_methods(["GET", "POST"])
def drone_safety_profile_edit(request, pk):
    profile = get_object_or_404(DroneSafetyProfile, pk=pk)
    form = DroneSafetyProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Drone safety profile updated.")
        return redirect("drones:drone_safety_profile_list")
    return render(request, "drones/drone_safety_profile_form.html", {"form": form, "title": f"Edit {profile.full_display_name}", "profile": profile})

@staff_member_required
@require_http_methods(["GET", "POST"])
def drone_safety_profile_delete(request, pk):
    profile = get_object_or_404(DroneSafetyProfile, pk=pk)
    if request.method == "POST":
        name = profile.full_display_name
        profile.delete(); messages.success(request, f"Deleted drone safety profile: {name}.")
        return redirect("drones:drone_safety_profile_list")
    return render(request, "drones/drone_safety_profile_confirm_delete.html", {"profile": profile})
