from pathlib import Path

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

from .validators import validate_faa_certificate_size


def faa_certificate_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"drone_certificates/{instance.user_id}/{instance.pk or 'new'}/faa_certificate{extension}"


class DroneSafetyProfile(models.Model):
    BRAND_CHOICES = [
        ("DJI", "DJI"),
        ("DJI Enterprise", "DJI Enterprise"),
        ("Autel", "Autel"),
        ("Skydio", "Skydio"),
        ("Other", "Other"),
    ]

    brand = models.CharField(max_length=50, choices=BRAND_CHOICES, default="DJI")
    model_name = models.CharField(max_length=100)
    full_display_name = models.CharField(max_length=150, unique=True)
    year_released = models.PositiveSmallIntegerField(null=True, blank=True)
    is_enterprise = models.BooleanField(default=False)
    safety_features = models.TextField()
    aka_names = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["brand", "model_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "model_name"],
                name="uniq_dronesafetyprofile_brand_model",
            ),
        ]
        verbose_name = "Drone Safety Profile"
        verbose_name_plural = "Drone Safety Profiles"

    def __str__(self):
        return self.full_display_name or f"{self.brand} {self.model_name}"


class Drone(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        MAINTENANCE = "maintenance", "Maintenance"
        DAMAGED = "damaged", "Damaged"
        SOLD = "sold", "Sold"
        RETIRED = "retired", "Retired"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="drones")
    safety_profile = models.ForeignKey(
        DroneSafetyProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drones",
        help_text="Catalog profile used to populate this drone's safety features.",
    )
    manufacturer = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    nickname = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=150)
    faa_registration_number = models.CharField(max_length=100, blank=True)
    registration_date = models.DateField(null=True, blank=True)
    registration_expiration = models.DateField(null=True, blank=True)
    date_purchased = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    safety_features = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    faa_certificate = models.FileField(
        upload_to=faa_certificate_upload_path,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp", "pdf"]),
            validate_faa_certificate_size,
        ],
        help_text="JPG, PNG, WebP, or PDF. Maximum file size: 5 MB.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["manufacturer", "model", "nickname", "id"]

    def __str__(self):
        label = f"{self.manufacturer} {self.model}".strip()
        if self.nickname:
            label = f"{self.nickname} — {label}"
        if self.faa_registration_number:
            return f"{label} ({self.faa_registration_number})"
        return label

    def save(self, *args, **kwargs):
        pending_certificate = None
        if self._state.adding and self.faa_certificate:
            pending_certificate = self.faa_certificate
            self.faa_certificate = None
        super().save(*args, **kwargs)
        if pending_certificate is not None:
            self.faa_certificate = pending_certificate
            super().save(update_fields=["faa_certificate", "updated_at"])

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE
