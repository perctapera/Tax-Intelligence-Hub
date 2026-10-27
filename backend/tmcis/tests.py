import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (
    AuditEvent,
    Declaration,
    FinancialDataSource,
    Investigation,
    Merchant,
    RiskAssessment,
    TarmLink,
    TarmTaxpayer,
    Transaction,
    User,
)


class TmcisApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="test-admin",
            email="admin@example.test",
            password="Safe-demo-pass-2026!",
            role=User.Role.ADMIN,
        )
        self.merchant_user = User.objects.create_user(
            username="test-merchant",
            email="merchant@example.test",
            password="Safe-demo-pass-2026!",
            role=User.Role.MERCHANT,
        )
        self.merchant = Merchant.objects.create(
            user=self.merchant_user,
            tin="2000768990",
            name="Fictional Merchant One",
            business_name="Fictional Merchant One",
        )
        self.other_merchant = Merchant.objects.create(
            tin="2000768991",
            name="Fictional Merchant Two",
            business_name="Fictional Merchant Two",
        )
        self.source = FinancialDataSource.objects.create(
            code="test-bank",
            name="Test Financial Source",
            source_type=FinancialDataSource.SourceType.BANK,
            is_enabled=True,
        )

    def as_user(self, user):
        self.client.force_authenticate(user=user)

    def test_health_is_public_and_marks_service(self):
        response = self.client.get("/api/v1/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["service"], "tmcis-api")

    def test_merchant_records_are_scoped_to_own_profile(self):
        self.as_user(self.merchant_user)
        response = self.client.get("/api/v1/merchants")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.data["results"]], [self.merchant.id])

    def test_merchant_cannot_create_staff_records_or_change_tin(self):
        self.as_user(self.merchant_user)
        create_response = self.client.post(
            "/api/v1/merchants",
            {"tin": "2000768992", "name": "No", "business_name": "No"},
            format="json",
        )
        self.assertEqual(create_response.status_code, 403)
        update_response = self.client.patch(
            f"/api/v1/merchants/{self.merchant.id}",
            {"tin": "2000768992"},
            format="json",
        )
        self.assertEqual(update_response.status_code, 403)

    def test_staff_rejects_tin_outside_demo_validation_rule(self):
        self.as_user(self.admin)
        response = self.client.post(
            "/api/v1/merchants",
            {"tin": "9999999999", "name": "Invalid", "business_name": "Invalid Demo"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("tin", response.data)

    def test_merchant_can_create_and_submit_own_declaration(self):
        self.as_user(self.merchant_user)
        draft = self.client.post(
            "/api/v1/declarations",
            {
                "period": "2026-01",
                "currency": "USD",
                "declared_revenue": "1000.00",
                "tax_amount": "150.00",
            },
            format="json",
        )
        self.assertEqual(draft.status_code, 201)
        self.assertEqual(draft.data["status"], Declaration.Status.DRAFT)
        submitted = self.client.post(
            f"/api/v1/declarations/{draft.data['id']}/submit",
            {},
            format="json",
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.data["status"], Declaration.Status.SUBMITTED)
        self.assertTrue(AuditEvent.objects.filter(action="declaration_submitted").exists())

    def test_csv_import_reports_accepted_duplicate_and_rejected_rows(self):
        self.as_user(self.admin)
        csv_content = (
            "transaction_reference,tin,transaction_at,amount,currency,transaction_type\n"
            "TX-ONE,2000768990,2026-01-10T10:00:00Z,100.00,USD,deposit\n"
            "TX-ONE,2000768990,2026-01-10T10:00:00Z,100.00,USD,deposit\n"
            "TX-BAD,invalid-tin,2026-01-11T10:00:00Z,25.00,USD,deposit\n"
            "TX-NEG,2000768990,2026-01-12T10:00:00Z,-2.00,USD,deposit\n"
        )
        upload = SimpleUploadedFile("fixture.csv", csv_content.encode(), content_type="text/csv")
        response = self.client.post(
            "/api/v1/transactions/import",
            {"source": self.source.code, "file": upload},
            format="multipart",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["accepted"], 1)
        self.assertEqual(response.data["duplicates"], 1)
        self.assertEqual(response.data["rejected"], 2)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_reconciliation_and_risk_are_review_support_not_enforcement(self):
        self.as_user(self.admin)
        declaration = Declaration.objects.create(
            reference="DEC-TEST-1",
            merchant=self.merchant,
            period="2026-01",
            currency="USD",
            declared_revenue="100.00",
            tax_amount="15.00",
            status=Declaration.Status.SUBMITTED,
        )
        Transaction.objects.create(
            source=self.source,
            merchant=self.merchant,
            tin=self.merchant.tin,
            reference="TX-TEST-1",
            transaction_at="2026-01-10T10:00:00Z",
            amount="125.00",
            currency="USD",
        )
        reconciliation = self.client.post("/api/v1/reconciliation/run", {}, format="json")
        self.assertEqual(reconciliation.status_code, 200)
        self.assertEqual(reconciliation.data["created"], 1)
        self.assertEqual(reconciliation.data["results"][0]["status"], "amount_discrepancy")

        assessment = self.client.post(
            "/api/v1/risk-assessments/run",
            {"merchant_id": self.merchant.id},
            format="json",
        )
        self.assertEqual(assessment.status_code, 201)
        self.assertIn("not proof of wrongdoing", " ".join(assessment.data["limitations"]))
        self.assertTrue(RiskAssessment.objects.filter(merchant=self.merchant).exists())
        self.assertTrue(Declaration.objects.filter(pk=declaration.pk).exists())

    def test_tarms_is_simulated_and_link_requires_successful_verification(self):
        self.as_user(self.admin)
        TarmTaxpayer.objects.create(
            tin=self.merchant.tin,
            external_id="SIM-TEST-001",
            permitted_name="Fictional Registered Merchant",
        )
        verification = self.client.post(
            "/api/v1/tarm/verify",
            {"merchant_id": self.merchant.id},
            format="json",
        )
        self.assertEqual(verification.status_code, 200)
        self.assertEqual(verification.data["outcome"], "registered")
        self.assertEqual(verification.data["environment"], "simulated")

        link = self.client.post(
            "/api/v1/tarm/link",
            {"merchant_id": self.merchant.id},
            format="json",
        )
        self.assertEqual(link.status_code, 201)
        self.assertTrue(TarmLink.objects.filter(merchant=self.merchant).exists())

    def test_only_assigned_officers_can_see_their_cases(self):
        officer = User.objects.create_user(
            username="test-officer",
            email="officer@example.test",
            password="Safe-demo-pass-2026!",
            role=User.Role.OFFICER,
            department="Test",
        )
        case = Investigation.objects.create(
            reference="CASE-TEST-1",
            merchant=self.merchant,
            reason="Fictional review case",
            created_by=self.admin,
            assigned_officer=officer,
        )
        other_case = Investigation.objects.create(
            reference="CASE-TEST-2",
            merchant=self.other_merchant,
            reason="Unassigned fixture",
            created_by=self.admin,
        )
        self.as_user(officer)
        response = self.client.get("/api/v1/cases")
        returned_ids = {row["id"] for row in response.data["results"]}
        self.assertIn(case.id, returned_ids)
        self.assertNotIn(other_case.id, returned_ids)
        forbidden_transition = self.client.post(
            f"/api/v1/cases/{case.id}/transition",
            {"status": "approved"},
            format="json",
        )
        self.assertEqual(forbidden_transition.status_code, 400)

    def test_transfer_confirmation_requires_explicit_confirmation_and_idempotency_key(self):
        self.as_user(self.admin)
        declaration = Declaration.objects.create(
            reference="DEC-TRANSFER-1",
            merchant=self.merchant,
            period="2026-02",
            currency="USD",
            declared_revenue="400.00",
            tax_amount="60.00",
            status=Declaration.Status.SUBMITTED,
        )
        self.assertTrue(TarmLink.objects.filter(merchant=self.merchant).exists() is False)
        missing_confirmation = self.client.post(
            "/api/v1/tarm/transfers",
            {"declaration_id": declaration.id, "idempotency_key": str(uuid.uuid4())},
            format="json",
        )
        self.assertEqual(missing_confirmation.status_code, 400)
