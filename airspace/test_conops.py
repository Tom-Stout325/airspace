from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from airspace.conops import generate_conops, save_conops_review
from airspace.models import (
    ApprovalType,
    ConopsSection,
    OperationApproval,
    OperationsPlanning,
)


class ConopsGenerationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="conops-pilot@example.com",
            password="test-password",
        )
        self.operation = OperationsPlanning.objects.create(
            user=self.user,
            operation_title="CONOPS Test Operation",
            operation_description="Aerial event coverage.",
            start_date="2026-09-01",
            timeframe=["sunrise_noon"],
            purpose_operations=["pro_photography"],
            venue_name="Test Raceway",
            location_city="Indianapolis",
            location_state="IN",
            maximum_planned_altitude_agl=200,
            ground_risk_mitigation="A controlled operating area is used.",
            air_risk_mitigation="The crew scans for crewed aircraft.",
            lost_link_actions="The aircraft executes Return-to-Home.",
            emergency_response_plan="The RPIC terminates the operation.",
            termination_conditions="The operation stops for crewed traffic.",
        )
        self.approval_type = ApprovalType.objects.create(
            code="conops-test",
            category="operational_waiver",
            regulation="14 CFR 107.31",
            name="CONOPS Test Waiver",
            active=True,
        )
        self.approval = OperationApproval.objects.create(
            operation=self.operation,
            approval_type=self.approval_type,
            requested_operation="Operate beyond visual line of sight.",
            safety_justification="Layered mitigations support safe flight.",
            risk_mitigations="Visual observers and traffic awareness.",
            equivalent_level_of_safety=(
                "The controls provide an equivalent level of safety."
            ),
        )

    def test_generation_creates_application_and_sections(self):
        application = generate_conops(
            self.approval,
            self.user,
        )

        self.assertEqual(application.approval, self.approval)
        self.assertGreater(
            application.conops_sections.count(),
            10,
        )
        self.assertIn(
            "CONOPS Test Operation",
            application.description,
        )

    def test_regeneration_preserves_locked_section(self):
        application = generate_conops(
            self.approval,
            self.user,
        )
        section = application.conops_sections.first()
        section.content = "Manual protected wording."
        section.locked = True
        section.save()

        self.operation.operation_description = "Changed description."
        self.operation.save()

        generate_conops(
            self.approval,
            self.user,
            regenerate_unlocked=True,
        )

        section.refresh_from_db()
        self.assertEqual(
            section.content,
            "Manual protected wording.",
        )

    def test_changed_review_text_is_automatically_locked(self):
        application = generate_conops(
            self.approval,
            self.user,
        )
        section = application.conops_sections.first()

        save_conops_review(
            application,
            {
                section.pk: {
                    "content": "Edited by the user.",
                    "locked": False,
                    "is_complete": True,
                }
            },
        )

        section.refresh_from_db()
        self.assertTrue(section.locked)
        self.assertTrue(section.is_complete)
        self.assertEqual(section.content, "Edited by the user.")

    def test_owner_can_open_conops_review(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse(
                "airspace:operation_conops_review",
                kwargs={
                    "operation_pk": self.operation.pk,
                    "approval_pk": self.approval.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Concept of Operations")

    def test_other_user_cannot_open_conops_review(self):
        other_user = get_user_model().objects.create_user(
            email="other-conops@example.com",
            password="test-password",
        )
        self.client.force_login(other_user)

        response = self.client.get(
            reverse(
                "airspace:operation_conops_review",
                kwargs={
                    "operation_pk": self.operation.pk,
                    "approval_pk": self.approval.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 404)
