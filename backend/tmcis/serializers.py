import re

from rest_framework import serializers

from .models import (
    AuditEvent,
    CaseNote,
    Declaration,
    FinancialDataSource,
    IdentityCandidate,
    Investigation,
    Merchant,
    ReconciliationResult,
    RiskAssessment,
    RiskRule,
    SocialLead,
    TarmLink,
    TarmTransfer,
    TarmVerification,
    Transaction,
    User,
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "role", "department"]


class MerchantSerializer(serializers.ModelSerializer):
    account_username = serializers.CharField(source="user.username", read_only=True, default=None)

    class Meta:
        model = Merchant
        fields = [
            "id", "tin", "name", "business_name", "business_type", "email", "phone",
            "address", "city", "registration_date", "status", "is_demo",
            "created_at", "updated_at", "account_username",
        ]
        read_only_fields = ["id", "is_demo", "created_at", "updated_at", "account_username"]

    def validate_tin(self, value):
        if not re.fullmatch(r"200076899\d", value):
            raise serializers.ValidationError(
                "For this prototype, TINs must be 10 digits and begin with 200076899."
            )
        queryset = Merchant.objects.filter(tin=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A merchant with this TIN already exists.")
        return value


class RegistrationSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=12)
    name = serializers.CharField(max_length=180)
    business_name = serializers.CharField(max_length=180)
    tin = serializers.RegexField(r"^200076899\d$")
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)

    def validate_tin(self, value):
        if Merchant.objects.filter(tin=value).exists():
            raise serializers.ValidationError("A merchant with this TIN already exists.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("That username is already in use.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("That email is already in use.")
        return value


class DeclarationSerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source="merchant.business_name", read_only=True)
    merchant_tin = serializers.CharField(source="merchant.tin", read_only=True)

    class Meta:
        model = Declaration
        fields = [
            "id", "reference", "merchant", "merchant_name", "merchant_tin", "period",
            "currency", "declared_revenue", "tax_amount", "status", "information_request",
            "merchant_response", "submitted_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "reference", "status", "information_request", "submitted_at",
            "created_at", "updated_at", "merchant_name", "merchant_tin",
        ]

    def validate_period(self, value):
        if len(value) != 7 or value[4] != "-" or not value[:4].isdigit() or not value[5:].isdigit():
            raise serializers.ValidationError("Use YYYY-MM for the declaration period.")
        month = int(value[5:])
        if month < 1 or month > 12:
            raise serializers.ValidationError("Month must be between 01 and 12.")
        return value


class SourceSerializer(serializers.ModelSerializer):
    transaction_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = FinancialDataSource
        fields = ["id", "code", "name", "source_type", "is_enabled", "is_demo", "transaction_count"]


class TransactionSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)
    merchant_name = serializers.CharField(source="merchant.business_name", read_only=True, default=None)

    class Meta:
        model = Transaction
        fields = [
            "id", "source", "source_name", "merchant", "merchant_name", "tin", "reference",
            "transaction_at", "amount", "currency", "transaction_type", "payment_reference",
            "sender_reference_masked", "receiver_reference_masked", "reconciliation_status",
            "provenance", "is_demo", "created_at",
        ]
        read_only_fields = [
            "id", "source_name", "merchant_name", "is_demo", "created_at",
            "reconciliation_status", "provenance", "import_batch",
        ]


class ReconciliationSerializer(serializers.ModelSerializer):
    declaration_reference = serializers.CharField(source="declaration.reference", read_only=True, default=None)
    merchant_name = serializers.CharField(source="declaration.merchant.business_name", read_only=True, default=None)
    transaction_ids = serializers.SerializerMethodField()

    class Meta:
        model = ReconciliationResult
        fields = [
            "id", "declaration", "declaration_reference", "merchant_name", "transaction_ids",
            "status", "declared_amount", "observed_amount", "amount_difference", "reason",
            "resolution_notes", "created_at",
        ]

    def get_transaction_ids(self, obj):
        return list(obj.transactions.values_list("id", flat=True))


class RiskAssessmentSerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source="merchant.business_name", read_only=True)
    merchant_tin = serializers.CharField(source="merchant.tin", read_only=True)

    class Meta:
        model = RiskAssessment
        fields = [
            "id", "merchant", "merchant_name", "merchant_tin", "score", "band",
            "triggered_rules", "evidence", "limitations", "rule_set_version", "created_at",
        ]


class RiskRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskRule
        fields = ["id", "code", "title", "description", "points", "enabled", "version"]
        read_only_fields = ["id", "code", "version"]


class CaseSerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source="merchant.business_name", read_only=True)
    merchant_tin = serializers.CharField(source="merchant.tin", read_only=True)
    assigned_officer_username = serializers.CharField(
        source="assigned_officer.username", read_only=True, default=None
    )
    supervisor_username = serializers.CharField(source="supervisor.username", read_only=True, default=None)
    risk_score = serializers.IntegerField(source="risk_assessment.score", read_only=True, default=None)

    class Meta:
        model = Investigation
        fields = [
            "id", "reference", "merchant", "merchant_name", "merchant_tin", "source", "reason",
            "declarations", "transactions", "reconciliation", "risk_assessment", "risk_score",
            "assigned_officer", "assigned_officer_username", "supervisor", "supervisor_username",
            "priority", "due_date", "status", "findings", "recommendation",
            "supervisory_decision", "closure_outcome", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "reference", "created_at", "updated_at", "merchant_name", "merchant_tin"]


class CaseNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.username", read_only=True, default="System")

    class Meta:
        model = CaseNote
        fields = ["id", "author_name", "body", "is_evidence_note", "created_at"]
        read_only_fields = ["id", "author_name", "created_at"]


class IdentityCandidateSerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source="merchant.business_name", read_only=True)
    candidate_name = serializers.CharField(source="candidate.business_name", read_only=True)

    class Meta:
        model = IdentityCandidate
        fields = [
            "id", "merchant", "merchant_name", "candidate", "candidate_name",
            "reason", "evidence", "status", "decision_notes", "created_at",
        ]
        read_only_fields = [
            "id", "merchant", "merchant_name", "candidate_name", "reason", "evidence", "created_at"
        ]


class SocialLeadSerializer(serializers.ModelSerializer):
    linked_merchant_name = serializers.CharField(
        source="linked_merchant.business_name", read_only=True, default=None
    )
    assigned_officer_username = serializers.CharField(
        source="assigned_officer.username", read_only=True, default=None
    )

    class Meta:
        model = SocialLead
        fields = [
            "id", "reference", "platform", "profile_name", "profile_url",
            "public_business_identifier", "observation", "source_reference",
            "collection_method", "collected_at", "linked_merchant", "linked_merchant_name",
            "match_status", "assigned_officer", "assigned_officer_username", "review_status",
            "evidence_references", "linked_case", "reviewer_comments", "is_demo", "created_at",
        ]
        read_only_fields = ["id", "reference", "created_at", "is_demo", "linked_merchant_name"]


class TarmVerificationSerializer(serializers.ModelSerializer):
    merchant_tin = serializers.CharField(source="merchant.tin", read_only=True)
    merchant_name = serializers.CharField(source="merchant.business_name", read_only=True)

    class Meta:
        model = TarmVerification
        fields = [
            "id", "merchant", "merchant_tin", "merchant_name", "outcome",
            "environment", "source", "permitted_details", "verified_at",
        ]


class TarmLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = TarmLink
        fields = ["id", "merchant", "external_id", "matched_tin", "source", "status", "verified_at"]


class TarmTransferSerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source="merchant.business_name", read_only=True)
    declaration_reference = serializers.CharField(source="declaration.reference", read_only=True)

    class Meta:
        model = TarmTransfer
        fields = [
            "id", "reference", "merchant", "merchant_name", "declaration",
            "declaration_reference", "status", "environment", "adapter_response", "created_at",
        ]


class AuditEventSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True, default="System")

    class Meta:
        model = AuditEvent
        fields = [
            "id", "actor_username", "action", "entity_type", "entity_id", "details",
            "ip_address", "created_at",
        ]
