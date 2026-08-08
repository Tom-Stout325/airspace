from unittest.mock import MagicMock, patch
from datetime import date
from io import BytesIO
import json
from tempfile import TemporaryDirectory
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from pypdf import PdfReader, PdfWriter
from drones.models import Drone
from pilot.models import PilotProfile
from .ai_conops import (
    GeneratedConopsPackage,
    GeneratedConopsSection,
    OpenAIConopsError,
    _operation_payload,
    _system_prompt,
    _validate_geometry_source_fidelity,
    _validate_package,
    generate_ai_conops,
)
from .conops import (
    CONOPS_DEFINITIONS,
    _airspace_atc_coordination,
    _dates_location_airspace,
    _emergency_procedures,
    _flight_envelope_limitations,
    _operation_overview,
    _see_and_avoid,
    get_or_create_application,
)
from .forms import OperationsPlanningForm
from .models import (
    Airport,
    ApprovalType,
    ConopsSection,
    OperationAircraft,
    OperationApproval,
    OperationsPlanning,
)
from .services import (
    _validate_generated_geometry_text,
    build_conops_section_prompt,
    build_waiver_description_prompt,
    search_openstreetmap_address,
)
from .views import _operation_timezone_display, _submission_workflow_steps

User = get_user_model()

class OperationsPlanningTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.com", first_name="Owner", last_name="Pilot", password="pass-12345")
        self.other = User.objects.create_user(email="other@example.com", first_name="Other", last_name="Pilot", password="pass-12345")
        self.owner_profile = PilotProfile.objects.create(
            user=self.owner,
            faa_certificate_number="OWNER-FAA-123",
        )
        self.other_profile = PilotProfile.objects.create(
            user=self.other,
            faa_certificate_number="OTHER-FAA-456",
        )
        self.operation = OperationsPlanning.objects.create(user=self.owner, operation_title="Test operation", start_date=date.today())
        self.drone = Drone.objects.create(user=self.owner, manufacturer="DJI", model="Air 3S", serial_number="SERIAL-1", safety_features="RTH")

    def operation_form_data(self, **overrides):
        data = {
            "status": OperationsPlanning.Status.DRAFT,
            "operation_title": "Certificate test operation",
            "start_date": date.today().isoformat(),
            "operation_area_type": "radius",
        }
        data.update(overrides)
        return data

    def test_selected_pilot_certificate_is_saved_on_create(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("airspace:operations_planning_create"),
            self.operation_form_data(
                pilot_profile=str(self.owner_profile.pk),
                pilot_cert_manual="untrusted-submitted-value",
            ),
        )

        created = OperationsPlanning.objects.get(
            operation_title="Certificate test operation",
        )
        self.assertRedirects(
            response,
            reverse(
                "airspace:operations_planning_detail",
                kwargs={"pk": created.pk},
            ),
        )
        self.assertEqual(created.pilot_profile, self.owner_profile)
        self.assertEqual(created.pilot_cert_manual, "OWNER-FAA-123")

    def test_edit_form_renders_selected_pilot_current_certificate(self):
        self.operation.pilot_profile = self.owner_profile
        self.operation.pilot_cert_manual = "STALE-CERTIFICATE"
        self.operation.save()
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                "airspace:operations_planning_edit",
                kwargs={"pk": self.operation.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"]["pilot_cert_manual"].value(),
            "OWNER-FAA-123",
        )
        self.assertContains(response, "OWNER-FAA-123")
        self.assertNotContains(response, "OTHER-FAA-456")

        response = self.client.post(
            reverse(
                "airspace:operations_planning_edit",
                kwargs={"pk": self.operation.pk},
            ),
            self.operation_form_data(
                operation_title=self.operation.operation_title,
                pilot_profile=str(self.owner_profile.pk),
                pilot_cert_manual="STALE-CERTIFICATE",
            ),
        )

        self.assertRedirects(
            response,
            reverse(
                "airspace:operations_planning_detail",
                kwargs={"pk": self.operation.pk},
            ),
        )
        self.operation.refresh_from_db()
        self.assertEqual(
            self.operation.pilot_cert_manual,
            "OWNER-FAA-123",
        )

    def test_other_users_pilot_profile_cannot_be_selected(self):
        form = OperationsPlanningForm(
            data=self.operation_form_data(
                pilot_profile=str(self.other_profile.pk),
            ),
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("pilot_profile", form.errors)

    def test_no_selected_pilot_keeps_blank_certificate(self):
        form = OperationsPlanningForm(
            data=self.operation_form_data(
                pilot_profile="",
                pilot_cert_manual="",
            ),
            user=self.owner,
        )

        self.assertTrue(form.is_valid(), form.errors)
        operation = form.save()
        self.assertIsNone(operation.pilot_profile)
        self.assertEqual(operation.pilot_cert_manual, "")

    def test_operation_map_upload_is_saved_through_planning_form(self):
        uploaded_map = SimpleUploadedFile(
            "Operation-Map.PDF",
            b"%PDF-1.4 test map",
            content_type="application/pdf",
        )

        with TemporaryDirectory() as media_root, self.settings(
            MEDIA_ROOT=media_root,
        ):
            form = OperationsPlanningForm(
                data=self.operation_form_data(),
                files={"operation_map": uploaded_map},
                user=self.owner,
            )

            self.assertTrue(form.is_valid(), form.errors)
            operation = form.save()

            self.assertRegex(
                operation.operation_map.name,
                rf"^operation_maps/user_{self.owner.pk}/[0-9a-f]{{32}}\.pdf$",
            )
            self.assertTrue(
                operation.operation_map.storage.exists(
                    operation.operation_map.name,
                )
            )

    def test_ai_payload_serializes_operation_map_as_safe_metadata(self):
        uploaded_map = SimpleUploadedFile(
            "Private-Operation-Map.PDF",
            b"%PDF-1.4 private test map",
            content_type="application/pdf",
        )

        with TemporaryDirectory() as media_root, self.settings(
            MEDIA_ROOT=media_root,
        ):
            form = OperationsPlanningForm(
                data=self.operation_form_data(
                    operation_title="Mapped AI payload operation",
                ),
                files={"operation_map": uploaded_map},
                user=self.owner,
            )
            self.assertTrue(form.is_valid(), form.errors)
            operation = form.save()
            approval_type = ApprovalType.objects.create(
                code="mapped-payload-test",
                category="airspace",
                name="Mapped payload test",
            )
            approval = OperationApproval.objects.create(
                operation=operation,
                approval_type=approval_type,
            )

            payload = _operation_payload(approval)
            serialized = json.dumps(payload)

            map_metadata = payload["operation"]["operation_map"]
            self.assertTrue(map_metadata["present"])
            self.assertEqual(
                map_metadata["filename"],
                operation.operation_map.name.rsplit("/", 1)[-1],
            )
            self.assertNotIn(media_root, serialized)
            self.assertNotIn(operation.operation_map.path, serialized)
            self.assertNotIn(operation.operation_map.url, serialized)

    def test_ai_payload_serializes_missing_operation_map(self):
        approval_type = ApprovalType.objects.create(
            code="unmapped-payload-test",
            category="airspace",
            name="Unmapped payload test",
        )
        approval = OperationApproval.objects.create(
            operation=self.operation,
            approval_type=approval_type,
        )

        payload = _operation_payload(approval)

        self.assertEqual(
            payload["operation"]["operation_map"],
            {"present": False, "filename": ""},
        )
        json.dumps(payload)

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


class ControlledAirspaceConopsWordingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="conops-wording@example.com",
            password="test-pass-123",
        )
        self.operation = OperationsPlanning.objects.create(
            user=self.user,
            operation_title="Controlled airspace wording test",
            start_date=date.today(),
            maximum_planned_altitude_agl=375,
            uses_flight_tracking=True,
            flight_tracking_service="SkyTrack Pro",
            atc_checkin_procedure=(
                "Call the recorded ATC contact before launch and report "
                "operation termination after landing."
            ),
            emergency_response_plan=(
                "Notify ATC and emergency services using the saved contact "
                "plan when an emergency affects the airspace."
            ),
        )
        self.approval_type = ApprovalType.objects.create(
            code="controlled-airspace",
            category="airspace",
            regulation="§107.41",
            name="Controlled Airspace Authorization",
        )
        self.approval = OperationApproval.objects.create(
            operation=self.operation,
            approval_type=self.approval_type,
        )

    def test_requested_altitude_is_qualified_by_faa_authorization(self):
        area_text = _dates_location_airspace(self.approval)
        envelope_text = _flight_envelope_limitations(self.approval)

        self.assertIn("375 feet AGL", area_text)
        self.assertIn("subject to the altitude authorized by the FAA", area_text)
        self.assertIn(
            "requested maximum altitude of 375 feet AGL",
            envelope_text,
        )
        self.assertIn(
            "not exceed any lower altitude limitation specified in the FAA authorization",
            envelope_text,
        )

    def test_description_prompt_requires_requested_altitude_wording(self):
        prompt = build_waiver_description_prompt(self.operation)

        self.assertIn("'maximum_planned_altitude_agl': 375", prompt)
        self.assertIn(
            "at or below the requested maximum altitude of [value] feet AGL "
            "and subject to any lower altitude limitation specified in the "
            "FAA authorization",
            prompt,
        )

    def test_description_prompt_uses_authorization_not_waiver(self):
        prompt = build_waiver_description_prompt(self.operation)

        self.assertIn("'controlled_airspace_only': True", prompt)
        self.assertIn(
            "This application requests a controlled-airspace authorization "
            "under §107.41 and does not request relief from any other Part "
            "107 requirement.",
            prompt,
        )
        self.assertIn("Do not call the §107.41 authorization a waiver", prompt)

        other_type = ApprovalType.objects.create(
            code="107-31-description-scope-test",
            category="operational_waiver",
            regulation="§107.31",
            name="Beyond Visual Line of Sight",
        )
        OperationApproval.objects.create(
            operation=self.operation,
            approval_type=other_type,
        )

        self.assertIn(
            "'controlled_airspace_only': False",
            build_waiver_description_prompt(self.operation),
        )

    def test_controlled_airspace_only_request_uses_authorization_language(self):
        text = _airspace_atc_coordination(self.approval)

        self.assertIn(
            "This application requests a controlled-airspace authorization "
            "under §107.41 and does not request relief from any other Part "
            "107 requirement.",
            text,
        )
        self.assertNotIn("does not request any waivers", text)

        other_type = ApprovalType.objects.create(
            code="107-31-bvlos-wording-test",
            category="operational_waiver",
            regulation="§107.31",
            name="Beyond Visual Line of Sight",
        )
        OperationApproval.objects.create(
            operation=self.operation,
            approval_type=other_type,
        )

        text_with_other_relief = _airspace_atc_coordination(self.approval)
        self.assertNotIn(
            "does not request relief from any other Part 107 requirement",
            text_with_other_relief,
        )

    def test_tracking_service_is_named_as_supplemental_only(self):
        text = _see_and_avoid(self.approval)

        self.assertIn(
            "SkyTrack Pro will be used as a supplemental situational-awareness tool",
            text,
        )
        self.assertIn("does not replace visual scanning", text)
        self.assertIn("RPIC's obligation to yield right of way", text)
        self.assertNotIn("FlightAware", text)

        self.operation.flight_tracking_service = "FlightAware"
        self.operation.save(update_fields=["flight_tracking_service"])

        self.assertIn(
            "FlightAware will be used as a supplemental situational-awareness tool",
            _see_and_avoid(self.approval),
        )

    def test_description_prompt_preserves_tracking_service_and_disclaimer(self):
        prompt = build_waiver_description_prompt(self.operation)

        self.assertIn("'flight_tracking_service': 'SkyTrack Pro'", prompt)
        self.assertIn("supplemental situational awareness only", prompt)
        self.assertIn("does not replace visual scanning", prompt)
        self.assertIn("see-and-avoid responsibilities", prompt)
        self.assertIn(
            "RPIC's obligation to yield right of way to crewed aircraft",
            prompt,
        )
        self.assertNotIn("FlightAware", prompt)

    def test_description_prompt_distinguishes_routine_and_emergency_atc(self):
        self.operation.atc_checkin_procedure = ""
        self.operation.emergency_response_plan = (
            "Notify ATC using the recorded emergency contact procedure."
        )
        self.operation.save(
            update_fields=["atc_checkin_procedure", "emergency_response_plan"]
        )

        prompt = build_waiver_description_prompt(self.operation)

        self.assertIn(self.operation.emergency_response_plan, prompt)
        self.assertIn(
            "No routine ATC check-in or communication procedure is prescribed. "
            "User-defined emergency notification procedures are addressed in "
            "Section 9.",
            prompt,
        )
        self.assertIn("Do not say that no direct ATC procedure exists", prompt)

    def test_user_entered_year_round_language_is_preserved(self):
        year_round_text = (
            "Operations are requested year-round, subject to the recorded "
            "operating dates and FAA authorization."
        )
        self.operation.operation_description = year_round_text
        self.operation.save(update_fields=["operation_description"])

        self.assertIn(
            f"'operation_description': '{year_round_text}'",
            build_waiver_description_prompt(self.operation),
        )
        self.assertIn(year_round_text, _operation_overview(self.approval))

    def test_user_entered_atc_and_emergency_procedures_are_preserved(self):
        self.assertIn(
            self.operation.atc_checkin_procedure,
            _airspace_atc_coordination(self.approval),
        )
        self.assertIn(
            self.operation.emergency_response_plan,
            _emergency_procedures(self.approval),
        )

    def test_ai_payload_and_prompt_include_wording_guardrails(self):
        payload = _operation_payload(self.approval)
        prompt = _system_prompt()

        self.assertTrue(
            payload["regulatory_context"]["controlled_airspace_only"]
        )
        self.assertEqual(
            payload["operation"]["flight_tracking_service"],
            "SkyTrack Pro",
        )
        self.assertIn("requested maximum altitude", prompt)
        self.assertIn("does not request relief from any other Part 107 requirement", prompt)
        self.assertIn("Never substitute or invent FlightAware", prompt)
        self.assertIn(
            "Preserve user-entered emergency and ATC notification procedures exactly",
            prompt,
        )
        self.assertIn("Preserve user-entered facility identifiers exactly", prompt)

    def test_generated_package_requires_exact_lsv_atc_procedure(self):
        procedure = "If required during an emergency, notify LSV ATC."
        sections = [
            GeneratedConopsSection(
                key=definition.key,
                title=definition.title,
                content=(
                    procedure
                    if definition.key == "emergency-procedures"
                    else f"Content for {definition.key}."
                ),
            )
            for definition in CONOPS_DEFINITIONS
        ]
        package = GeneratedConopsPackage(
            description_of_operations="Controlled-airspace operation.",
            sections=sections,
        )

        _validate_package(
            package,
            required_exact_phrases=(procedure,),
        )

        sections[-1].content = (
            "If required during an emergency, notify Las Vegas Motor "
            "Speedway ATC."
        )
        expanded = GeneratedConopsPackage(
            description_of_operations="Controlled-airspace operation.",
            sections=sections,
        )
        with self.assertRaises(OpenAIConopsError):
            _validate_package(
                expanded,
                required_exact_phrases=(procedure,),
            )

    def _geometry_package(self, text):
        return GeneratedConopsPackage(
            description_of_operations=text,
            sections=[
                GeneratedConopsSection(
                    key=definition.key,
                    title=definition.title,
                    content=f"Content for {definition.key}.",
                )
                for definition in CONOPS_DEFINITIONS
            ],
        )

    def test_numeric_dronezone_radius_is_supplied_and_preserved(self):
        self.operation.dronezone_radius = "0.5_nm"
        self.operation.save(update_fields=["dronezone_radius"])

        payload = _operation_payload(self.approval)
        self.assertEqual(
            payload["operation_semantics"]["dronezone_requested_radius"],
            "1/2 NM",
        )
        _validate_geometry_source_fidelity(
            self._geometry_package("The DroneZone Requested Radius is 1/2 NM."),
            self.operation,
        )

    def test_blanket_multiple_sites_and_varies_are_semantic_payload_values(self):
        self.operation.dronezone_radius = "blanket_wide_area"
        self.operation.operation_area_type = "multiple_sites"
        self.operation.launch_location = "Varies"
        self.operation.recovery_location = "Varies"
        self.operation.location_latitude = "36.271187"
        self.operation.location_longitude = "-115.009416"
        self.operation.save()

        payload = _operation_payload(self.approval)
        semantics = payload["operation_semantics"]
        self.assertEqual(
            semantics["dronezone_requested_radius"],
            "Blanket Area / Wide Area",
        )
        self.assertEqual(semantics["operational_area_geometry"], "Multiple sites")
        self.assertEqual(semantics["launch_location"], "Varies")
        self.assertEqual(semantics["recovery_location"], "Varies")
        self.assertIn(
            "not a launch or recovery coordinate",
            semantics["operation_reference_coordinates"]["meaning"],
        )

        description_prompt = build_waiver_description_prompt(self.operation)
        section_prompt = build_conops_section_prompt(
            application=MagicMock(),
            planning=self.operation,
            section=MagicMock(
                section_key="operational_area_containment",
                title="Operational Area & Containment",
            ),
        )
        for prompt in (description_prompt, section_prompt):
            self.assertIn("'dronezone_requested_radius': 'Blanket Area / Wide Area'", prompt)
            self.assertIn("'operation_area_geometry': 'Multiple sites'", prompt)
            self.assertIn("'launch_location': 'Varies'", prompt)
            self.assertIn("Operation reference coordinates", prompt)

    def test_blanket_radius_rejects_numeric_radius_and_launch_coordinate_rewrite(self):
        self.operation.dronezone_radius = "blanket_wide_area"
        self.operation.operation_area_type = "multiple_sites"
        self.operation.launch_location = "Varies"
        self.operation.recovery_location = "Varies"
        self.operation.save()
        valid = (
            "The DroneZone Requested Radius is Blanket Area / Wide Area for "
            "Multiple sites. The launch location Varies and the recovery "
            "location Varies. The coordinates are operation reference "
            "coordinates."
        )

        _validate_geometry_source_fidelity(
            self._geometry_package(valid),
            self.operation,
        )
        _validate_generated_geometry_text(
            valid,
            self.operation,
            require_planning_values=True,
        )

        with self.assertRaises(OpenAIConopsError):
            _validate_geometry_source_fidelity(
                self._geometry_package(
                    valid + " Flights use an authorized 0.5 nautical mile radius."
                ),
                self.operation,
            )
        with self.assertRaises(OpenAIConopsError):
            _validate_geometry_source_fidelity(
                self._geometry_package(
                    valid + " The launch site is at latitude 36.271187."
                ),
                self.operation,
            )

    def test_conops_headings_render_regulation_only_once(self):
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

        expected_heading = "Controlled Airspace Authorization · §107.41"
        duplicate_heading = (
            "§107.41 — Controlled Airspace Authorization · §107.41"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, duplicate_heading)
        self.assertEqual(
            response.content.decode("utf-8").count("§107.41"),
            1,
        )

        application = get_or_create_application(self.approval, self.user)
        rendered_pdf = render_to_string(
            "airspace/pdf/conops_pdf.html",
            {
                "operation": self.operation,
                "approval": self.approval,
                "application": application,
                "sections": [],
                "generated_at": timezone.now(),
                "all_sections_complete": False,
                "logo_uri": "",
            },
        )
        self.assertIn(expected_heading, rendered_pdf)
        self.assertNotIn(duplicate_heading, rendered_pdf)


class ConopsReviewWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="conops-review@example.com",
            password="test-pass-123",
        )
        self.operation = OperationsPlanning.objects.create(
            user=self.user,
            operation_title="CONOPS review workflow",
            start_date=date.today(),
        )
        self.approval_type = ApprovalType.objects.create(
            code="controlled-airspace-review",
            category="airspace",
            regulation="§107.41",
            name="Controlled Airspace Authorization",
        )
        self.approval = OperationApproval.objects.create(
            operation=self.operation,
            approval_type=self.approval_type,
        )
        self.application = get_or_create_application(
            self.approval,
            self.user,
        )
        self.application.description = "Saved Description of Operations."
        self.application.save(update_fields=["description", "updated_at"])
        self.sections = []
        for definition in CONOPS_DEFINITIONS:
            self.sections.append(
                ConopsSection.objects.create(
                    user=self.user,
                    application=self.application,
                    section_key=definition.key,
                    title=definition.title,
                    content=f"Saved content for {definition.title}.",
                )
            )
        self.url = reverse(
            "airspace:operation_conops_review",
            kwargs={
                "operation_pk": self.operation.pk,
                "approval_pk": self.approval.pk,
            },
        )
        self.client.force_login(self.user)

    def _post_data(self, **extra):
        data = {
            "action": "save",
            "description": self.application.description,
        }
        for section in self.sections:
            data[f"content_{section.pk}"] = section.content
        data.update(extra)
        return data

    def test_progress_includes_description_at_zero_partial_and_complete(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context["complete_count"], 0)
        self.assertEqual(response.context["total_count"], 10)
        self.assertEqual(response.context["review_percentage"], 0)
        self.assertContains(response, "0 of 10 items reviewed")

        self.application.description_is_complete = True
        self.application.save(
            update_fields=["description_is_complete", "updated_at"]
        )
        ConopsSection.objects.filter(
            pk__in=[section.pk for section in self.sections[:4]]
        ).update(is_complete=True)

        response = self.client.get(self.url)
        self.assertEqual(response.context["complete_count"], 5)
        self.assertEqual(response.context["total_count"], 10)
        self.assertEqual(response.context["review_percentage"], 50)

        ConopsSection.objects.filter(application=self.application).update(
            is_complete=True
        )
        response = self.client.get(self.url)
        self.assertEqual(response.context["complete_count"], 10)
        self.assertEqual(response.context["review_percentage"], 100)
        self.assertContains(response, "10 of 10 items reviewed")

    def test_description_review_state_persists_independently_from_protection(self):
        response = self.client.post(
            self.url,
            self._post_data(description_is_complete="on"),
        )
        self.assertRedirects(response, self.url)

        self.application.refresh_from_db()
        self.assertTrue(self.application.description_is_complete)
        self.assertIsNotNone(self.application.description_validated_at)
        self.assertFalse(self.application.locked_description)

        response = self.client.post(
            self.url,
            self._post_data(locked_description="on"),
        )
        self.assertRedirects(response, self.url)

        self.application.refresh_from_db()
        self.assertTrue(self.application.locked_description)
        self.assertFalse(self.application.description_is_complete)

    def test_section_review_and_protection_remain_independent(self):
        section = self.sections[0]
        response = self.client.post(
            self.url,
            self._post_data(**{f"is_complete_{section.pk}": "on"}),
        )
        self.assertRedirects(response, self.url)

        section.refresh_from_db()
        self.assertTrue(section.is_complete)
        self.assertFalse(section.locked)

        response = self.client.post(
            self.url,
            self._post_data(**{f"locked_{section.pk}": "on"}),
        )
        self.assertRedirects(response, self.url)

        section.refresh_from_db()
        self.assertTrue(section.locked)
        self.assertFalse(section.is_complete)

    def test_substantive_edits_clear_reviewed_state(self):
        section = self.sections[0]
        self.application.description_is_complete = True
        self.application.save(
            update_fields=["description_is_complete", "updated_at"]
        )
        section.is_complete = True
        section.save(update_fields=["is_complete", "updated_at"])

        response = self.client.post(
            self.url,
            self._post_data(
                description="Edited Description of Operations.",
                description_is_complete="on",
                **{
                    f"content_{section.pk}": "Edited section content.",
                    f"is_complete_{section.pk}": "on",
                },
            ),
        )
        self.assertRedirects(response, self.url)

        self.application.refresh_from_db()
        section.refresh_from_db()
        self.assertFalse(self.application.description_is_complete)
        self.assertFalse(section.is_complete)
        self.assertTrue(self.application.locked_description)
        self.assertTrue(section.locked)

    def test_review_textareas_render_fifteen_rows(self):
        response = self.client.get(self.url)

        self.assertContains(response, 'id="description"')
        self.assertContains(response, 'rows="15"', count=10)
        self.assertContains(response, "resize: vertical")

    def test_submission_workflow_stepper_states(self):
        incomplete = _submission_workflow_steps(
            planning_complete=False,
            conops_generated=False,
            conops_stale=False,
            review_complete=False,
            submitted=False,
        )
        self.assertTrue(incomplete[0]["current"])
        self.assertFalse(incomplete[0]["complete"])

        generated = _submission_workflow_steps(
            planning_complete=True,
            conops_generated=True,
            conops_stale=False,
            review_complete=False,
            submitted=False,
        )
        self.assertTrue(generated[0]["complete"])
        self.assertTrue(generated[1]["complete"])
        self.assertTrue(generated[2]["current"])

        reviewed = _submission_workflow_steps(
            planning_complete=True,
            conops_generated=True,
            conops_stale=False,
            review_complete=True,
            submitted=False,
        )
        self.assertTrue(all(step["complete"] for step in reviewed[:3]))
        self.assertTrue(reviewed[3]["current"])
        self.assertFalse(reviewed[3]["complete"])

        submitted = _submission_workflow_steps(
            planning_complete=True,
            conops_generated=True,
            conops_stale=False,
            review_complete=True,
            submitted=True,
        )
        self.assertTrue(all(step["complete"] for step in submitted))

        stale = _submission_workflow_steps(
            planning_complete=True,
            conops_generated=True,
            conops_stale=True,
            review_complete=False,
            submitted=False,
        )
        self.assertTrue(stale[1]["current"])
        self.assertFalse(stale[1]["complete"])

    def test_review_ui_has_separate_document_actions_and_submission_guidance(self):
        self.application.description_is_complete = True
        self.application.ai_generated_at = timezone.now()
        self.application.ai_generation_model = "test-model"
        self.application.conops_source_updated_at = timezone.now()
        self.application.save(
            update_fields=[
                "description_is_complete",
                "ai_generated_at",
                "ai_generation_model",
                "conops_source_updated_at",
                "updated_at",
            ]
        )
        ConopsSection.objects.filter(application=self.application).update(
            is_complete=True
        )

        response = self.client.get(self.url)

        self.assertContains(response, "View Worksheet")
        self.assertContains(response, "Download Worksheet")
        self.assertContains(response, "View CONOPS")
        self.assertContains(response, "Download CONOPS")
        self.assertContains(response, "Copy Description of Operations")
        self.assertContains(response, "Ready to Submit")
        self.assertNotContains(response, "FAA Package")

    def test_generation_loading_state_markup_is_scoped_to_ai_action(self):
        response = self.client.get(self.url)

        self.assertContains(response, 'id="conops-generation-overlay"')
        self.assertContains(response, 'role="status"')
        self.assertContains(response, 'aria-live="polite"')
        self.assertContains(response, "Generating CONOPS…")
        self.assertContains(response, "Please don't leave this page")
        self.assertContains(response, 'id="generate-conops-button"')
        self.assertContains(response, "Generating…")
        self.assertContains(
            response,
            'submitter.value !== "generate_ai"',
        )
        self.assertContains(response, 'aria-busy", "true"')

    @override_settings(
        OPENAI_API_KEY="test-key",
        OPENAI_TEXT_MODEL="test-model",
    )
    @patch("airspace.ai_conops._request_ai_document")
    def test_regeneration_preserves_protected_content(self, request_document):
        protected_section = self.sections[0]
        protected_section.locked = True
        protected_section.save(update_fields=["locked", "updated_at"])
        self.application.locked_description = True
        self.application.save(
            update_fields=["locked_description", "updated_at"]
        )

        package = GeneratedConopsPackage(
            description_of_operations="Regenerated description.",
            sections=[
                GeneratedConopsSection(
                    key=definition.key,
                    title=definition.title,
                    content=f"Regenerated {definition.key}.",
                )
                for definition in CONOPS_DEFINITIONS
            ],
        )
        request_document.return_value = (package, MagicMock(usage=None))

        generate_ai_conops(
            self.approval,
            self.user,
            regenerate_unlocked=True,
        )

        self.application.refresh_from_db()
        protected_section.refresh_from_db()
        unprotected_section = ConopsSection.objects.get(
            pk=self.sections[1].pk
        )
        self.assertEqual(
            self.application.description,
            "Saved Description of Operations.",
        )
        self.assertEqual(
            protected_section.content,
            f"Saved content for {protected_section.title}.",
        )
        self.assertEqual(
            unprotected_section.content,
            f"Regenerated {unprotected_section.section_key}.",
        )

    @override_settings(
        OPENAI_API_KEY="test-key",
        OPENAI_TEXT_MODEL="test-model",
    )
    @patch("airspace.ai_conops._request_ai_document")
    def test_failed_identifier_fidelity_does_not_rewrite_protected_content(
        self, request_document
    ):
        procedure = "Emergency notification will be made to LSV ATC."
        self.operation.emergency_response_plan = procedure
        self.operation.save(update_fields=["emergency_response_plan"])
        protected_section = self.sections[-1]
        protected_section.locked = True
        protected_section.is_complete = True
        protected_section.save(
            update_fields=["locked", "is_complete", "updated_at"]
        )
        original_content = protected_section.content

        request_document.return_value = (
            GeneratedConopsPackage(
                description_of_operations="Regenerated description.",
                sections=[
                    GeneratedConopsSection(
                        key=definition.key,
                        title=definition.title,
                        content=(
                            "Notify Las Vegas Motor Speedway ATC."
                            if definition.key == "emergency-procedures"
                            else f"Regenerated {definition.key}."
                        ),
                    )
                    for definition in CONOPS_DEFINITIONS
                ],
            ),
            MagicMock(usage=None),
        )

        with self.assertRaises(OpenAIConopsError):
            generate_ai_conops(
                self.approval,
                self.user,
                regenerate_unlocked=True,
            )

        protected_section.refresh_from_db()
        self.assertEqual(protected_section.content, original_content)
        self.assertTrue(protected_section.locked)
        self.assertTrue(protected_section.is_complete)


class SubmissionDocumentTests(TestCase):
    def setUp(self):
        ConopsReviewWorkflowTests.setUp(self)
        self.operation.operation_description = (
            "Year-round operatons use the stored applicant text."
        )
        self.operation.local_time_zone = "PST"
        self.operation.dronezone_radius = "0.5_nm"
        self.operation.location_latitude = "36.080000"
        self.operation.location_longitude = "-115.152000"
        self.operation.launch_location = "varies"
        self.operation.recovery_location = "varies"
        self.operation.ground_risk_mitigation = "Stored ground control text."
        self.operation.air_risk_mitigation = "Stored air control text."
        self.operation.emergency_response_plan = "Stored emergency text."
        self.operation.weather_go_nogo = "Stored weather text."
        self.operation.atc_facility_name = "LSV ATC"
        self.operation.save()
        self.worksheet_url = reverse(
            "airspace:operation_application_worksheet_pdf",
            kwargs={
                "operation_pk": self.operation.pk,
                "approval_pk": self.approval.pk,
            },
        )
        self.conops_pdf_url = reverse(
            "airspace:operation_conops_pdf",
            kwargs={
                "operation_pk": self.operation.pk,
                "approval_pk": self.approval.pk,
            },
        )

    @staticmethod
    def _pdf_text(content):
        return "\n".join(
            page.extract_text() or ""
            for page in PdfReader(BytesIO(content)).pages
        )

    def test_worksheet_is_applicant_reference_and_preserves_source_data(self):
        response = self.client.get(self.worksheet_url)
        text = self._pdf_text(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertIn("FAA DroneZone Application Worksheet", text)
        self.assertIn("PRIVATE APPLICANT PLANNING REFERENCE", text)
        self.assertIn("DroneZone Requested Radius", text)
        self.assertIn("1/2 NM", text)
        self.assertNotIn("Launch-site radius", text)
        self.assertIn("Operation Reference Latitude", text)
        self.assertIn("Launch Location", text)
        self.assertGreaterEqual(text.count("varies"), 2)
        self.assertIn("Year-round operatons", text)
        self.assertIn("Supporting Planning Information", text)
        self.assertIn("Stored emergency text.", text)
        self.assertIn("Stored weather text.", text)
        self.assertIn("LSV ATC", text)
        self.assertNotIn("Las Vegas ATC", text)
        self.assertIn("Pacific Time (PT)", text)
        self.assertNotIn("Pacific Standard Time", text)
        self.assertNotIn("Concept of Operations (CONOPS)", text)

    def test_timezone_display_uses_dst_safe_regional_name(self):
        self.assertEqual(
            _operation_timezone_display(self.operation),
            "Pacific Time (PT)",
        )

    def test_standalone_conops_excludes_worksheet_sections(self):
        response = self.client.get(self.conops_pdf_url)
        text = self._pdf_text(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertIn("CONCEPT OF OPERATIONS", text)
        self.assertIn("Appendix A — Operations Area Map", text)
        self.assertIn("No operations area map is available", text)
        self.assertNotIn("FAA DroneZone Application Worksheet", text)
        self.assertNotIn("Supporting Planning Information", text)
        self.assertIn("Draft — RPIC review required", text)

    def test_image_map_is_embedded_without_private_location_leakage(self):
        image = Image.new("RGB", (1200, 800), color=(20, 90, 140))
        image_bytes = BytesIO()
        image.save(image_bytes, format="PNG")

        with TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            self.operation.operation_map.save(
                "private-map.png",
                SimpleUploadedFile(
                    "private-map.png",
                    image_bytes.getvalue(),
                    content_type="image/png",
                ),
            )
            response = self.client.get(self.conops_pdf_url)
            reader = PdfReader(BytesIO(response.content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Appendix A — Operations Area Map", text)
        self.assertNotIn("No operations area map is available", text)
        self.assertNotIn("operation_maps/", text)
        self.assertNotIn("private-map.png", text)
        self.assertTrue(any(page.images for page in reader.pages))

    def _pdf_map_response(self, page_count):
        map_buffer = BytesIO()
        map_writer = PdfWriter()
        for _ in range(page_count):
            map_writer.add_blank_page(width=612, height=792)
        map_writer.write(map_buffer)

        with TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            self.operation.operation_map.save(
                "private-map.pdf",
                SimpleUploadedFile(
                    "private-map.pdf",
                    map_buffer.getvalue(),
                    content_type="application/pdf",
                ),
            )
            response = self.client.get(self.conops_pdf_url)
            reader = PdfReader(BytesIO(response.content))
            texts = [page.extract_text() or "" for page in reader.pages]

        return response, reader, texts

    def test_single_page_pdf_map_is_first_appendix_page_and_numbered(self):
        response, reader, texts = self._pdf_map_response(1)
        text = "\n".join(texts)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Appendix A — Operations Area Map", texts[-1])
        self.assertEqual(text.count("Appendix A — Operations Area Map"), 1)
        self.assertNotIn("operation_maps/", text)
        self.assertNotIn("private-map.pdf", text)
        self.assertIn(
            f"Page {len(reader.pages)} of {len(reader.pages)}",
            texts[-1],
        )

    def test_multi_page_pdf_map_all_pages_share_final_page_total(self):
        single_response, single_reader, _ = self._pdf_map_response(1)
        response, reader, texts = self._pdf_map_response(2)
        text = "\n".join(texts)

        self.assertEqual(single_response.status_code, 200)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(reader.pages), len(single_reader.pages) + 1)
        self.assertIn("Appendix A — Operations Area Map", texts[-2])
        self.assertNotIn("Appendix A — Operations Area Map", texts[-1])
        self.assertEqual(text.count("Appendix A — Operations Area Map"), 1)
        self.assertIn(
            f"Page {len(reader.pages) - 1} of {len(reader.pages)}",
            texts[-2],
        )
        self.assertIn(
            f"Page {len(reader.pages)} of {len(reader.pages)}",
            texts[-1],
        )


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
