from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from airspace.models import OperationsPlanning


class OperationPlanningPDFTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="pdf-pilot@example.com",
            password="test-password",
        )
        self.other_user = get_user_model().objects.create_user(
            email="other-pilot@example.com",
            password="test-password",
        )
        self.operation = OperationsPlanning.objects.create(
            user=self.user,
            operation_title="PDF Planning Test",
            operation_description="Test PDF operation.",
            start_date="2026-08-30",
            timeframe=["sunrise_noon"],
            purpose_operations=["pro_photography"],
        )

    @patch("airspace.views.HTML")
    def test_owner_can_view_pdf_inline(self, html_class):
        html_instance = MagicMock()
        html_instance.write_pdf.return_value = b"%PDF-test"
        html_class.return_value = html_instance
        self.client.force_login(self.user)

        response = self.client.get(
            reverse(
                "airspace:operation_planning_pdf",
                kwargs={"pk": self.operation.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(
            response["Content-Disposition"].startswith("inline;")
        )
        self.assertEqual(response.content, b"%PDF-test")

    @patch("airspace.views.HTML")
    def test_download_query_uses_attachment_disposition(
        self,
        html_class,
    ):
        html_instance = MagicMock()
        html_instance.write_pdf.return_value = b"%PDF-test"
        html_class.return_value = html_instance
        self.client.force_login(self.user)

        response = self.client.get(
            reverse(
                "airspace:operation_planning_pdf",
                kwargs={"pk": self.operation.pk},
            ),
            {"download": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response["Content-Disposition"].startswith("attachment;")
        )

    def test_other_user_cannot_access_pdf(self):
        self.client.force_login(self.other_user)

        response = self.client.get(
            reverse(
                "airspace:operation_planning_pdf",
                kwargs={"pk": self.operation.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
