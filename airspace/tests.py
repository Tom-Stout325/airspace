from unittest.mock import MagicMock, PropertyMock, patch
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
    _ensure_additional_operational_information,
    _canonicalize_structured_facts,
    _ensure_crewed_aircraft_response,
    _ensure_emergency_airspace_conflict_reference,
    _ensure_operation_reference_coordinates,
    _ensure_operations_over_people_avoided,
    _source_fidelity_requirements,
    _system_prompt,
    _validate_discrete_source_fidelity,
    _validate_geometry_source_fidelity,
    _validate_package,
    EMERGENCY_AIRSPACE_CONFLICT_REFERENCE,
    generate_ai_conops,
)
from .conops import (
    CONOPS_DEFINITIONS,
    OPERATIONS_OVER_PEOPLE_AVOIDED,
    _airspace_atc_coordination,
    _area_and_containment,
    _crewed_aircraft_conflict_response,
    _dates_location_airspace,
    _emergency_procedures,
    _flight_envelope_limitations,
    _operation_overview,
    _operational_risk_controls,
    _operations_over_people,
    _see_and_avoid,
    get_or_create_application,
)
from .forms import OperationsPlanningForm
from .models import (
    Airport,
    ApprovalType,
    CREWED_AIRCRAFT_CONFLICT_RESPONSE_NO_VO,
    CREWED_AIRCRAFT_CONFLICT_RESPONSE_VO,
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
from .views import (
    _invalidate_operation_conops,
    _operation_timezone_display,
    _submission_workflow_steps,
)

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

    def test_new_record_has_standard_vo_conflict_response_default(self):
        operation = OperationsPlanning(
            user=self.owner,
            operation_title="New default test",
            start_date=date.today(),
        )
        self.assertEqual(
            operation.crewed_aircraft_conflict_response,
            CREWED_AIRCRAFT_CONFLICT_RESPONSE_VO,
        )

    def test_form_uses_vo_or_no_vo_standard_and_allows_custom_text(self):
        with_vo = OperationsPlanningForm(
            data=self.operation_form_data(has_visual_observer="on"),
            user=self.owner,
        )
        self.assertTrue(with_vo.is_valid(), with_vo.errors)
        self.assertEqual(
            with_vo.cleaned_data["crewed_aircraft_conflict_response"],
            CREWED_AIRCRAFT_CONFLICT_RESPONSE_VO,
        )

        without_vo = OperationsPlanningForm(
            data=self.operation_form_data(),
            user=self.owner,
        )
        self.assertTrue(without_vo.is_valid(), without_vo.errors)
        self.assertEqual(
            without_vo.cleaned_data["crewed_aircraft_conflict_response"],
            CREWED_AIRCRAFT_CONFLICT_RESPONSE_NO_VO,
        )

        custom = (
            "The RPIC will immediately land and yield right of way to all "
            "crewed aircraft."
        )
        edited = OperationsPlanningForm(
            data=self.operation_form_data(
                crewed_aircraft_conflict_response=custom,
            ),
            user=self.owner,
        )
        self.assertTrue(edited.is_valid(), edited.errors)
        self.assertEqual(
            edited.cleaned_data["crewed_aircraft_conflict_response"],
            custom,
        )

    def test_no_vo_rejects_custom_visual_observer_reference(self):
        form = OperationsPlanningForm(
            data=self.operation_form_data(
                crewed_aircraft_conflict_response=(
                    "The Visual Observer will report traffic to the RPIC."
                ),
            ),
            user=self.owner,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("crewed_aircraft_conflict_response", form.errors)

    def test_changing_conflict_response_marks_generated_conops_stale(self):
        approval_type = ApprovalType.objects.create(
            code="conflict-response-stale-test",
            category="airspace",
            regulation="§107.41",
            name="Controlled Airspace Authorization",
        )
        approval = OperationApproval.objects.create(
            operation=self.operation,
            approval_type=approval_type,
        )
        application = get_or_create_application(approval, self.owner)
        application.conops_source_updated_at = timezone.now()
        application.save(
            update_fields=["conops_source_updated_at", "updated_at"]
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "airspace:operations_planning_edit",
                kwargs={"pk": self.operation.pk},
            ),
            self.operation_form_data(
                operation_title=self.operation.operation_title,
                crewed_aircraft_conflict_response=(
                    "The RPIC will land and yield to crewed aircraft."
                ),
            ),
        )

        self.assertRedirects(
            response,
            reverse(
                "airspace:operations_planning_detail",
                kwargs={"pk": self.operation.pk},
            ),
        )
        application.refresh_from_db()
        self.assertIsNone(application.conops_source_updated_at)

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

    def test_multiple_sites_blanket_area_creates_without_corridor_dimensions(self):
        form = OperationsPlanningForm(
            data=self.operation_form_data(
                operation_area_type="multiple_sites",
                dronezone_radius="blanket_wide_area",
                launch_location="Varies",
                recovery_location="Varies",
            ),
            user=self.owner,
        )

        self.assertTrue(form.is_valid(), form.errors)
        operation = form.save()
        self.assertEqual(operation.operation_area_type, "multiple_sites")
        self.assertIsNone(operation.corridor_length_ft)
        self.assertIsNone(operation.corridor_width_ft)

    def test_defined_site_creates_without_corridor_dimensions(self):
        form = OperationsPlanningForm(
            data=self.operation_form_data(operation_area_type="site"),
            user=self.owner,
        )

        self.assertTrue(form.is_valid(), form.errors)
        operation = form.save()
        self.assertEqual(operation.operation_area_type, "site")
        self.assertIsNone(operation.corridor_length_ft)
        self.assertIsNone(operation.corridor_width_ft)

    def test_corridor_validation_uses_normal_form_errors(self):
        form = OperationsPlanningForm(
            data=self.operation_form_data(operation_area_type="corridor"),
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("corridor_length_ft", form.errors)
        self.assertIn("corridor_width_ft", form.errors)

    def test_corridor_dimensions_are_exposed_and_saved(self):
        form = OperationsPlanningForm(
            data=self.operation_form_data(
                operation_area_type="corridor",
                corridor_length_ft="5280",
                corridor_width_ft="500",
            ),
            user=self.owner,
        )

        self.assertIn("corridor_length_ft", form.fields)
        self.assertIn("corridor_width_ft", form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        operation = form.save()
        self.assertEqual(operation.corridor_length_ft, 5280)
        self.assertEqual(operation.corridor_width_ft, 500)

    def test_existing_corridor_record_loads_in_edit_form(self):
        self.operation.operation_area_type = "corridor"
        self.operation.corridor_length_ft = 2640
        self.operation.corridor_width_ft = 300
        self.operation.save()

        form = OperationsPlanningForm(instance=self.operation, user=self.owner)

        self.assertEqual(form["corridor_length_ft"].value(), 2640)
        self.assertEqual(form["corridor_width_ft"].value(), 300)

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

    def test_standard_crewed_aircraft_response_tracks_vo_selection(self):
        self.operation.has_visual_observer = True
        self.operation.crewed_aircraft_conflict_response = (
            CREWED_AIRCRAFT_CONFLICT_RESPONSE_VO
        )
        with_vo = _crewed_aircraft_conflict_response(self.operation)
        self.assertIn("Visual Observer continues reporting", with_vo)
        self.assertIn("yield right of way", with_vo)

        self.operation.has_visual_observer = False
        self.operation.crewed_aircraft_conflict_response = (
            CREWED_AIRCRAFT_CONFLICT_RESPONSE_NO_VO
        )
        without_vo = _crewed_aircraft_conflict_response(self.operation)
        self.assertNotIn("Visual Observer", without_vo)
        self.assertIn("maintain separation and yield right of way", without_vo)
        form = OperationsPlanningForm(
            data={
                "status": OperationsPlanning.Status.DRAFT,
                "operation_title": "No VO operation",
                "start_date": date.today().isoformat(),
                "operation_area_type": "site",
            },
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_section_four_contains_authoritative_stored_response(self):
        stored = (
            "Custom stored response: descend, reposition, land, report the "
            "aircraft position and trajectory, resolve the conflict, and "
            "yield right of way."
        )
        self.operation.crewed_aircraft_conflict_response = stored
        self.operation.save(
            update_fields=["crewed_aircraft_conflict_response"]
        )

        self.assertIn(stored, _see_and_avoid(self.approval))
        payload = _operation_payload(self.approval)
        self.assertEqual(
            payload["operation"]["crewed_aircraft_conflict_response"],
            stored,
        )

        package = self._geometry_package("Valid generated overview.")
        see_and_avoid = next(
            section
            for section in package.sections
            if section.key == "see-and-avoid"
        )
        see_and_avoid.content = "AI-generated shortened response."
        _ensure_crewed_aircraft_response(package, self.operation)
        self.assertEqual(
            see_and_avoid.content,
            "AI-generated shortened response.\n\n" + stored,
        )

    def test_section_four_removes_duplicate_response_actions(self):
        stored = CREWED_AIRCRAFT_CONFLICT_RESPONSE_VO
        self.operation.has_visual_observer = True
        self.operation.crewed_aircraft_conflict_response = stored
        package = self._geometry_package("Valid generated overview.")
        section = next(
            item for item in package.sections if item.key == "see-and-avoid"
        )
        section.content = (
            "A Visual Observer will continuously monitor the operating area "
            "for crewed aircraft. FlightAware is used as a supplemental "
            "situational-awareness tool and does not replace visual scanning, "
            "see-and-avoid responsibilities, or the RPIC's obligation to yield "
            "right of way to crewed aircraft. Upon detecting a crewed aircraft, "
            "the RPIC will descend, reposition, or land to resolve the conflict. "
            + stored
        )

        _ensure_crewed_aircraft_response(package, self.operation)

        self.assertEqual(section.content.count(stored), 1)
        self.assertEqual(section.content.casefold().count("descend"), 1)
        self.assertIn("Visual Observer will continuously monitor", section.content)
        self.assertIn("FlightAware is used as a supplemental", section.content)

    def test_no_vo_and_custom_responses_remain_authoritative(self):
        self.operation.has_visual_observer = False
        self.operation.crewed_aircraft_conflict_response = (
            CREWED_AIRCRAFT_CONFLICT_RESPONSE_NO_VO
        )
        package = self._geometry_package("Valid generated overview.")
        section = next(
            item for item in package.sections if item.key == "see-and-avoid"
        )
        section.content = "The RPIC will scan continuously for crewed aircraft."
        _ensure_crewed_aircraft_response(package, self.operation)
        self.assertNotIn("Visual Observer", section.content)
        self.assertEqual(
            section.content.count(CREWED_AIRCRAFT_CONFLICT_RESPONSE_NO_VO),
            1,
        )

        custom = "Custom authoritative conflict response text."
        self.operation.crewed_aircraft_conflict_response = custom
        _ensure_crewed_aircraft_response(package, self.operation)
        self.assertTrue(section.content.endswith(custom))

    def test_additional_information_is_routed_and_preserved(self):
        information = (
            "RPIC has flown sUAS operations at this location for 11 events "
            "over five years, including March 2026 under FAA Form 7711-1 "
            "2026-P107-WSA-07645. This application mirrors parameters of "
            "that earlier approved waiver."
        )
        self.operation.additional_operational_information = information
        package = self._geometry_package("Valid generated overview.")

        _ensure_additional_operational_information(package, self.operation)

        overview = next(
            item for item in package.sections if item.key == "operational-overview"
        )
        self.assertIn(information, overview.content)
        self.assertIn("2026-P107-WSA-07645", overview.content)
        self.assertNotIn("current application is approved", overview.content)
        self.assertIn(
            "2026-P107-WSA-07645",
            _source_fidelity_requirements(self.operation),
        )
        prompt = _system_prompt()
        self.assertIn("must remain historical context", prompt)
        self.assertIn("special provisions must not be presented as current", prompt.casefold())

    def test_additional_atc_history_remains_historical_and_blank_adds_nothing(self):
        package = self._geometry_package("Valid generated overview.")
        original = [item.content for item in package.sections]
        self.operation.additional_operational_information = ""
        _ensure_additional_operational_information(package, self.operation)
        self.assertEqual([item.content for item in package.sections], original)

        history = "The RPIC previously worked with KPOC ATC at this location."
        self.operation.additional_operational_information = history
        _ensure_additional_operational_information(package, self.operation)
        atc = next(
            item
            for item in package.sections
            if item.key == "airspace-atc-coordination"
        )
        self.assertIn(history, atc.content)
        self.assertNotIn("KPOC ATC has approved", atc.content)
        self.assertNotIn("coordination has been conducted", atc.content)

    def test_operations_over_people_choices_are_deterministic(self):
        expected = {
            "avoided": OPERATIONS_OVER_PEOPLE_AVOIDED,
            "part_107_compliant": "applicable Part 107 Operations Over People category",
            "separate_relief": "separate FAA relief or approval",
            "requires_review": "requires further review",
        }
        for value, wording in expected.items():
            with self.subTest(value=value):
                self.operation.operations_over_people = value
                self.assertIn(wording, _operations_over_people(self.operation))

        self.operation.operations_over_people = "avoided"
        self.operation.crowd_mitigation = "Use controlled spectator barriers."
        self.assertIn(
            "Use controlled spectator barriers.",
            _operations_over_people(self.operation),
        )
        self.operation.operations_over_people = ""
        self.operation.crowd_mitigation = ""
        self.operation.ground_environment = ["crowd_dense"]
        payload = _operation_payload(self.approval)
        self.assertEqual(
            payload["airspace_standard_procedures"]["operations_over_people"],
            "",
        )

    def test_avoided_operations_over_people_is_inserted_exactly_once(self):
        self.operation.operations_over_people = "avoided"
        package = self._geometry_package("Valid generated overview.")
        section = next(
            item
            for item in package.sections
            if item.key == "flight-envelope-limitations"
        )
        section.content = (
            "Generated flight limitations that omit operations over people."
        )

        _ensure_operations_over_people_avoided(package, self.operation)
        _ensure_operations_over_people_avoided(package, self.operation)

        self.assertEqual(
            section.content.count(OPERATIONS_OVER_PEOPLE_AVOIDED),
            1,
        )
        self.assertTrue(section.content.endswith(OPERATIONS_OVER_PEOPLE_AVOIDED))

    def test_other_operations_over_people_choices_are_not_post_processed(self):
        for value in (
            "part_107_compliant",
            "separate_relief",
            "requires_review",
        ):
            with self.subTest(value=value):
                self.operation.operations_over_people = value
                package = self._geometry_package("Valid generated overview.")
                section = next(
                    item
                    for item in package.sections
                    if item.key == "flight-envelope-limitations"
                )
                original = section.content
                _ensure_operations_over_people_avoided(package, self.operation)
                self.assertEqual(section.content, original)

    def test_boundary_additional_information_and_corridor_reach_context(self):
        self.operation.operation_area_type = "corridor"
        self.operation.corridor_length_ft = 1200
        self.operation.corridor_width_ft = 300
        self.operation.operational_boundary_description = (
            "Remain north of Service Road A and outside the runway boundary."
        )
        self.operation.additional_operational_information = (
            "The RPIC has prior experience coordinating with KPOC ATC."
        )
        self.operation.save()

        area = _area_and_containment(self.approval)
        self.assertIn("1,200 feet long by 300 feet wide", area)
        self.assertIn("Remain north of Service Road A", area)
        self.assertIn(
            self.operation.additional_operational_information,
            _operational_risk_controls(self.approval),
        )
        payload = _operation_payload(self.approval)
        self.assertEqual(
            payload["operation_semantics"]["corridor_dimensions"],
            {"length_ft": 1200, "width_ft": 300},
        )
        self.assertEqual(
            payload["operation"]["additional_operational_information"],
            self.operation.additional_operational_information,
        )
        prompt = _system_prompt()
        self.assertIn("must remain historical context", prompt)
        self.assertNotIn("Coordination with KPOC ATC has been conducted", area)

        self.operation.operation_area_type = "site"
        self.assertNotIn("1,200 feet", _area_and_containment(self.approval))

    def test_blank_optional_context_does_not_fabricate_boundaries(self):
        self.operation.operational_boundary_description = ""
        self.operation.additional_operational_information = ""
        payload = _operation_payload(self.approval)

        self.assertEqual(
            payload["operation_semantics"]["operational_boundary_description"],
            "",
        )
        self.assertNotIn(
            "Operational boundaries:",
            _area_and_containment(self.approval),
        )
        model_fields = {field.name for field in OperationsPlanning._meta.fields}
        self.assertNotIn("prior_waiver", model_fields)
        self.assertNotIn("previous_authorization", model_fields)

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

    def test_atc_contact_values_do_not_invent_current_coordination(self):
        self.operation.atc_facility_name = "KPOC ATC"
        self.operation.atc_frequency = "123.45 MHz"
        self.operation.atc_phone = "909-555-0100"
        self.operation.atc_checkin_procedure = ""
        self.operation.additional_operational_information = (
            "The RPIC has prior experience coordinating with KPOC ATC."
        )
        self.operation.save()

        text = _airspace_atc_coordination(self.approval)
        self.assertIn("KPOC ATC", text)
        self.assertIn("123.45 MHz", text)
        self.assertIn("909-555-0100", text)
        self.assertNotIn("must call", text.casefold())
        self.assertNotIn("must monitor", text.casefold())
        self.assertNotIn("coordination has been conducted", text.casefold())
        self.assertIn(
            self.operation.additional_operational_information,
            _operational_risk_controls(self.approval),
        )

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
            "Preserve every substantive action in user-entered emergency and ATC",
            prompt,
        )
        self.assertIn("Preserve user-entered facility identifiers exactly", prompt)

    def _package_with_emergency_text(self, emergency_text):
        sections = [
            GeneratedConopsSection(
                key=definition.key,
                title=definition.title,
                content=(
                    emergency_text
                    if definition.key == "emergency-procedures"
                    else f"Content for {definition.key}."
                ),
            )
            for definition in CONOPS_DEFINITIONS
        ]
        return GeneratedConopsPackage(
            description_of_operations="Controlled-airspace operation.",
            sections=sections,
        )

    def test_narrative_procedures_allow_professional_rewriting(self):
        self.operation.emergency_response_plan = (
            "Immediately land at pre-determined emergency landing zones "
            "on access roads"
        )
        self.operation.flyaway_actions = (
            "RPIC will attempt to regain control of the aircraft and will "
            "note location, direction, altitude and speed, and will notify "
            "LSV ATC if unable to regain control of the aircraft"
        )
        exact_identifiers = _source_fidelity_requirements(
            self.operation
        )
        rewritten = self._package_with_emergency_text(
            "The aircraft will land in preselected emergency areas located "
            "along access roads. If control cannot be restored, the RPIC "
            "will contact LSV ATC."
        )

        _validate_package(
            rewritten,
            required_exact_identifiers=exact_identifiers,
        )

    def test_flyaway_procedure_requires_exact_lsv_atc_identifier(self):
        self.operation.flyaway_actions = (
            "RPIC will attempt to regain control of the aircraft and will "
            "note location, direction, altitude and speed, and will notify "
            "LSV ATC if unable to regain control of the aircraft"
        )
        exact_identifiers = _source_fidelity_requirements(
            self.operation
        )
        expanded = self._package_with_emergency_text(
            "The RPIC will attempt to regain control while recording the "
            "aircraft's location, direction, altitude, and speed. If control "
            "cannot be regained, notify Las Vegas Motor Speedway ATC."
        )

        with self.assertRaisesRegex(OpenAIConopsError, "LSV ATC"):
            _validate_package(
                expanded,
                required_exact_identifiers=exact_identifiers,
            )

    def test_contact_values_embedded_in_narrative_remain_exact(self):
        self.operation.flyaway_actions = (
            "Contact LSV ATC on 123.45 MHz at 702-555-0188 and maintain "
            "the 390 feet AGL RTH limit during a flyaway."
        )
        exact_identifiers = _source_fidelity_requirements(self.operation)

        self.assertEqual(
            exact_identifiers,
            ("LSV ATC", "702-555-0188", "123.45 MHz"),
        )
        for changed in (
            "Contact LSV ATC on 123.40 MHz at 702-555-0188; limit 390.",
            "Contact LSV ATC on 123.45 MHz at 702-555-0199; limit 390.",
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(OpenAIConopsError):
                    _validate_package(
                        self._package_with_emergency_text(changed),
                        required_exact_identifiers=exact_identifiers,
                    )

    def test_discrete_coordinates_altitude_and_dates_are_strict(self):
        self.operation.location_latitude = "36.271187"
        self.operation.location_longitude = "-115.009416"
        self.operation.maximum_planned_altitude_agl = 400
        self.operation.start_date = date(2026, 10, 1)
        self.operation.end_date = date(2027, 12, 31)
        self.operation.save()
        valid = self._geometry_package(
            "Reference coordinates are 36.271187, -115.009416. The requested "
            "maximum is 400 feet AGL. Operations run October 1, 2026 through "
            "December 31, 2027."
        )
        _validate_discrete_source_fidelity(valid, self.operation)

        replacements = (
            ("36.271187", "36.271188"),
            ("400 feet AGL", "300 feet AGL"),
            ("October 1, 2026", "October 2, 2026"),
        )
        for old, new in replacements:
            with self.subTest(new=new):
                changed = self._geometry_package(
                    valid.description_of_operations.replace(old, new)
                )
                with self.assertRaises(OpenAIConopsError):
                    _validate_discrete_source_fidelity(changed, self.operation)

    def test_aircraft_registration_is_optional_but_cannot_be_substituted(self):
        drone = Drone.objects.create(
            user=self.user,
            manufacturer="DJI",
            model="Mavic 4 Pro",
            serial_number="SERIAL-REGISTRATION-FACTS",
            faa_registration_number="faeid42",
        )
        OperationAircraft.objects.create(
            operation=self.operation,
            drone=drone,
        )
        required_facts = (
            "The requested maximum is 375 feet AGL. The operation begins "
            f"{self.operation.start_date.isoformat()}. "
        )

        accepted = (
            "The assigned aircraft is a DJI Mavic 4 Pro.",
            "The DJI Mavic 4 Pro has FAA registration faeid42.",
            "The DJI Mavic 4 Pro has FAA registration FAEID42.",
            "The assigned Mavic 4 Pro is registered as faeid42.",
        )
        for text in accepted:
            with self.subTest(text=text):
                _validate_discrete_source_fidelity(
                    self._geometry_package(required_facts + text),
                    self.operation,
                )

        rejected = (
            "The DJI Mavic 4 Pro has FAA registration faeid43.",
            "The assigned aircraft has FAA registration N123AB.",
            "The assigned Mavic 4 Pro is registered as N123AB.",
        )
        for text in rejected:
            with self.subTest(text=text):
                with self.assertRaises(OpenAIConopsError):
                    _validate_discrete_source_fidelity(
                        self._geometry_package(required_facts + text),
                        self.operation,
                    )

        canonical = self._geometry_package(
            required_facts
            + "The DJI Mavic 4 Pro has FAA registration FAEID42."
        )
        _canonicalize_structured_facts(canonical, self.operation)
        self.assertIn("FAA registration faeid42", canonical.description_of_operations)
        self.assertNotIn("FAEID42", canonical.description_of_operations)

    def test_coordinate_equivalence_is_numeric_and_canonicalized(self):
        self.operation.location_latitude = "34.099076"
        self.operation.location_longitude = "-117.775772"
        self.operation.save(
            update_fields=["location_latitude", "location_longitude"]
        )
        required = (
            "The requested maximum is 375 ft AGL. The operation begins "
            f"{self.operation.start_date.isoformat()}. Reference coordinates "
            "are 34.0990760, -117.77577200."
        )
        package = self._geometry_package(required)

        _validate_discrete_source_fidelity(package, self.operation)
        _canonicalize_structured_facts(package, self.operation)

        self.assertIn("34.099076, -117.775772", package.description_of_operations)

        changed = self._geometry_package(
            required.replace("34.0990760", "34.0991760")
        )
        with self.assertRaises(OpenAIConopsError):
            _validate_discrete_source_fidelity(changed, self.operation)

        omitted = self._geometry_package(
            "The requested maximum is 375 feet AGL. The operation begins "
            f"{self.operation.start_date.isoformat()}."
        )
        _validate_discrete_source_fidelity(omitted, self.operation)

    def test_section_two_gets_one_canonical_operation_reference_point(self):
        self.operation.location_latitude = "34.099076"
        self.operation.location_longitude = "-117.775772"
        package = self._geometry_package("Valid generated overview.")
        section = next(
            item
            for item in package.sections
            if item.key == "operational-area-airspace"
        )
        section.content = (
            "The mapped area defines the operation. The operation reference "
            "coordinates are 34.0990760, -117.7757720."
        )

        _ensure_operation_reference_coordinates(package, self.operation)
        _ensure_operation_reference_coordinates(package, self.operation)

        canonical = (
            "The operation reference point is latitude 34.099076, "
            "longitude -117.775772."
        )
        self.assertEqual(section.content.count(canonical), 1)
        self.assertIn("The mapped area defines the operation.", section.content)

        self.operation.location_longitude = None
        blank_package = self._geometry_package("Valid generated overview.")
        blank_section = next(
            item
            for item in blank_package.sections
            if item.key == "operational-area-airspace"
        )
        original = blank_section.content
        _ensure_operation_reference_coordinates(blank_package, self.operation)
        self.assertEqual(blank_section.content, original)

    def test_launch_and_reference_coordinate_roles_remain_distinct(self):
        self.operation.location_latitude = "34.099076"
        self.operation.location_longitude = "-117.775772"
        self.operation.launch_latitude = "34.092603"
        self.operation.launch_longitude = "-117.771812"
        self.operation.save(
            update_fields=[
                "location_latitude",
                "location_longitude",
                "launch_latitude",
                "launch_longitude",
            ]
        )
        required = (
            "The requested maximum is 375 feet AGL. The operation begins "
            f"{self.operation.start_date.isoformat()}. "
        )
        correct_launch = self._geometry_package(
            required
            + "The launch site is located at latitude 34.092603, longitude "
            "-117.771812."
        )
        _validate_discrete_source_fidelity(correct_launch, self.operation)
        _validate_geometry_source_fidelity(correct_launch, self.operation)

        both_roles = self._geometry_package(
            required
            + "The launch site is located at latitude 34.092603, longitude "
            "-117.771812. The operation reference point is latitude "
            "34.099076, longitude -117.775772. An emergency landing area "
            "is near 34.090000, -117.770000."
        )
        _validate_discrete_source_fidelity(both_roles, self.operation)
        _validate_geometry_source_fidelity(both_roles, self.operation)

        launch_then_reference_context = self._geometry_package(
            required
            + "The launch site is located at latitude 34.092603, longitude "
            "-117.771812, while the operation reference point identifies the "
            "overall mapped area. An unrelated supported point is 34.090000, "
            "-117.770000."
        )
        _validate_discrete_source_fidelity(
            launch_then_reference_context,
            self.operation,
        )

        launch_as_reference = self._geometry_package(
            required
            + "The operation reference coordinates are 34.092603, "
            "-117.771812."
        )
        with self.assertRaises(OpenAIConopsError):
            _validate_discrete_source_fidelity(
                launch_as_reference,
                self.operation,
            )

        reference_as_launch = self._geometry_package(
            required
            + "The launch coordinates are 34.099076, -117.775772."
        )
        with self.assertRaises(OpenAIConopsError):
            _validate_geometry_source_fidelity(
                reference_as_launch,
                self.operation,
            )

    def test_altitude_unit_and_radius_numeric_equivalence(self):
        self.operation.maximum_planned_altitude_agl = 75
        self.operation.dronezone_radius = "0.5_nm"
        self.operation.save(
            update_fields=[
                "maximum_planned_altitude_agl",
                "dronezone_radius",
            ]
        )
        facts = (
            "The requested maximum is 75 ft AGL. The operation begins "
            f"{self.operation.start_date.isoformat()}. The requested radius "
            "is 0.50 nautical miles."
        )
        package = self._geometry_package(facts)
        _validate_discrete_source_fidelity(package, self.operation)
        _validate_geometry_source_fidelity(package, self.operation)

        wrong_altitude = self._geometry_package(
            facts.replace("75 ft AGL", "100 ft AGL")
        )
        with self.assertRaises(OpenAIConopsError):
            _validate_discrete_source_fidelity(wrong_altitude, self.operation)

        wrong_radius = self._geometry_package(
            facts.replace("0.50 nautical miles", "1 NM")
        )
        with self.assertRaises(OpenAIConopsError):
            _validate_geometry_source_fidelity(wrong_radius, self.operation)

    def test_section_nine_uses_section_four_conflict_reference(self):
        stored = CREWED_AIRCRAFT_CONFLICT_RESPONSE_VO
        self.operation.has_visual_observer = True
        self.operation.crewed_aircraft_conflict_response = stored
        package = self._geometry_package("Valid generated overview.")
        section_four = next(
            item for item in package.sections if item.key == "see-and-avoid"
        )
        section_nine = next(
            item
            for item in package.sections
            if item.key == "emergency-procedures"
        )
        section_four.content = "Visual scanning context. " + stored
        section_nine.content = (
            "Lost-link procedures remain in effect. Airspace Conflict: Upon "
            "detecting crewed aircraft, the RPIC will descend, reposition, "
            "or land as necessary until the conflict is resolved."
        )

        _ensure_crewed_aircraft_response(package, self.operation)
        _ensure_emergency_airspace_conflict_reference(package)
        _ensure_emergency_airspace_conflict_reference(package)

        self.assertEqual(section_four.content.count(stored), 1)
        self.assertNotIn("descend, reposition", section_nine.content)
        self.assertEqual(
            section_nine.content.count(EMERGENCY_AIRSPACE_CONFLICT_REFERENCE),
            1,
        )
        self.assertIn("Lost-link procedures remain in effect.", section_nine.content)

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
        _validate_geometry_source_fidelity(
            self._geometry_package(
                "Operations use the requested 0.5 NM radius."
            ),
            self.operation,
        )
        with self.assertRaises(OpenAIConopsError):
            _validate_geometry_source_fidelity(
                self._geometry_package(
                    "Operations use the requested 1 NM radius."
                ),
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

        natural_descriptions = (
            "Operations will occur at multiple locations throughout the "
            "mapped operational area. Launch and recovery locations will "
            "vary throughout the approved operating area.",
            "Operations will remain within the mapped property boundaries.",
            "This is a wide-area operation with varying launch and recovery "
            "locations.",
        )
        for description in natural_descriptions:
            with self.subTest(description=description):
                _validate_geometry_source_fidelity(
                    self._geometry_package(description),
                    self.operation,
                )

        for contradiction in (
            "Flights use an authorized 0.5 nautical mile radius.",
            "Flights remain within a 1 NM radius.",
        ):
            with self.subTest(contradiction=contradiction):
                with self.assertRaises(OpenAIConopsError):
                    _validate_geometry_source_fidelity(
                        self._geometry_package(contradiction),
                        self.operation,
                    )
        with self.assertRaises(OpenAIConopsError):
            _validate_geometry_source_fidelity(
                self._geometry_package(
                    valid + " The launch site is at latitude 36.271187."
                ),
                self.operation,
            )
        with self.assertRaises(OpenAIConopsError):
            _validate_geometry_source_fidelity(
                self._geometry_package(
                    valid + " Operations use one fixed site."
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

    def test_newly_reviewed_edits_can_be_completed_on_the_same_save(self):
        section = self.sections[0]

        response = self.client.post(
            self.url,
            self._post_data(
                description="Final reviewed Description of Operations.",
                description_is_complete="on",
                **{
                    f"content_{section.pk}": "Final reviewed section content.",
                    f"is_complete_{section.pk}": "on",
                },
            ),
        )
        self.assertRedirects(response, self.url)

        self.application.refresh_from_db()
        section.refresh_from_db()
        self.assertTrue(self.application.description_is_complete)
        self.assertIsNotNone(self.application.description_validated_at)
        self.assertTrue(section.is_complete)
        self.assertIsNotNone(section.validated_at)

    def test_all_ten_reviews_advance_workflow_to_submit_current(self):
        generated_at = timezone.now()
        self.application.ai_generated_at = generated_at
        self.application.ai_generation_model = "test-model"
        self.application.conops_source_updated_at = generated_at
        self.application.save(
            update_fields=[
                "ai_generated_at",
                "ai_generation_model",
                "conops_source_updated_at",
                "updated_at",
            ]
        )
        post_data = self._post_data(description_is_complete="on")
        for section in self.sections:
            post_data[f"is_complete_{section.pk}"] = "on"

        response = self.client.post(self.url, post_data)
        self.assertRedirects(response, self.url)
        with patch.object(
            OperationsPlanning,
            "completion_percentage",
            new_callable=PropertyMock,
            return_value=100,
        ):
            response = self.client.get(self.url)

        self.assertEqual(response.context["complete_count"], 10)
        self.assertEqual(response.context["total_count"], 10)
        self.assertEqual(response.context["review_percentage"], 100)
        self.assertContains(response, "10 of 10 items reviewed")
        steps = response.context["submission_workflow_steps"]
        self.assertTrue(steps[2]["complete"])
        self.assertFalse(steps[2]["current"])
        self.assertTrue(steps[3]["current"])
        self.assertFalse(steps[3]["complete"])

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
    def test_regeneration_inserts_omitted_operation_reference_coordinates(
        self, request_document
    ):
        self.operation.location_latitude = "34.099076"
        self.operation.location_longitude = "-117.775772"
        self.operation.launch_latitude = "34.092603"
        self.operation.launch_longitude = "-117.771812"
        self.operation.save(
            update_fields=[
                "location_latitude",
                "location_longitude",
                "launch_latitude",
                "launch_longitude",
            ]
        )
        package = GeneratedConopsPackage(
            description_of_operations=(
                "Regenerated description for "
                f"{self.operation.start_date.isoformat()}."
            ),
            sections=[
                GeneratedConopsSection(
                    key=definition.key,
                    title=definition.title,
                    content=(
                        "The launch coordinates are 34.092603, -117.771812."
                        if definition.key == "operational-area-airspace"
                        else f"Regenerated {definition.key}."
                    ),
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

        section = ConopsSection.objects.get(
            application=self.application,
            section_key="operational-area-airspace",
        )
        canonical = (
            "The operation reference point is latitude 34.099076, "
            "longitude -117.775772."
        )
        launch = (
            "The launch location is latitude 34.092603, longitude "
            "-117.771812."
        )
        self.assertEqual(section.content.count(canonical), 1)
        self.assertEqual(section.content.count(launch), 1)

    @override_settings(
        OPENAI_API_KEY="test-key",
        OPENAI_TEXT_MODEL="test-model",
    )
    @patch("airspace.ai_conops._request_ai_document")
    def test_regeneration_cannot_omit_avoided_over_people_limit(
        self, request_document
    ):
        self.operation.operations_over_people = "avoided"
        self.operation.save(update_fields=["operations_over_people"])
        package = GeneratedConopsPackage(
            description_of_operations=(
                "Regenerated description for "
                f"{self.operation.start_date.isoformat()}."
            ),
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

        section = ConopsSection.objects.get(
            application=self.application,
            section_key="flight-envelope-limitations",
        )
        self.assertEqual(
            section.content.count(OPERATIONS_OVER_PEOPLE_AVOIDED),
            1,
        )

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
            description_of_operations=(
                "Regenerated description for "
                f"{self.operation.start_date.isoformat()}."
            ),
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
        self.application.refresh_from_db()
        self.assertIn(
            "did not preserve a required exact identifier from the planning record: LSV ATC",
            self.application.ai_generation_error,
        )
        response = self.client.get(self.url)
        self.assertContains(
            response,
            "Generation failed — existing CONOPS content was not replaced.",
        )

    @override_settings(
        OPENAI_API_KEY="test-key",
        OPENAI_TEXT_MODEL="test-model",
    )
    @patch("airspace.ai_conops._request_ai_document")
    def test_successful_regeneration_replaces_old_fixed_radius_text(
        self, request_document
    ):
        old_description = (
            "The DroneZone Requested Radius is 1/2 NM. Operations will remain "
            "within a radius around the launch site. Operation reference "
            "coordinates are 36.271187, -115.009416. The operation begins "
            f"{self.operation.start_date.isoformat()}."
        )
        old_section = (
            "The stored selection is 1/2 NM. Flights will remain within the "
            "authorized 0.5 nautical mile radius."
        )
        area_section = next(
            section
            for section in self.sections
            if section.section_key == "operational-area-airspace"
        )

        self.operation.dronezone_radius = "0.5_nm"
        self.operation.launch_location = "Primary pad"
        self.operation.recovery_location = "Primary pad"
        self.operation.location_latitude = "36.271187"
        self.operation.location_longitude = "-115.009416"
        self.operation.save()
        request_document.return_value = (
            GeneratedConopsPackage(
                description_of_operations=old_description,
                sections=[
                    GeneratedConopsSection(
                        key=definition.key,
                        title=definition.title,
                        content=(
                            old_section
                            if definition.key == "operational-area-airspace"
                            else f"Initial {definition.key}."
                        ),
                    )
                    for definition in CONOPS_DEFINITIONS
                ],
            ),
            MagicMock(usage=None),
        )
        generate_ai_conops(
            self.approval,
            self.user,
            regenerate_unlocked=True,
        )
        self.application.refresh_from_db()
        area_section.refresh_from_db()
        self.assertEqual(self.application.description, old_description)
        self.assertIn(old_section, area_section.content)
        self.assertIn(
            "The operation reference point is latitude 36.271187, "
            "longitude -115.009416.",
            area_section.content,
        )

        self.operation.dronezone_radius = "blanket_wide_area"
        self.operation.operation_area_type = "multiple_sites"
        self.operation.launch_location = "Varies"
        self.operation.recovery_location = "Varies"
        self.operation.location_latitude = "36.271187"
        self.operation.location_longitude = "-115.009416"
        self.operation.save()
        _invalidate_operation_conops(self.operation)

        current_geometry = (
            "Operations use Multiple sites. The launch location Varies and "
            "the recovery location Varies. The DroneZone Requested Radius is "
            "Blanket Area / Wide Area. The coordinates are operation "
            "reference coordinates, not launch coordinates: 36.271187, "
            "-115.009416. The operation begins "
            f"{self.operation.start_date.isoformat()}."
        )
        request_document.return_value = (
            GeneratedConopsPackage(
                description_of_operations=current_geometry,
                sections=[
                    GeneratedConopsSection(
                        key=definition.key,
                        title=definition.title,
                        content=(
                            current_geometry
                            if definition.key == "operational-area-airspace"
                            else f"Regenerated {definition.key}."
                        ),
                    )
                    for definition in CONOPS_DEFINITIONS
                ],
            ),
            MagicMock(usage=None),
        )

        generate_ai_conops(
            self.approval,
            self.user,
            regenerate_unlocked=True,
        )

        self.application.refresh_from_db()
        area_section.refresh_from_db()
        self.assertEqual(self.application.description, current_geometry)
        self.assertIn("Operations use Multiple sites.", area_section.content)
        self.assertIn("Blanket Area / Wide Area", area_section.content)
        self.assertIn(
            "The operation reference point is latitude 36.271187, "
            "longitude -115.009416.",
            area_section.content,
        )
        combined = f"{self.application.description}\n{area_section.content}"
        self.assertNotIn("0.5 nautical mile radius", combined)
        self.assertNotIn("radius around the launch site", combined)
        self.assertIn("Blanket Area / Wide Area", combined)
        self.assertIn("Multiple sites", combined)
        self.assertIn("launch location Varies", combined)


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
        self.operation.atc_frequency = "123.45 MHz"
        self.operation.atc_phone = "702-555-0188"
        self.operation.operational_boundary_description = (
            "Mapped property lines and Service Road A define the boundary."
        )
        self.operation.operations_over_people = "avoided"
        self.operation.crowd_mitigation = "Use controlled spectator barriers."
        self.operation.additional_operational_information = (
            "The RPIC has prior operating experience at this location."
        )
        self.operation.crewed_aircraft_conflict_response = (
            "Stored worksheet crewed-aircraft conflict response."
        )
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
        self.assertIn("123.45 MHz", text)
        self.assertIn("702-555-0188", text)
        self.assertIn("Mapped property lines", text)
        self.assertIn("Avoided", text)
        self.assertIn("controlled spectator barriers", text)
        self.assertIn("prior operating experience", text)
        self.assertIn(
            "Stored worksheet crewed-aircraft conflict response.",
            text,
        )
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
        self.assertIn("PDF prepared:", text)
        self.assertIn("AI content generated:", text)

    def test_unchanged_generation_post_does_not_retimestamp_saved_sections(self):
        section = self.sections[0]
        original_updated_at = section.updated_at

        with patch(
            "airspace.views.generate_ai_conops",
            side_effect=OpenAIConopsError("Test generation failure."),
        ):
            post_data = {
                "action": "generate_ai",
                "description": self.application.description,
            }
            for saved_section in self.sections:
                post_data[f"content_{saved_section.pk}"] = saved_section.content
            response = self.client.post(
                self.url,
                post_data,
            )

        self.assertRedirects(response, self.url)
        section.refresh_from_db()
        self.assertEqual(section.updated_at, original_updated_at)

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
