from decimal import Decimal

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

from .validators import validate_logo_file_size


class PilotProfile(models.Model):
    user                        = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pilot_profile")
    business_name               = models.CharField(max_length=200, blank=True)
    logo                        = models.ImageField(
        upload_to="pilot_logos/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
            validate_logo_file_size,
        ],
        help_text="JPG, PNG, or WebP. Maximum file size: 5 MB.",
    )
    street_address              = models.CharField(max_length=255, blank=True)
    city                        = models.CharField(max_length=100, blank=True)
    state                       = models.CharField(max_length=2, blank=True)
    zip_code                    = models.CharField(max_length=10, blank=True)
    phone                       = models.CharField(max_length=25, blank=True)
    faa_certificate_number      = models.CharField(max_length=100, blank=True)
    total_flight_hours          = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    created_at                  = models.DateTimeField(auto_now_add=True)
    updated_at                  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__last_name", "user__first_name", "user__email"]

    def __str__(self):
        full_name = f"{self.user.first_name} {self.user.last_name}".strip()
        return full_name or self.user.email

    def flight_time_total(self):
        if not self.total_flight_hours:
            return 0
        return int(Decimal(self.total_flight_hours) * Decimal("3600"))




class Aircraft(models.Model):
    user                 = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="aircraft")
    brand                = models.CharField(max_length=100)
    model                = models.CharField(max_length=100)
    registration_number  = models.CharField(max_length=100, blank=True)
    safety_features      = models.TextField(blank=True)
    active               = models.BooleanField(default=True)
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["brand", "model", "id"]

    def __str__(self):
        label = f"{self.brand} {self.model}".strip()
        if self.registration_number:
            return f"{label} ({self.registration_number})"
        return label

    @property
    def drone_safety_profile(self):
        return self
