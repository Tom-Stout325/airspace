from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import PilotProfile

class PilotProfileTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="pilot@example.com", password="test-pass-123", first_name="Pat", last_name="Pilot")
        self.other_user = user_model.objects.create_user(email="other@example.com", password="test-pass-123", first_name="Other", last_name="Pilot")
        PilotProfile.objects.create(user=self.other_user, faa_certificate_number="OTHER-123")
        self.client.force_login(self.user)

    def test_dashboard_only_displays_logged_in_users_profile(self):
        response = self.client.get(reverse("pilot:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "OTHER-123")

    def test_profile_create_and_update(self):
        response = self.client.post(reverse("pilot:profile_edit"), {"first_name":"Patricia","last_name":"Pilot","business_name":"Sky LLC","email":"pilot@example.com","street_address":"123 Main St","city":"Westfield","state":"in","zip_code":"46074","phone":"317-555-0100","faa_certificate_number":"FAA-123"})
        self.assertRedirects(response, reverse("pilot:dashboard"))
        profile = PilotProfile.objects.get(user=self.user)
        self.assertEqual(profile.state, "IN")
        self.assertEqual(profile.business_name, "Sky LLC")

    def test_logo_download_is_scoped_to_logged_in_user(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        PilotProfile.objects.create(
            user=self.user,
            logo=SimpleUploadedFile("logo.png", b"test-logo", content_type="image/png"),
        )

        response = self.client.get(reverse("pilot:logo_download"))
        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.other_user)
        response = self.client.get(reverse("pilot:logo_download"))
        self.assertEqual(response.status_code, 404)

    def test_profile_delete_does_not_delete_login_account(self):
        PilotProfile.objects.create(user=self.user, faa_certificate_number="FAA-123")
        self.client.post(reverse("pilot:profile_delete"))
        self.assertFalse(PilotProfile.objects.filter(user=self.user).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(reverse("pilot:dashboard"))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('pilot:dashboard')}")
