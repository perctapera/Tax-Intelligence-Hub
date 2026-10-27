import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

TIN_PATTERN = r"^200076899\d$"
tin_validator = RegexValidator(
    regex=TIN_PATTERN,
    message="Demo TINs must be 10 digits and begin with 200076899.",
)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        SUPERVISOR = "supervisor", "Supervisor"
        OFFICER = "officer", "Tax compliance officer"
        MERCHANT = "merchant", "Merchant"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MERCHANT)
    department = models.CharField(max_length=120, blank=True)
    email = models.EmailField(unique=True)

    @property
    def is_staff_role(self):
        return self.role in {self.Role.ADMIN, self.Role.SUPERVISOR, self.Role.OFFICER}


class Merchant(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVIEW = "review", "Needs review"
        INACTIVE = "inactive", "Inactive"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="merchant_profile",
        on_delete=models.SET_NULL,
    )
    tin = models.CharField(
        max_length=32,
        unique=True,
        validators=[tin_validator],
        help_text="Project-specific demonstration validation rule.",
    )
    name = models.CharField(max_length=180)
    business_name = models.CharField(max_length=180, blank=True)
    business_type = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    registration_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["tin", "status"]), models.Index(fields=["name"])]

    def __str__(self):
        return f"{self.business_name or self.name} ({self.tin})"


class Declaration(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        NEEDS_INFO = "needs_info", "Information requested"
        APPROVED = "approved", "Approved"
        RETURNED = "returned", "Returned"

    reference = models.CharField(max_length=32, unique=True)
    merchant = models.ForeignKey(Merchant, related_name="declarations", on_delete=models.PROTECT)
    period = models.CharField(max_length=7, db_index=True)
    currency = models.CharField(max_length=3, default="USD")
    declared_revenue = models.DecimalField(max_digits=16, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    information_request = models.TextField(blank=True)
    merchant_response = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="created_declarations"
    )
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period", "-created_at"]
        indexes = [models.Index(fields=["merchant", "status"]), models.Index(fields=["period", "status"])]


class FinancialDataSource(models.Model):
    class SourceType(models.TextChoices):
        MOBILE_MONEY = "mobile_money", "Mobile money"
        BANK = "bank", "Bank"
        OTHER = "other", "Other"

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    is_enabled = models.BooleanField(default=True)
    is_demo = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        PARTIAL = "partial", "Completed with errors"
        FAILED = "failed", "Failed"

    source = models.ForeignKey(FinancialDataSource, on_delete=models.PROTECT, related_name="batches")
    file_name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COMPLETED)
    accepted_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    row_errors = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class Transaction(models.Model):
    class ReconciliationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        MATCHED = "matched", "Matched"
        UNMATCHED = "unmatched", "Unmatched"
        DUPLICATE = "duplicate", "Potential duplicate"
        REVIEW = "review", "Requires review"

    source = models.ForeignKey(FinancialDataSource, related_name="transactions", on_delete=models.PROTECT)
    merchant = models.ForeignKey(
        Merchant, related_name="transactions", null=True, blank=True, on_delete=models.SET_NULL
    )
    tin = models.CharField(max_length=32, blank=True, db_index=True)
    reference = models.CharField(max_length=120, db_index=True)
    transaction_at = models.DateTimeField(db_index=True)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=3)
    transaction_type = models.CharField(max_length=40, blank=True)
    payment_reference = models.CharField(max_length=120, blank=True)
    sender_reference_masked = models.CharField(max_length=80, blank=True)
    receiver_reference_masked = models.CharField(max_length=80, blank=True)
    import_batch = models.ForeignKey(
        ImportBatch, null=True, blank=True, related_name="transactions", on_delete=models.SET_NULL
    )
    reconciliation_status = models.CharField(
        max_length=20, choices=ReconciliationStatus.choices, default=ReconciliationStatus.PENDING
    )
    provenance = models.CharField(max_length=255, default="Fictional demonstration data")
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-transaction_at"]
        indexes = [
            models.Index(fields=["source", "transaction_at"]),
            models.Index(fields=["tin", "currency"]),
        ]


class ReconciliationResult(models.Model):
    class Status(models.TextChoices):
        MATCHED = "matched", "Matched"
        PARTIAL = "partially_matched", "Partially matched"
        UNMATCHED_DECLARATION = "unmatched_declaration", "Unmatched declaration"
        UNMATCHED_TRANSACTION = "unmatched_transaction", "Unmatched transaction"
        DUPLICATE = "potential_duplicate", "Potential duplicate"
        AMOUNT = "amount_discrepancy", "Amount discrepancy"
        DATE = "date_discrepancy", "Date discrepancy"
        CURRENCY = "currency_discrepancy", "Currency discrepancy"
        REVIEW = "manual_review", "Requires manual review"

    declaration = models.ForeignKey(
        Declaration, null=True, blank=True, related_name="reconciliation_results", on_delete=models.SET_NULL
    )
    transactions = models.ManyToManyField(Transaction, related_name="reconciliation_results", blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, db_index=True)
    declared_amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    observed_amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    amount_difference = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    reason = models.TextField()
    rule_snapshot = models.JSONField(default=dict, blank=True)
    resolution_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class IdentityCandidate(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        DEFERRED = "deferred", "Deferred"

    merchant = models.ForeignKey(Merchant, related_name="identity_candidates", on_delete=models.PROTECT)
    candidate = models.ForeignKey(Merchant, related_name="candidate_for", on_delete=models.PROTECT)
    reason = models.CharField(max_length=180)
    evidence = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    decision_notes = models.TextField(blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    decided_at = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["status", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["merchant", "candidate"], name="unique_identity_candidate_pair")
        ]


class RiskRule(models.Model):
    code = models.SlugField(max_length=60, unique=True)
    title = models.CharField(max_length=160)
    description = models.TextField()
    points = models.PositiveSmallIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["code"]


class RiskAssessment(models.Model):
    class Band(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    merchant = models.ForeignKey(Merchant, related_name="risk_assessments", on_delete=models.PROTECT)
    score = models.PositiveSmallIntegerField()
    band = models.CharField(max_length=20, choices=Band.choices)
    triggered_rules = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=list, blank=True)
    limitations = models.JSONField(default=list, blank=True)
    rule_set_version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class Investigation(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_REVIEW = "in_review", "In review"
        RETURNED = "returned", "Returned for more work"
        RECOMMENDED = "recommended", "Submitted for review"
        APPROVED = "approved", "Approved"
        ESCALATED = "escalated", "Escalated"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    reference = models.CharField(max_length=32, unique=True)
    merchant = models.ForeignKey(Merchant, related_name="cases", on_delete=models.PROTECT)
    source = models.CharField(max_length=80, default="Manual review")
    reason = models.TextField()
    declarations = models.ManyToManyField(Declaration, blank=True, related_name="cases")
    transactions = models.ManyToManyField(Transaction, blank=True, related_name="cases")
    reconciliation = models.ForeignKey(
        ReconciliationResult, null=True, blank=True, related_name="cases", on_delete=models.SET_NULL
    )
    risk_assessment = models.ForeignKey(
        RiskAssessment, null=True, blank=True, related_name="cases", on_delete=models.SET_NULL
    )
    assigned_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="assigned_cases", on_delete=models.SET_NULL
    )
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="supervised_cases", on_delete=models.SET_NULL
    )
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    findings = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    supervisory_decision = models.TextField(blank=True)
    closure_outcome = models.CharField(max_length=180, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, related_name="created_cases", on_delete=models.SET_NULL
    )
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["assigned_officer", "status"])]


class CaseNote(models.Model):
    case = models.ForeignKey(Investigation, related_name="notes", on_delete=models.CASCADE)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    body = models.TextField()
    is_evidence_note = models.BooleanField(default=False)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]


class SocialLead(models.Model):
    class Platform(models.TextChoices):
        FACEBOOK = "facebook", "Facebook"
        INSTAGRAM = "instagram", "Instagram"
        X = "x", "X"

    class ReviewStatus(models.TextChoices):
        NEW = "new", "New"
        REVIEWED = "reviewed", "Reviewed"
        REQUIRES_REVIEW = "requires_review", "Requires review"
        LINKED = "linked", "Linked to merchant"
        REJECTED = "rejected", "Rejected"

    reference = models.CharField(max_length=32, unique=True)
    platform = models.CharField(max_length=20, choices=Platform.choices, db_index=True)
    profile_name = models.CharField(max_length=180)
    profile_url = models.URLField(blank=True)
    public_business_identifier = models.CharField(max_length=180, blank=True)
    observation = models.TextField()
    source_reference = models.CharField(max_length=180, blank=True)
    collection_method = models.CharField(max_length=40, default="manual")
    collected_at = models.DateTimeField(default=timezone.now)
    linked_merchant = models.ForeignKey(
        Merchant, null=True, blank=True, related_name="social_leads", on_delete=models.SET_NULL
    )
    match_status = models.CharField(max_length=30, default="unreviewed")
    assigned_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="social_leads", on_delete=models.SET_NULL
    )
    review_status = models.CharField(
        max_length=24, choices=ReviewStatus.choices, default=ReviewStatus.NEW, db_index=True
    )
    evidence_references = models.JSONField(default=list, blank=True)
    linked_case = models.ForeignKey(
        Investigation, null=True, blank=True, related_name="social_leads", on_delete=models.SET_NULL
    )
    reviewer_comments = models.TextField(blank=True)
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-collected_at"]


class TarmTaxpayer(models.Model):
    tin = models.CharField(max_length=32, unique=True)
    external_id = models.CharField(max_length=80, unique=True)
    permitted_name = models.CharField(max_length=180)
    status = models.CharField(max_length=30, default="registered")
    is_demo = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)


class TarmVerification(models.Model):
    class Outcome(models.TextChoices):
        REGISTERED = "registered", "Registered"
        NOT_REGISTERED = "not_registered", "Not registered"
        INVALID = "invalid_tin", "Invalid TIN"
        UNAVAILABLE = "connection_unavailable", "Connection unavailable"
        AUTH_FAILURE = "authorization_failure", "Authorization failure"
        FAILED = "request_failed", "Request failed"
        PENDING = "pending", "Pending"

    merchant = models.ForeignKey(Merchant, related_name="tarm_verifications", on_delete=models.PROTECT)
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    outcome = models.CharField(max_length=30, choices=Outcome.choices)
    environment = models.CharField(max_length=20, default="simulated")
    source = models.CharField(max_length=80, default="Simulated TaRMS adapter")
    permitted_details = models.JSONField(default=dict, blank=True)
    verified_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-verified_at"]


class TarmLink(models.Model):
    merchant = models.OneToOneField(Merchant, related_name="tarm_link", on_delete=models.PROTECT)
    external_id = models.CharField(max_length=80, unique=True)
    matched_tin = models.CharField(max_length=32)
    source = models.CharField(max_length=80, default="Simulated TaRMS adapter")
    status = models.CharField(max_length=24, default="linked")
    verified_at = models.DateTimeField()
    linked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now)


class TarmTransfer(models.Model):
    class Status(models.TextChoices):
        READY = "ready", "Ready for transfer"
        SUBMITTED = "submitted", "Submitted"
        PROCESSING = "processing", "Processing"
        SUCCESS = "success", "Successfully transferred"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"
        REVIEW = "manual_review", "Requires manual review"

    reference = models.CharField(max_length=32, unique=True)
    merchant = models.ForeignKey(Merchant, related_name="tarm_transfers", on_delete=models.PROTECT)
    declaration = models.ForeignKey(Declaration, related_name="tarm_transfers", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.READY)
    environment = models.CharField(max_length=20, default="simulated")
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True)
    adapter_response = models.JSONField(default=dict, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="audit_events", on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=100, db_index=True)
    entity_type = models.CharField(max_length=80, blank=True)
    entity_id = models.CharField(max_length=80, blank=True)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
