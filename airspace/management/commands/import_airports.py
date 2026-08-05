from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from django.core.management.base import BaseCommand, CommandError

from airspace.models import Airport


def to_decimal(value: str | None) -> Optional[Decimal]:
    """
    Convert a CSV string value to Decimal.
    Returns None for blank/invalid values.
    """
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


class Command(BaseCommand):
    help = "Import FAA NASR APT_BASE.csv airport records into the Airport model."

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to APT_BASE.csv (e.g. airspace/data/APT_BASE.csv).",
        )
        parser.add_argument(
            "--inactive",
            action="store_true",
            help="Also import non-active airports (default: only active/open).",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_file"]).expanduser().resolve()

        if not csv_path.exists():
            raise CommandError(f"File not found: {csv_path}")

        include_inactive = bool(options["inactive"])

        created = 0
        updated = 0
        skipped = 0
        missing_icao = 0
        missing_coords = 0
        filtered_inactive = 0

        # utf-8-sig handles BOM if present in FAA CSVs
        with csv_path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            # Validate required columns exist in this CSV
            required_cols = {"ICAO_ID", "ARPT_NAME", "LAT_DECIMAL", "LONG_DECIMAL", "CITY", "STATE_CODE"}
            fieldnames = set(reader.fieldnames or [])
            missing_cols = required_cols - fieldnames
            if missing_cols:
                raise CommandError(
                    "APT_BASE.csv is missing required columns: "
                    + ", ".join(sorted(missing_cols))
                )

            for row in reader:
                icao = (row.get("ICAO_ID") or "").strip().upper()
                if not icao:
                    missing_icao += 1
                    skipped += 1
                    continue

                name = (row.get("ARPT_NAME") or "").strip()
                lat = to_decimal(row.get("LAT_DECIMAL"))
                lon = to_decimal(row.get("LONG_DECIMAL"))

                if not name or lat is None or lon is None:
                    missing_coords += 1
                    skipped += 1
                    continue

                # Optional: filter out closed/inactive airports by ARPT_STATUS when present
                status = (row.get("ARPT_STATUS") or "").strip().upper()
                if status and not include_inactive:
                    # Keep this conservative: skip only clearly closed
                    if status in {"CLSD", "CLOSED"}:
                        filtered_inactive += 1
                        skipped += 1
                        continue

                city = (row.get("CITY") or "").strip()
                state = (row.get("STATE_CODE") or "").strip()

                obj, was_created = Airport.objects.update_or_create(
                    icao=icao,
                    defaults={
                        "name": name,
                        "latitude": lat,
                        "longitude": lon,
                        "street_address": "",   # NASR APT_BASE doesn't provide street reliably
                        "city": city,
                        "state": state,
                        "zip_code": "",         # same as above
                        "active": True,
                    },
                )

                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Airport import complete. "
                f"Created: {created}, Updated: {updated}, Skipped: {skipped} "
                f"(missing ICAO: {missing_icao}, missing name/coords: {missing_coords}, "
                f"filtered closed: {filtered_inactive})"
            )
        )
