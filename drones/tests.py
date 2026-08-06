import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import DroneForm
from .models import Drone, DroneSafetyProfile
from .services import find_best_drone_profile


TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class DroneViewsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(email="pilot@example.com", password="test-pass-123")
        self.other_user = User.objects.create_user(email="other@example.com", password="test-pass-123")
        self.profile = DroneSafetyProfile.objects.create(
            brand="DJI",
            model_name="Avata 2",
            full_display_name="DJI Avata 2",
            aka_names="Avata 2",
            safety_features="Integrated propeller guards and Return-to-Home.",
            active=True,
        )
        self.drone = Drone.objects.create(
            user=self.user,
            manufacturer="DJI",
            model="Mavic 4 Pro",
            serial_number="SN-001",
            safety_features="Return-to-home and obstacle sensing.",
        )

    def test_list_requires_login(self):
        response = self.client.get(reverse("drones:list"))
        self.assertEqual(response.status_code, 302)

    def test_list_only_shows_current_users_drones(self):
        Drone.objects.create(user=self.other_user, manufacturer="DJI", model="Air 3S", serial_number="SN-002")
        self.client.force_login(self.user)
        response = self.client.get(reverse("drones:list"))
        self.assertContains(response, "Mavic 4 Pro")
        self.assertNotContains(response, "Air 3S")

    def test_create_assigns_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("drones:create"), {
            "safety_profile": self.profile.pk,
            "manufacturer": "",
            "model": "",
            "serial_number": "SN-003",
            "status": Drone.Status.ACTIVE,
            "safety_features": "",
        })
        created = Drone.objects.get(serial_number="SN-003")
        self.assertEqual(created.user, self.user)
        self.assertEqual(created.safety_profile, self.profile)
        self.assertEqual(created.manufacturer, self.profile.brand)
        self.assertEqual(created.model, self.profile.model_name)
        self.assertEqual(created.safety_features, self.profile.safety_features)
        self.assertRedirects(response, reverse("drones:detail", args=[created.pk]))

    def test_other_users_drone_returns_404(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("drones:detail", args=[self.drone.pk]))
        self.assertEqual(response.status_code, 404)

    def test_certificate_download_is_owner_scoped(self):
        self.drone.faa_certificate = SimpleUploadedFile("certificate.pdf", b"test", content_type="application/pdf")
        self.drone.save()
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("drones:faa_certificate_download", args=[self.drone.pk]))
        self.assertEqual(response.status_code, 404)

    def test_dashboard_shows_only_active_drones(self):
        Drone.objects.create(
            user=self.user,
            manufacturer="DJI",
            model="Retired Drone",
            serial_number="SN-004",
            status=Drone.Status.RETIRED,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("pilot:dashboard"))
        self.assertContains(response, "Mavic 4 Pro")
        self.assertNotContains(response, "Retired Drone")


class DroneSafetyProfileTests(TestCase):
    def setUp(self):
        self.profile = DroneSafetyProfile.objects.create(
            brand="DJI", model_name="Air 3S", full_display_name="DJI Air 3S",
            aka_names="Air 3S\nDJI Air 3 S", safety_features="RTH and obstacle sensing."
        )

    def test_exact_match(self):
        self.assertEqual(find_best_drone_profile("dji", "air 3s"), self.profile)

    def test_alias_match_supports_newlines(self):
        self.assertEqual(find_best_drone_profile("DJI", "DJI Air 3 S"), self.profile)

    def test_inactive_profile_is_not_suggested(self):
        self.profile.active = False; self.profile.save(update_fields=["active"])
        self.assertIsNone(find_best_drone_profile("DJI", "Air 3S"))

    def test_form_populates_empty_safety_features(self):
        form = DroneForm(data={
            "safety_profile": self.profile.pk,
            "manufacturer": "",
            "model": "",
            "serial_number": "S1",
            "status": Drone.Status.ACTIVE,
            "safety_features": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        drone = form.save(commit=False)
        self.assertEqual(drone.safety_profile, self.profile)
        self.assertEqual(drone.safety_features, self.profile.safety_features)

    def test_form_preserves_user_safety_features(self):
        form = DroneForm(data={
            "safety_profile": self.profile.pk,
            "manufacturer": "",
            "model": "",
            "serial_number": "S2",
            "status": Drone.Status.ACTIVE,
            "safety_features": "Custom wording",
        })
        self.assertTrue(form.is_valid(), form.errors)
        drone = form.save(commit=False)
        self.assertEqual(drone.safety_features, "Custom wording")

    def test_suggestion_endpoint_requires_login(self):
        response = self.client.get(reverse("drones:profile_suggest"), {"brand": "DJI", "name": "Air 3S"})
        self.assertEqual(response.status_code, 302)

class DroneProfileDropdownTests(TestCase):
    def setUp(self):
        self.profile = DroneSafetyProfile.objects.create(
            brand="DJI",
            model_name="Mavic 4 Pro",
            full_display_name="DJI Mavic 4 Pro",
            safety_features="Omnidirectional obstacle sensing and return-to-home.",
            active=True,
        )

    def test_dropdown_only_contains_active_profiles(self):
        inactive = DroneSafetyProfile.objects.create(
            brand="Autel",
            model_name="Inactive Model",
            full_display_name="Autel Inactive Model",
            safety_features="Test",
            active=False,
        )
        form = DroneForm()
        profile_ids = set(form.fields["safety_profile"].queryset.values_list("pk", flat=True))
        self.assertIn(self.profile.pk, profile_ids)
        self.assertNotIn(inactive.pk, profile_ids)

    def test_selected_profile_populates_drone_fields(self):
        form = DroneForm(data={
            "safety_profile": self.profile.pk,
            "manufacturer": "",
            "model": "",
            "serial_number": "M4P-001",
            "status": Drone.Status.ACTIVE,
        })
        self.assertTrue(form.is_valid(), form.errors)
        drone = form.save(commit=False)
        self.assertEqual(drone.safety_profile, self.profile)
        self.assertEqual(drone.manufacturer, "DJI")
        self.assertEqual(drone.model, "Mavic 4 Pro")
        self.assertEqual(drone.safety_features, self.profile.safety_features)

    def test_changing_profile_on_edit_refreshes_safety_features(self):
        other_profile = DroneSafetyProfile.objects.create(
            brand="DJI",
            model_name="Air 3S",
            full_display_name="DJI Air 3S",
            safety_features="Air 3S safety features.",
            active=True,
        )
        drone = Drone.objects.create(
            user=get_user_model().objects.create_user(email="dropdown@example.com", password="test-pass-123"),
            safety_profile=self.profile,
            manufacturer=self.profile.brand,
            model=self.profile.model_name,
            serial_number="EDIT-001",
            safety_features="Old profile features",
        )
        form = DroneForm(data={
            "safety_profile": other_profile.pk,
            "manufacturer": drone.manufacturer,
            "model": drone.model,
            "serial_number": drone.serial_number,
            "status": drone.status,
            "safety_features": drone.safety_features,
        }, instance=drone)
        self.assertTrue(form.is_valid(), form.errors)
        updated = form.save(commit=False)
        self.assertEqual(updated.safety_profile, other_profile)
        self.assertEqual(updated.manufacturer, other_profile.brand)
        self.assertEqual(updated.model, other_profile.model_name)
        self.assertEqual(updated.safety_features, other_profile.safety_features)
