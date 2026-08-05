from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from pilot.models import PilotProfile

from .models import EmailDeliveryLog, Invitation

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InvitationFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin@example.com", first_name="Admin", last_name="User", password="test-pass-123", is_staff=True
        )
        self.regular_user = User.objects.create_user(
            email="pilot@example.com", first_name="Pilot", last_name="User", password="test-pass-123"
        )

    def test_only_staff_can_open_invitation_page(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse("accounts:invitation_list"))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:invitation_list"))
        self.assertEqual(response.status_code, 200)

    def test_staff_can_send_invitation_and_delivery_is_logged(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("accounts:invitation_list"), {"email": "newpilot@example.com"})
        self.assertRedirects(response, reverse("accounts:invitation_list"))
        invitation = Invitation.objects.get(email="newpilot@example.com")
        self.assertIsNotNone(invitation.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(invitation.token, mail.outbox[0].body)
        self.assertTrue(EmailDeliveryLog.objects.filter(invitation=invitation, status="sent").exists())

    def test_public_registration_is_blocked(self):
        response = self.client.get(reverse("accounts:register"))
        self.assertEqual(response.status_code, 403)

    def test_expired_invitation_cannot_register(self):
        invitation = Invitation.objects.create_for_email(
            email="expired@example.com", invited_by=self.admin, lifetime=timedelta(seconds=-1)
        )
        response = self.client.get(reverse("accounts:invitation_accept", kwargs={"token": invitation.token}))
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, "expired", status_code=410)

    def test_invitation_is_single_use_and_creates_profile(self):
        invitation = Invitation.objects.create_for_email(
            email="accepted@example.com", invited_by=self.admin, lifetime=timedelta(hours=1)
        )
        url = reverse("accounts:invitation_accept", kwargs={"token": invitation.token})
        response = self.client.post(url, {
            "email": invitation.email,
            "first_name": "New",
            "last_name": "Pilot",
            "phone": "317-555-0100",
            "password1": "Strong-test-password-123",
            "password2": "Strong-test-password-123",
        })
        user = User.objects.get(email=invitation.email)
        self.assertRedirects(response, reverse("pilot:profile_edit"),)
        self.assertTrue(PilotProfile.objects.filter(user=user).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.ACCEPTED)
        self.assertIsNotNone(invitation.accepted_at)

        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 410)

    def test_duplicate_pending_invitation_is_rejected(self):
        Invitation.objects.create_for_email(
            email="duplicate@example.com", invited_by=self.admin, lifetime=timedelta(hours=1)
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse("accounts:invitation_list"), {"email": "duplicate@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pending invitation already exists")

    def test_staff_can_revoke_pending_invitation(self):
        invitation = Invitation.objects.create_for_email(
            email="revoke@example.com", invited_by=self.admin, lifetime=timedelta(hours=1)
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse("accounts:invitation_revoke", kwargs={"pk": invitation.pk}))
        self.assertRedirects(response, reverse("accounts:invitation_list"))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, Invitation.Status.REVOKED)
