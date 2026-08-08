from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models
from django.utils import timezone
import secrets

def generate_invitation_token():
    return secrets.token_urlsafe(32)


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set.')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=25, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = UserManager()

    class Meta:
        ordering = ['first_name', 'last_name', 'email']

    def __str__(self):
        full_name = self.get_full_name().strip()
        return full_name or self.email


class InvitationManager(models.Manager):
    def create_for_email(self, *, email, invited_by, lifetime):
        normalized = User.objects.normalize_email(email).lower()
        return self.create(
            email=normalized,
            invited_by=invited_by,
            expires_at=timezone.now() + lifetime,
        )


class Invitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"

    email              = models.EmailField(db_index=True)
    token              = models.CharField(max_length=64, unique=True, editable=False, default=generate_invitation_token,)
    status             = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    invited_by         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_invitations",)
    sent_at            = models.DateTimeField(null=True, blank=True)
    expires_at         = models.DateTimeField(db_index=True)
    accepted_at        = models.DateTimeField(null=True, blank=True)
    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)
    objects            = InvitationManager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["email"],
                condition=models.Q(status="pending"),
                name="accounts_one_pending_invitation_per_email",
            )
        ]

    def __str__(self):
        return f"{self.email} ({self.display_status})"

    @property
    def is_expired(self):
        return self.status == self.Status.PENDING and timezone.now() >= self.expires_at

    @property
    def display_status(self):
        return "expired" if self.is_expired else self.status


class EmailDeliveryLog(models.Model):
    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    invitation = models.ForeignKey(Invitation, on_delete=models.CASCADE, related_name="delivery_logs")
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    error_message = models.TextField(blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-attempted_at"]

    def __str__(self):
        return f"{self.recipient} - {self.status}"
