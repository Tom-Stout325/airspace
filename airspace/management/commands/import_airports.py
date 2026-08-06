from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from airspace.models import Airport


def to_decimal(value: str | None) -> Optional[Decimal]:
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
    help = (
        "Import or update FAA NASR APT_BASE.csv records in the Airport table."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            nargs="?",
            default="airspace/data/APT_BASE.csv",
            help=(
                "Path to APT_BASE.csv. Defaults to "
                "airspace/data/APT_BASE.csv."
            ),
        )
        parser.add_argument(
            "--inactive",
            action="store_true",
            help="Also import clearly closed facilities.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        csv_path = Path(options["csv_file"]).expanduser().resolve()
        if not csv_path.exists():
            raise CommandError(f"File not found: {csv_path}")

        include_inactive = bool(options["inactive"])
        created = updated = skipped = filtered_inactive = 0

        with csv_path.open(newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            required_columns = {
                "ARPT_ID",
                "ARPT_NAME",
                "LAT_DECIMAL",
                "LONG_DECIMAL",
                "CITY",
                "STATE_CODE",
                "ICAO_ID",
            }
            missing_columns = required_columns - set(reader.fieldnames or [])
            if missing_columns:
                raise CommandError(
                    "APT_BASE.csv is missing required columns: "
                    + ", ".join(sorted(missing_columns))
                )

            for row in reader:
                faa_identifier = (row.get("ARPT_ID") or "").strip().upper()
                icao = (row.get("ICAO_ID") or "").strip().upper() or None
                name = (row.get("ARPT_NAME") or "").strip()
                latitude = to_decimal(row.get("LAT_DECIMAL"))
                longitude = to_decimal(row.get("LONG_DECIMAL"))

                if (
                    not faa_identifier
                    or not name
                    or latitude is None
                    or longitude is None
                ):
                    skipped += 1
                    continue

                status = (row.get("ARPT_STATUS") or "").strip().upper()
                is_closed = status in {"CLSD", "CLOSED"}
                if is_closed and not include_inactive:
                    filtered_inactive += 1
                    skipped += 1
                    continue

                defaults = {
                    "icao": icao,
                    "name": name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "street_address": "",
                    "city": (row.get("CITY") or "").strip(),
                    "state": (row.get("STATE_CODE") or "").strip(),
                    "zip_code": "",
                    "active": not is_closed,
                }

                # Reuse an older ICAO-only row when possible, then populate
                # its FAA identifier instead of creating a duplicate.
                existing = None
                if icao:
                    existing = Airport.objects.filter(
                        icao=icao,
                        faa_identifier__isnull=True,
                    ).first()

                if existing:
                    for field, value in defaults.items():
                        setattr(existing, field, value)
                    existing.faa_identifier = faa_identifier
                    existing.save()
                    updated += 1
                    continue

                _, was_created = Airport.objects.update_or_create(
                    faa_identifier=faa_identifier,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Airport import complete. "
                f"Created: {created}, Updated: {updated}, "
                f"Skipped: {skipped}, Closed filtered: {filtered_inactive}."
            )
        )
