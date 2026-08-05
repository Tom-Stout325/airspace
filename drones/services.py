import re
from typing import Optional

from django.db.models import Q

from .models import DroneSafetyProfile


def normalize_drone_name(value: str | None) -> str:
    """Normalize manufacturer/model text for catalog matching."""
    value = (value or "").casefold().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def split_aliases(value: str | None) -> list[str]:
    """Support comma, semicolon, and newline separated aliases."""
    return [part.strip() for part in re.split(r"[,;\n]+", value or "") if part.strip()]


def find_best_drone_profile(brand: str | None, name: str | None) -> Optional[DroneSafetyProfile]:
    """Return the strongest active catalog match for a manufacturer/model pair."""
    brand_norm = normalize_drone_name(brand)
    name_norm = normalize_drone_name(name)
    if not name_norm:
        return None

    combined_norm = normalize_drone_name(f"{brand or ''} {name or ''}")
    queryset = DroneSafetyProfile.objects.filter(active=True).order_by('brand', 'model_name', 'pk')

    # Fast database candidates first, followed by normalized/alias matching.
    candidates = list(queryset.filter(
        Q(full_display_name__iexact=f"{(brand or '').strip()} {(name or '').strip()}".strip())
        | Q(model_name__iexact=(name or '').strip())
    ))
    if not candidates:
        candidates = list(queryset)

    best = None
    best_score = -1
    for profile in candidates:
        profile_brand = normalize_drone_name(profile.brand)
        profile_model = normalize_drone_name(profile.model_name)
        profile_display = normalize_drone_name(profile.full_display_name)
        aliases = {normalize_drone_name(alias) for alias in split_aliases(profile.aka_names)}

        score = -1
        if combined_norm and combined_norm == profile_display:
            score = 100
        elif brand_norm == profile_brand and name_norm == profile_model:
            score = 95
        elif name_norm == profile_model:
            score = 85
        elif name_norm in aliases or combined_norm in aliases:
            score = 80
        elif combined_norm and combined_norm == normalize_drone_name(f"{profile.brand} {profile.model_name}"):
            score = 75

        if score > best_score:
            best = profile
            best_score = score

    return best if best_score >= 0 else None
