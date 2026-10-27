from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tmcis.models import (
    Declaration,
    FinancialDataSource,
    IdentityCandidate,
    ImportBatch,
    Investigation,
    Merchant,
    ReconciliationResult,
    RiskAssessment,
    RiskRule,
    SocialLead,
    TarmLink,
    TarmTaxpayer,
    TarmTransfer,
    Transaction,
    User,
)
from tmcis.services import assess_merchant_risk


class Command(BaseCommand):
    help = "Create repeatable, fictional TMCIS demo data. Development only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-demo-passwords",
            action="store_true",
            help="Reset the development demo accounts to the password shown in the output.",
        )
        parser.add_argument(
            "--password",
            default="TmcisDemo2026!",
            help="Local-only password assigned to new demo accounts.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo seeding is disabled when DJANGO_DEBUG is false.")
        password = options["password"]
        if len(password) < 12:
            raise CommandError("Use a demo password with at least 12 characters.")

        users = self.seed_users(password, options["reset_demo_passwords"])
        sources = self.seed_sources()
        merchants = self.seed_merchants(users)
        declarations, transaction_rows = self.seed_financial_records(merchants, sources)
        self.seed_taxpayer_directory(merchants, users["admin_demo"])
        self.seed_import_batches(sources, users["admin_demo"])
        self.seed_reconciliation_exceptions(declarations, transaction_rows)
        self.seed_risk_rules()
        self.seed_risk_assessments(merchants, users["admin_demo"])
        self.seed_cases(merchants, declarations, transaction_rows, users)
        self.seed_identity_candidates(merchants)
        self.seed_social_leads(merchants, users)
        self.seed_transfers(declarations, merchants, users["admin_demo"])

        self.stdout.write(self.style.SUCCESS("Fictional TMCIS demonstration data is ready."))
        self.stdout.write("Development-only accounts share this password:")
        self.stdout.write(f"  {password}")
        self.stdout.write("  admin_demo | supervisor_demo | officer_demo1 | merchant_demo1")
        self.stdout.write(
            "All seeded business, transaction, taxpayer, and social-intelligence records are fictional."
        )
        self.stdout.write(
            "The fixed demonstration TIN rule permits only 10 valid values; "
            "the remaining merchant profiles are inactive review fixtures with invalid demo TINs."
        )

    def seed_users(self, password, reset_passwords):
        definitions = [
            ("admin_demo", "admin", "admin@example.test", "Central"),
            ("supervisor_demo", "supervisor", "supervisor@example.test", "Central"),
            ("supervisor_demo2", "supervisor", "supervisor2@example.test", "North"),
        ]
        definitions.extend(
            (f"officer_demo{i}", "officer", f"officer{i}@example.test", "Central" if i <= 3 else "North")
            for i in range(1, 6)
        )
        definitions.extend(
            (f"merchant_demo{i}", "merchant", f"merchant{i}@example.test", "")
            for i in range(1, 31)
        )
        result = {}
        for username, role, email, department in definitions:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "role": role,
                    "department": department,
                    "is_active": True,
                    "is_staff": role == "admin",
                    "is_superuser": role == "admin",
                },
            )
            changed = []
            if user.email != email:
                user.email = email
                changed.append("email")
            if user.role != role:
                user.role = role
                changed.append("role")
            if user.department != department:
                user.department = department
                changed.append("department")
            if user.is_staff != (role == "admin"):
                user.is_staff = role == "admin"
                changed.append("is_staff")
            if user.is_superuser != (role == "admin"):
                user.is_superuser = role == "admin"
                changed.append("is_superuser")
            if created or reset_passwords:
                user.set_password(password)
                changed.append("password")
            if changed:
                user.save(update_fields=list(set(changed)))
            result[username] = user
        return result

    def seed_sources(self):
        rows = [
            ("ecocash", "EcoCash", "mobile_money"),
            ("onemoney", "OneMoney", "mobile_money"),
            ("cbz", "CBZ Bank", "bank"),
            ("stanbic", "Stanbic Bank Zimbabwe", "bank"),
            ("fbc", "FBC Bank", "bank"),
            ("cabs", "CABS", "bank"),
            ("zb", "ZB Bank", "bank"),
            ("other-bank", "Other configured bank", "bank"),
        ]
        return [
            FinancialDataSource.objects.update_or_create(
                code=code,
                defaults={"name": name, "source_type": kind, "is_enabled": True, "is_demo": True},
            )[0]
            for code, name, kind in rows
        ]

    def seed_merchants(self, users):
        merchants = []
        for index in range(1, 31):
            tin = f"200076899{index - 1}" if index <= 10 else f"DEMO-INVALID-TIN-{index:02d}"
            user = users[f"merchant_demo{index}"]
            merchant, _ = Merchant.objects.update_or_create(
                tin=tin,
                defaults={
                    "user": user,
                    "name": f"Demo Owner {index:02d}",
                    "business_name": f"Fictional Merchant {index:02d}",
                    "business_type": ["Retail", "Hospitality", "Services", "Wholesale"][index % 4],
                    "email": user.email,
                    "phone": f"+26377000{index:04d}",
                    "address": f"Demo Avenue {index}",
                    "city": ["Harare", "Bulawayo", "Mutare", "Gweru"][index % 4],
                    "registration_date": datetime(2020 + index % 5, (index % 12) + 1, 10).date(),
                    "status": Merchant.Status.ACTIVE if index <= 10 else Merchant.Status.REVIEW,
                    "is_demo": True,
                },
            )
            merchants.append(merchant)
        return merchants

    def seed_financial_records(self, merchants, sources):
        declarations = []
        transaction_rows = {}
        periods = [(2026, month) for month in range(4, 10)]
        for merchant_index, merchant in enumerate(merchants[:10]):
            transaction_rows[merchant.id] = []
            for period_index, (year, month) in enumerate(periods):
                period = f"{year}-{month:02d}"
                revenue = Decimal(1000 + merchant_index * 83 + period_index * 29).quantize(Decimal("0.01"))
                reference = f"DEMO-DEC-{merchant_index + 1:02d}-{period}"
                declared_status = (
                    Declaration.Status.DRAFT
                    if merchant_index == 0 and period_index == 5
                    else Declaration.Status.SUBMITTED
                )
                declaration, _ = Declaration.objects.update_or_create(
                    reference=reference,
                    defaults={
                        "merchant": merchant,
                        "period": period,
                        "currency": "USD",
                        "declared_revenue": revenue,
                        "tax_amount": (revenue * Decimal("0.15")).quantize(Decimal("0.01")),
                        "status": declared_status,
                        "submitted_at": timezone.make_aware(
                            datetime(year, month, 20, 12), dt_timezone.utc
                        ) if declared_status == Declaration.Status.SUBMITTED else None,
                        "created_by": merchant.user,
                        "is_demo": True,
                    },
                )
                declarations.append(declaration)
                amounts = [Decimal("150.00"), Decimal("200.00"), Decimal("250.00"), Decimal("100.00")]
                amounts.append(revenue - sum(amounts))
                # A small set of deliberate demo discrepancies; these are review indicators only.
                if period_index == 2 and merchant_index < 5:
                    amounts[-1] += Decimal("40.00")
                for transaction_index, amount in enumerate(amounts):
                    source = sources[(merchant_index * 6 + period_index * 5 + transaction_index) % len(sources)]
                    trans_at = timezone.make_aware(
                        datetime(year, month, 8 + transaction_index, 10 + transaction_index, 15),
                        dt_timezone.utc,
                    )
                    trans_ref = f"DEMO-{merchant_index + 1:02d}-{period}-{transaction_index + 1}"
                    record, _ = Transaction.objects.get_or_create(
                        reference=trans_ref,
                        source=source,
                        amount=amount,
                        defaults={
                            "merchant": merchant,
                            "tin": merchant.tin,
                            "transaction_at": trans_at,
                            "currency": "USD",
                            "transaction_type": "payment",
                            "payment_reference": f"INV-{merchant_index + 1:02d}-{period_index + 1:02d}",
                            "sender_reference_masked": "****4821",
                            "receiver_reference_masked": f"****{merchant_index + 1:04d}",
                            "reconciliation_status": Transaction.ReconciliationStatus.PENDING,
                            "provenance": "Fictional seeded demonstration record",
                            "is_demo": True,
                        },
                    )
                    transaction_rows[merchant.id].append(record)
        # Preserve explicit duplicate-reference examples in the fictional dataset.
        for index in range(5):
            original = Transaction.objects.filter(is_demo=True).order_by("id")[index]
            count = Transaction.objects.filter(
                source=original.source, reference=original.reference, amount=original.amount
            ).count()
            if count < 2:
                Transaction.objects.create(
                    source=original.source,
                    merchant=original.merchant,
                    tin=original.tin,
                    reference=original.reference,
                    transaction_at=original.transaction_at,
                    amount=original.amount,
                    currency=original.currency,
                    transaction_type=original.transaction_type,
                    payment_reference=original.payment_reference,
                    reconciliation_status=Transaction.ReconciliationStatus.DUPLICATE,
                    provenance="Fictional duplicate-reference demonstration record",
                    is_demo=True,
                )
        return declarations, transaction_rows

    def seed_taxpayer_directory(self, merchants, admin):
        for index, merchant in enumerate(merchants[:6], start=1):
            taxpayer, _ = TarmTaxpayer.objects.update_or_create(
                tin=merchant.tin,
                defaults={
                    "external_id": f"SIM-TAXPAYER-{index:04d}",
                    "permitted_name": merchant.business_name,
                    "status": "registered",
                    "is_demo": True,
                },
            )
            verified_at = timezone.make_aware(datetime(2026, 10, 1, 9), dt_timezone.utc)
            TarmLink.objects.update_or_create(
                merchant=merchant,
                defaults={
                    "external_id": taxpayer.external_id,
                    "matched_tin": merchant.tin,
                    "source": "Simulated TaRMS adapter",
                    "status": "linked",
                    "verified_at": verified_at,
                    "linked_by": admin,
                },
            )
        for index in range(7, 31):
            TarmTaxpayer.objects.update_or_create(
                tin=f"SIM-DEMO-TIN-{index:03d}",
                defaults={
                    "external_id": f"SIM-TAXPAYER-{index:04d}",
                    "permitted_name": f"Fictional TaRMS Taxpayer {index:02d}",
                    "status": "simulated_unmatched",
                    "is_demo": True,
                },
            )

    def seed_import_batches(self, sources, admin):
        for index, source in enumerate(sources[:5], start=1):
            ImportBatch.objects.update_or_create(
                source=source,
                file_name=f"DEMO-IMPORT-{index:02d}.csv",
                is_demo=True,
                defaults={
                    "status": ImportBatch.Status.PARTIAL if index == 3 else ImportBatch.Status.COMPLETED,
                    "accepted_count": 48 + index,
                    "rejected_count": 2 if index == 3 else 0,
                    "duplicate_count": 1 if index == 3 else 0,
                    "row_errors": (
                        [{"row": 17, "kind": "invalid", "message": "Fictional invalid demo row."}]
                        if index == 3 else []
                    ),
                    "created_by": admin,
                },
            )

    def seed_reconciliation_exceptions(self, declarations, transaction_rows):
        statuses = [
            ReconciliationResult.Status.AMOUNT,
            ReconciliationResult.Status.PARTIAL,
            ReconciliationResult.Status.UNMATCHED_DECLARATION,
            ReconciliationResult.Status.DUPLICATE,
            ReconciliationResult.Status.DATE,
        ]
        for index, declaration in enumerate(declarations[:15]):
            status_value = statuses[index % len(statuses)]
            result, created = ReconciliationResult.objects.get_or_create(
                declaration=declaration,
                reason="Seeded fictional exception for workflow demonstration.",
                defaults={
                    "status": status_value,
                    "declared_amount": declaration.declared_revenue,
                    "observed_amount": declaration.declared_revenue + Decimal("40.00"),
                    "amount_difference": Decimal("40.00"),
                    "rule_snapshot": {
                        "method": "Fictional seeded exception",
                        "limitations": "Requires manual review; not proof of wrongdoing.",
                    },
                    "is_demo": True,
                },
            )
            if created:
                candidates = transaction_rows.get(declaration.merchant_id, [])[:2]
                result.transactions.set(candidates)

    def seed_risk_rules(self):
        rules = [
            ("reconciliation-discrepancy", "reconciliation_discrepancy", "Reconciliation discrepancy", "A reviewed declaration has a mismatch against available source records.", 20),
            ("repeated-unresolved", "repeated_unresolved_exceptions", "Repeated unresolved exceptions", "Two or more recorded exceptions remain unresolved.", 20),
            ("duplicate-transaction", "duplicate_transaction_indicator", "Duplicate transaction indicator", "A source transaction reference appears more than once.", 15),
            ("information-requested", "information_requested", "Outstanding information request", "A declaration has an unresolved request for information.", 10),
        ]
        for code, rule_code, title, description, points in rules:
            RiskRule.objects.update_or_create(
                code=rule_code,
                defaults={
                    "title": title,
                    "description": description,
                    "points": points,
                    "enabled": True,
                    "version": 1,
                },
            )

    def seed_risk_assessments(self, merchants, admin):
        for merchant in merchants[:10]:
            if not RiskAssessment.objects.filter(merchant=merchant, created_by=admin).exists():
                assess_merchant_risk(merchant, admin)

    def seed_cases(self, merchants, declarations, transaction_rows, users):
        statuses = [
            Investigation.Status.OPEN,
            Investigation.Status.IN_REVIEW,
            Investigation.Status.RETURNED,
            Investigation.Status.RECOMMENDED,
            Investigation.Status.APPROVED,
            Investigation.Status.CLOSED,
            Investigation.Status.ESCALATED,
            Investigation.Status.OPEN,
            Investigation.Status.IN_REVIEW,
            Investigation.Status.RECOMMENDED,
        ]
        for index in range(10):
            merchant = merchants[index]
            officer = users[f"officer_demo{index % 5 + 1}"] if index not in {6, 8} else None
            case, _ = Investigation.objects.update_or_create(
                reference=f"DEMO-CASE-{index + 1:04d}",
                defaults={
                    "merchant": merchant,
                    "source": "Fictional seeded compliance review",
                    "reason": "Fictional demonstration case. Findings require officer and supervisor review.",
                    "assigned_officer": officer,
                    "supervisor": users["supervisor_demo" if index < 5 else "supervisor_demo2"],
                    "priority": [Investigation.Priority.NORMAL, Investigation.Priority.HIGH, Investigation.Priority.LOW][index % 3],
                    "due_date": datetime(2026, 11, 15).date(),
                    "status": statuses[index],
                    "findings": "No finding has been made. Review the source records and document limitations.",
                    "recommendation": "",
                    "created_by": users["admin_demo"],
                    "is_demo": True,
                },
            )
            declaration = declarations[index]
            case.declarations.set([declaration])
            case.transactions.set(transaction_rows.get(merchant.id, [])[:3])

    def seed_identity_candidates(self, merchants):
        for index in range(5):
            first = merchants[index]
            second = merchants[index + 1]
            IdentityCandidate.objects.get_or_create(
                merchant=first,
                candidate=second,
                defaults={
                    "reason": "Shared fictional business contact token; verify using authorized records.",
                    "evidence": [{"type": "business_identifier", "value": f"DEMO-GROUP-{index + 1:02d}"}],
                    "status": IdentityCandidate.Status.PENDING,
                    "is_demo": True,
                },
            )

    def seed_social_leads(self, merchants, users):
        platforms = [SocialLead.Platform.FACEBOOK, SocialLead.Platform.INSTAGRAM, SocialLead.Platform.X]
        for index in range(30):
            platform = platforms[index % 3]
            merchant = merchants[index % 10]
            status_value = [
                SocialLead.ReviewStatus.NEW,
                SocialLead.ReviewStatus.REQUIRES_REVIEW,
                SocialLead.ReviewStatus.REVIEWED,
                SocialLead.ReviewStatus.LINKED,
                SocialLead.ReviewStatus.REJECTED,
            ][index % 5]
            SocialLead.objects.update_or_create(
                reference=f"DEMO-SOC-{index + 1:04d}",
                defaults={
                    "platform": platform,
                    "profile_name": f"Fictional {platform.title()} business profile {index + 1:02d}",
                    "profile_url": f"https://example.test/{platform}/demo-{index + 1:02d}",
                    "public_business_identifier": f"DEMO-BUSINESS-{index + 1:03d}",
                    "observation": "FICTIONAL DEMO ONLY: public business listing used to exercise manual review workflow.",
                    "source_reference": f"DEMO-SOURCE-{index + 1:03d}",
                    "collection_method": "manual",
                    "collected_at": timezone.make_aware(datetime(2026, 10, 1 + (index % 25), 11), dt_timezone.utc),
                    "linked_merchant": merchant if status_value == SocialLead.ReviewStatus.LINKED else None,
                    "match_status": "confirmed_by_reviewer" if status_value == SocialLead.ReviewStatus.LINKED else "unreviewed",
                    "assigned_officer": users[f"officer_demo{index % 5 + 1}"],
                    "review_status": status_value,
                    "evidence_references": [f"DEMO-EVIDENCE-{index + 1:03d}"],
                    "reviewer_comments": "Fictional record; no live platform collection.",
                    "is_demo": True,
                },
            )

    def seed_transfers(self, declarations, merchants, admin):
        statuses = [
            TarmTransfer.Status.SUCCESS,
            TarmTransfer.Status.SUCCESS,
            TarmTransfer.Status.REJECTED,
            TarmTransfer.Status.FAILED,
            TarmTransfer.Status.SUBMITTED,
            TarmTransfer.Status.PROCESSING,
            TarmTransfer.Status.REVIEW,
            TarmTransfer.Status.SUCCESS,
            TarmTransfer.Status.REJECTED,
            TarmTransfer.Status.READY,
        ]
        for index in range(10):
            declaration = declarations[index]
            reference = f"DEMO-TRF-{index + 1:04d}"
            TarmTransfer.objects.update_or_create(
                reference=reference,
                defaults={
                    "merchant": merchants[index],
                    "declaration": declaration,
                    "status": statuses[index],
                    "environment": "simulated",
                    "idempotency_key": uuid5(NAMESPACE_URL, reference),
                    "adapter_response": {
                        "code": "FICTIONAL_DEMO",
                        "message": "Seeded simulated transfer outcome; no live system was contacted.",
                    },
                    "submitted_by": admin,
                },
            )
