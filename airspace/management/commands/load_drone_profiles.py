import csv
from pathlib import Path
from collections import defaultdict



def run():
    # Path to your CSV (same folder as manage.py)
    csv_path = Path("drone_safety_features.csv")

    if not csv_path.exists():
        print(f"CSV not found at {csv_path!s}")
        return

    rows = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Skip completely empty separator rows
            if not (r["make"] or r["model"]):
                continue
            rows.append(r)

    print(f"Loaded {len(rows)} rows from CSV.")

    # Group rows by (make, model, year)
    groups = defaultdict(list)
    for r in rows:
        key = (r["make"].strip(), r["model"].strip(), r["year"].strip())
        groups[key].append(r)

    print(f"Found {len(groups)} unique aircraft (make+model+year).")

    created = 0
    updated = 0

    for (make, model_name, year), group_rows in groups.items():
        bullets = []
        for r in group_rows:
            feature = (r["safety_feature"] or "").strip()
            desc = (r["description"] or "").strip()

            if feature and desc:
                bullets.append(f"• {feature} – {desc}")
            elif feature:
                bullets.append(f"• {feature}")
            elif desc:
                bullets.append(f"• {desc}")

        safety_text = "\n".join(bullets)
        year_int = int(year) if year else None
        full_name = f"{make} {model_name}"

        obj, is_created = DroneSafetyProfile.objects.update_or_create(
            brand=make,
            model_name=model_name,
            defaults={
                "full_display_name": full_name,
                "aka_names": model_name,
                "year_released": year_int,
                "safety_features": safety_text,
                "active": True,
            },
        )

        if is_created:
            created += 1
            action = "CREATED"
        else:
            updated += 1
            action = "UPDATED"

        print(f"{action}: {full_name} ({year})")

    print(f"\nDone. Created {created}, updated {updated}.")
    print("Total DroneSafetyProfile objects:", DroneSafetyProfile.objects.count())


if __name__ == "__main__":
    # When run through `python manage.py shell < load_drone_profiles.py`
    run()

