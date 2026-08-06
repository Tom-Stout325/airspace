from unittest.mock import MagicMock, patch
from datetime import date
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from drones.models import Drone
from .models import (
    Airport,
    ApprovalType,
    OperationAircraft,
    OperationApproval,
    OperationsPlanning,
)
from .services import search_openstreetmap_address

User = get_user_model()

class OperationsPlanningTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", first_name="Owner", last_name="Pilot", password="pass-12345")
        self.other = User.objects.create_user(email="other@example.com", first_name="Other", last_name="Pilot", password="pass-12345")
        self.operation = OperationsPlanning.objects.create(user=self.owner, operation_title="Test operation", start_date=date.today())
        self.drone = Drone.objects.create(user=self.owner, manufacturer="DJI", model="Air 3S", serial_number="SERIAL-1", safety_features="RTH")

    def test_other_user_cannot_open_operation(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("airspace:operations_planning_detail", kwargs={"pk": self.operation.pk}))
        self.assertEqual(response.status_code, 404)

    def test_aircraft_assignment_copies_safety_snapshot(self):
        assignment = OperationAircraft.objects.create(
            operation=self.operation,
            drone=self.drone,
            current_firmware_installed=True,
        )
        self.assertEqual(assignment.safety_features_snapshot, "RTH")
        self.assertTrue(assignment.current_firmware_installed)

    def test_cannot_assign_another_users_drone(self):
        other_drone = Drone.objects.create(user=self.other, manufacturer="DJI", model="Mini 4 Pro", serial_number="SERIAL-2")
        assignment = OperationAircraft(operation=self.operation, drone=other_drone)
        with self.assertRaises(ValidationError): assignment.full_clean()

    def test_multiple_approval_types_can_be_added(self):
        altitude = ApprovalType.objects.create(code="107-51-altitude", category="operational_waiver", regulation="§107.51", name="Maximum altitude")
        bvlos = ApprovalType.objects.create(code="107-31-bvlos", category="operational_waiver", regulation="§107.31", name="BVLOS")
        OperationApproval.objects.create(operation=self.operation, approval_type=altitude)
        OperationApproval.objects.create(operation=self.operation, approval_type=bvlos)
        self.assertEqual(self.operation.approvals.count(), 2)

# ---------------------------------------------------------------------------
# Address search and nearest-airport tests
# ---------------------------------------------------------------------------

class OpenStreetMapAddressTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(
            email="address-pilot@example.com",
            password="test-password",
        )
        self.client.force_login(self.user)

    @patch("airspace.services.urlopen")
    def test_explicit_address_search_normalizes_result(self, mocked_urlopen):
        import json
        from django.core.cache import cache

        cache.clear()
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            [
                {
                    "display_name": "123 Main Street, Indianapolis, Indiana",
                    "lat": "39.7684",
                    "lon": "-86.1581",
                    "osm_type": "way",
                    "osm_id": 123,
                    "address": {
                        "house_number": "123",
                        "road": "Main Street",
                        "city": "Indianapolis",
                        "state": "Indiana",
                        "ISO3166-2-lvl4": "US-IN",
                        "postcode": "46204",
                    },
                }
            ]
        ).encode("utf-8")
        mocked_urlopen.return_value = response

        result = search_openstreetmap_address(
            "123 Main Street, Indianapolis"
        )[0]

        self.assertEqual(result["street_address"], "123 Main Street")
        self.assertEqual(result["city"], "Indianapolis")
        self.assertEqual(result["state"], "IN")
        self.assertEqual(result["zip_code"], "46204")

    def test_nearest_airport_endpoint_uses_local_faa_database(self):
        near = Airport.objects.create(
            faa_identifier="TYQ",
            icao="KTYQ",
            name="Indianapolis Executive Airport",
            latitude="40.0307",
            longitude="-86.2514",
            city="Zionsville",
            state="IN",
        )
        Airport.objects.create(
            faa_identifier="IND",
            icao="KIND",
            name="Indianapolis International Airport",
            latitude="39.7173",
            longitude="-86.2944",
            city="Indianapolis",
            state="IN",
        )

        response = self.client.get(
            reverse("airspace:nearest_airport_lookup"),
            {"lat": "40.0428", "lon": "-86.1275"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["found"])
        self.assertEqual(payload["airport"]["id"], near.pk)
        self.assertEqual(payload["airport"]["faa_identifier"], "TYQ")

class ApprovalWorkflowTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user(
            email="approval-pilot@example.com",
            password="test-password",
        )
        self.operation = OperationsPlanning.objects.create(
            user=self.user,
            operation_title="Approval Test",
            operation_description="Professional aerial operation.",
            start_date="2026-08-10",
            timeframe=["sunrise_noon"],
            purpose_operations=["pro_photography"],
        )
        self.approval_type = ApprovalType.objects.create(
            code="test-waiver",
            category="operational_waiver",
            regulation="14 CFR 107.31",
            name="Test BVLOS Waiver",
            active=True,
        )

    def test_approval_planning_complete(self):
        approval = OperationApproval.objects.create(
            operation=self.operation,
            approval_type=self.approval_type,
            requested_operation="Operate beyond visual line of sight.",
            safety_justification="The operation uses layered controls.",
            risk_mitigations="Visual observers and traffic monitoring.",
            equivalent_level_of_safety=(
                "The combined controls maintain an equivalent safety level."
            ),
        )

        self.assertTrue(approval.planning_complete)
        self.assertEqual(approval.regulation_display, "14 CFR 107.31")

    def test_tracking_fields_are_not_in_planning_form(self):
        from .forms import OperationApprovalForm

        form = OperationApprovalForm()
        self.assertIn("approval_type", form.fields)
        self.assertIn("requested_operation", form.fields)
        self.assertNotIn("faa_tracking_number", form.fields)
        self.assertNotIn("approval_document", form.fields)
        self.assertNotIn("status", form.fields)

    def test_operation_completion_reports_missing_sections(self):
        sections = self.operation.completion_sections()
        by_key = {section["key"]: section for section in sections}

        self.assertTrue(by_key["operation"]["complete"])
        self.assertFalse(by_key["aircraft"]["complete"])
        self.assertFalse(by_key["approvals"]["complete"])
        self.assertLess(self.operation.completion_percentage, 100)

