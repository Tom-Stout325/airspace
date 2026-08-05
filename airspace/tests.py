from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import WaiverPlanning

User = get_user_model()


class WaiverOwnershipTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", first_name="Owner", last_name="Pilot", password="pass-12345")
        self.other = User.objects.create_user(email="other@example.com", first_name="Other", last_name="Pilot", password="pass-12345")
        self.planning = WaiverPlanning.objects.create(
            user=self.owner,
            operation_title="Owner waiver",
            start_date=date.today(),
        )

    def test_user_cannot_open_another_users_waiver(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("airspace:waiver_application_overview", kwargs={"planning_id": self.planning.pk}))
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_delete_another_users_waiver(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse("airspace:waiver_planning_delete", kwargs={"pk": self.planning.pk}))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(WaiverPlanning.objects.filter(pk=self.planning.pk).exists())
