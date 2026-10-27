import csv
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction as db_transaction
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AuditEvent,
    CaseNote,
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
    TarmVerification,
    Transaction,
    User,
)
from .pagination import StandardResultsPagination
from .serializers import (
    AuditEventSerializer,
    CaseNoteSerializer,
    CaseSerializer,
    DeclarationSerializer,
    IdentityCandidateSerializer,
    MerchantSerializer,
    ReconciliationSerializer,
    RegistrationSerializer,
    RiskAssessmentSerializer,
    RiskRuleSerializer,
    SocialLeadSerializer,
    SourceSerializer,
    TarmLinkSerializer,
    TarmTransferSerializer,
    TarmVerificationSerializer,
    TransactionSerializer,
    UserSerializer,
)
from .services import (
    assess_merchant_risk,
    dashboard_counts,
    make_reference,
    record_audit,
    run_reconciliation,
    simulated_tarm_check,
)

ADMIN = User.Role.ADMIN
SUPERVISOR = User.Role.SUPERVISOR
OFFICER = User.Role.OFFICER
MERCHANT_ROLE = User.Role.MERCHANT
STAFF = {ADMIN, SUPERVISOR, OFFICER}
ADMIN_SUPERVISOR = {ADMIN, SUPERVISOR}
TIN_RE = re.compile(r"^200076899\d$")


def deny(message="You do not have permission to perform this action."):
    return Response({"error": message}, status=status.HTTP_403_FORBIDDEN)


def require_roles(request, roles):
    return request.user.is_authenticated and request.user.role in roles


def accessible_cases(user):
    cases = Investigation.objects.select_related("merchant", "assigned_officer", "supervisor", "risk_assessment")
    if user.role == ADMIN:
        return cases
    if user.role == SUPERVISOR:
        if user.department:
            return cases.filter(
                Q(supervisor=user) | Q(assigned_officer__department=user.department)
            ).distinct()
        return cases
    if user.role == OFFICER:
        return cases.filter(assigned_officer=user)
    merchant = getattr(user, "merchant_profile", None)
    return cases.filter(merchant=merchant) if merchant else cases.none()


def accessible_merchant_ids(user):
    if user.role == ADMIN:
        return Merchant.objects.values_list("id", flat=True)
    if user.role == SUPERVISOR:
        if user.department:
            return accessible_cases(user).values_list("merchant_id", flat=True).distinct()
        return Merchant.objects.values_list("id", flat=True)
    if user.role == OFFICER:
        return accessible_cases(user).values_list("merchant_id", flat=True).distinct()
    merchant = getattr(user, "merchant_profile", None)
    return [merchant.id] if merchant else []


def can_access_merchant(user, merchant):
    if user.role == ADMIN:
        return True
    if user.role in {SUPERVISOR, OFFICER}:
        return accessible_cases(user).filter(merchant=merchant).exists()
    own = getattr(user, "merchant_profile", None)
    return own is not None and own.id == merchant.id


def paginated(queryset, request, serializer_class):
    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(serializer_class(page, many=True).data)


class CsrfCookieView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({"detail": "CSRF cookie set."})


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"status": "ok", "service": "tmcis-api"})


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(csrf_protect)
    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        user = authenticate(request, username=username, password=password)
        if not user:
            record_audit(request, "login_failed")
            return Response(
                {"error": "The username or password is incorrect."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not user.is_active:
            return Response({"error": "This account is inactive."}, status=status.HTTP_403_FORBIDDEN)
        login(request, user)
        record_audit(request, "login_succeeded", user, {"role": user.role})
        return Response({"user": UserSerializer(user).data})


class LogoutView(APIView):
    @method_decorator(csrf_protect)
    def post(self, request):
        record_audit(request, "logout")
        logout(request)
        return Response({"detail": "Signed out."})


class MeView(APIView):
    def get(self, request):
        data = UserSerializer(request.user).data
        if request.user.role == MERCHANT_ROLE:
            merchant = getattr(request.user, "merchant_profile", None)
            data["merchant_id"] = merchant.id if merchant else None
        return Response(data)


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        candidate = User(
            username=values["username"],
            email=values["email"],
            role=MERCHANT_ROLE,
            first_name=values["name"][:150],
        )
        try:
            validate_password(values["password"], user=candidate)
        except DjangoValidationError as exc:
            return Response({"error": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        with db_transaction.atomic():
            candidate.set_password(values["password"])
            candidate.save()
            merchant = Merchant.objects.create(
                user=candidate,
                tin=values["tin"],
                name=values["name"],
                business_name=values["business_name"],
                email=values["email"],
                phone=values.get("phone", ""),
                status=Merchant.Status.REVIEW,
            )
        login(request, candidate)
        record_audit(request, "merchant_registered", merchant, {"source": "self_service"})
        return Response(
            {"user": UserSerializer(candidate).data, "merchant": MerchantSerializer(merchant).data},
            status=status.HTTP_201_CREATED,
        )


class DashboardView(APIView):
    def get(self, request):
        return Response(dashboard_counts(request.user))


class MerchantListView(APIView):
    def get(self, request):
        merchants = Merchant.objects.all().select_related("user")
        if request.user.role in {OFFICER, SUPERVISOR} and (
            request.user.role == OFFICER or request.user.department
        ):
            merchants = merchants.filter(id__in=accessible_merchant_ids(request.user))
        elif request.user.role == MERCHANT_ROLE:
            own = getattr(request.user, "merchant_profile", None)
            merchants = merchants.filter(pk=own.pk) if own else merchants.none()
        elif request.user.role not in {ADMIN, SUPERVISOR}:
            return deny()
        query = request.query_params.get("q", "").strip()
        if query:
            merchants = merchants.filter(
                Q(name__icontains=query) | Q(business_name__icontains=query) | Q(tin__icontains=query)
            )
        if request.query_params.get("status"):
            merchants = merchants.filter(status=request.query_params["status"])
        return paginated(merchants, request, MerchantSerializer)

    def post(self, request):
        if not require_roles(request, ADMIN_SUPERVISOR):
            return deny()
        serializer = MerchantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        merchant = serializer.save()
        record_audit(request, "merchant_created", merchant)
        return Response(MerchantSerializer(merchant).data, status=status.HTTP_201_CREATED)


class MerchantDetailView(APIView):
    def get_object(self, request, merchant_id):
        merchant = Merchant.objects.filter(pk=merchant_id).first()
        return merchant if merchant and can_access_merchant(request.user, merchant) else None

    def get(self, request, merchant_id):
        merchant = self.get_object(request, merchant_id)
        if not merchant:
            return Response({"error": "Merchant not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(MerchantSerializer(merchant).data)

    def patch(self, request, merchant_id):
        merchant = self.get_object(request, merchant_id)
        if not merchant:
            return Response({"error": "Merchant not found."}, status=status.HTTP_404_NOT_FOUND)
        if request.user.role not in {ADMIN, SUPERVISOR} and merchant.user_id != request.user.id:
            return deny()
        if request.user.role == MERCHANT_ROLE and set(request.data.keys()) - {
            "name", "business_name", "business_type", "email", "phone", "address", "city"
        }:
            return deny("Merchants may update contact and business profile fields only.")
        serializer = MerchantSerializer(merchant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        record_audit(request, "merchant_updated", updated)
        return Response(MerchantSerializer(updated).data)


class SourceListView(APIView):
    def get(self, request):
        if request.user.role not in STAFF:
            return deny()
        sources = FinancialDataSource.objects.annotate(transaction_count=Count("transactions"))
        return Response(SourceSerializer(sources, many=True).data)


class DeclarationListView(APIView):
    def get_queryset(self, request):
        declarations = Declaration.objects.select_related("merchant")
        if request.user.role == MERCHANT_ROLE:
            merchant = getattr(request.user, "merchant_profile", None)
            return declarations.filter(merchant=merchant) if merchant else declarations.none()
        if request.user.role in {OFFICER, SUPERVISOR} and (
            request.user.role == OFFICER or request.user.department
        ):
            return declarations.filter(merchant_id__in=accessible_merchant_ids(request.user))
        return declarations if request.user.role in {ADMIN, SUPERVISOR} else declarations.none()

    def get(self, request):
        declarations = self.get_queryset(request)
        query = request.query_params.get("q", "").strip()
        if query:
            declarations = declarations.filter(
                Q(reference__icontains=query)
                | Q(merchant__business_name__icontains=query)
                | Q(merchant__tin__icontains=query)
            )
        for field in ("status", "period", "currency"):
            if request.query_params.get(field):
                declarations = declarations.filter(**{field: request.query_params[field]})
        return paginated(declarations, request, DeclarationSerializer)

    def post(self, request):
        if request.user.role not in STAFF | {MERCHANT_ROLE}:
            return deny()
        payload = request.data.copy()
        if request.user.role == MERCHANT_ROLE:
            merchant = getattr(request.user, "merchant_profile", None)
            if not merchant:
                return Response({"error": "Merchant profile is missing."}, status=400)
            payload["merchant"] = merchant.id
        serializer = DeclarationSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        declaration = serializer.save(
            reference=make_reference("DEC"),
            created_by=request.user,
            is_demo=False,
        )
        record_audit(request, "declaration_draft_created", declaration)
        return Response(DeclarationSerializer(declaration).data, status=status.HTTP_201_CREATED)


class DeclarationDetailView(APIView):
    def get_object(self, request, declaration_id):
        declaration = Declaration.objects.select_related("merchant").filter(pk=declaration_id).first()
        if not declaration:
            return None
        if request.user.role == MERCHANT_ROLE:
            own = getattr(request.user, "merchant_profile", None)
            return declaration if own and declaration.merchant_id == own.id else None
        if request.user.role == OFFICER:
            return declaration if declaration.merchant_id in set(accessible_merchant_ids(request.user)) else None
        return declaration if request.user.role in {ADMIN, SUPERVISOR} else None

    def get(self, request, declaration_id):
        declaration = self.get_object(request, declaration_id)
        if not declaration:
            return Response({"error": "Declaration not found."}, status=404)
        return Response(DeclarationSerializer(declaration).data)

    def patch(self, request, declaration_id):
        declaration = self.get_object(request, declaration_id)
        if not declaration:
            return Response({"error": "Declaration not found."}, status=404)
        if declaration.status != Declaration.Status.DRAFT:
            return Response({"error": "Only draft declarations can be edited."}, status=409)
        serializer = DeclarationSerializer(declaration, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        record_audit(request, "declaration_draft_updated", updated)
        return Response(DeclarationSerializer(updated).data)


class DeclarationSubmitView(APIView):
    def post(self, request, declaration_id):
        declaration = Declaration.objects.select_related("merchant").filter(pk=declaration_id).first()
        own = getattr(request.user, "merchant_profile", None)
        if request.user.role != MERCHANT_ROLE or not own or not declaration or declaration.merchant_id != own.id:
            return Response({"error": "Declaration not found."}, status=404)
        if declaration.status != Declaration.Status.DRAFT:
            return Response({"error": "Only draft declarations can be submitted."}, status=409)
        if declaration.declared_revenue < 0 or declaration.tax_amount < 0:
            return Response({"error": "Amounts cannot be negative."}, status=400)
        declaration.status = Declaration.Status.SUBMITTED
        declaration.submitted_at = timezone.now()
        declaration.save(update_fields=["status", "submitted_at", "updated_at"])
        record_audit(request, "declaration_submitted", declaration)
        return Response(DeclarationSerializer(declaration).data)


class DeclarationResponseView(APIView):
    def post(self, request, declaration_id):
        declaration = Declaration.objects.filter(pk=declaration_id).first()
        own = getattr(request.user, "merchant_profile", None)
        if request.user.role != MERCHANT_ROLE or not own or not declaration or declaration.merchant_id != own.id:
            return Response({"error": "Declaration not found."}, status=404)
        if declaration.status != Declaration.Status.NEEDS_INFO:
            return Response({"error": "This declaration has no open information request."}, status=409)
        response_text = str(request.data.get("response", "")).strip()
        if not response_text:
            return Response({"error": "A response is required."}, status=400)
        declaration.merchant_response = response_text[:5000]
        declaration.status = Declaration.Status.SUBMITTED
        declaration.save(update_fields=["merchant_response", "status", "updated_at"])
        record_audit(request, "declaration_information_response", declaration)
        return Response(DeclarationSerializer(declaration).data)


class DeclarationReviewView(APIView):
    def post(self, request, declaration_id):
        if request.user.role not in STAFF:
            return deny()
        declaration = Declaration.objects.select_related("merchant").filter(pk=declaration_id).first()
        if not declaration or not can_access_merchant(request.user, declaration.merchant):
            return Response({"error": "Declaration not found."}, status=404)
        if declaration.status != Declaration.Status.SUBMITTED:
            return Response({"error": "Only submitted declarations can be reviewed."}, status=409)

        action = request.data.get("action")
        message = str(request.data.get("message", "")).strip()[:5000]
        if action == "request_information":
            if not message:
                return Response({"error": "Describe the information requested."}, status=400)
            declaration.status = Declaration.Status.NEEDS_INFO
            declaration.information_request = message
        elif action == "approve":
            if request.user.role not in ADMIN_SUPERVISOR:
                return deny("Only a supervisor or administrator may approve a declaration.")
            declaration.status = Declaration.Status.APPROVED
        elif action == "return":
            if request.user.role not in ADMIN_SUPERVISOR:
                return deny("Only a supervisor or administrator may return a declaration.")
            declaration.status = Declaration.Status.RETURNED
            declaration.information_request = message
        else:
            return Response({"error": "Choose request_information, approve, or return."}, status=400)

        declaration.save(update_fields=["status", "information_request", "updated_at"])
        record_audit(request, f"declaration_{action}", declaration, {"message": message})
        return Response(DeclarationSerializer(declaration).data)


class TransactionListView(APIView):
    def get_queryset(self, request):
        transactions = Transaction.objects.select_related("source", "merchant")
        if request.user.role in {OFFICER, SUPERVISOR} and (
            request.user.role == OFFICER or request.user.department
        ):
            merchant_ids = accessible_merchant_ids(request.user)
            tins = Merchant.objects.filter(id__in=merchant_ids).values_list("tin", flat=True)
            return transactions.filter(Q(merchant_id__in=merchant_ids) | Q(tin__in=tins))
        return transactions if request.user.role in {ADMIN, SUPERVISOR} else transactions.none()

    def get(self, request):
        if request.user.role not in STAFF:
            return deny()
        transactions = self.get_queryset(request)
        for param, field in [
            ("source", "source__code"),
            ("status", "reconciliation_status"),
            ("currency", "currency"),
        ]:
            if request.query_params.get(param):
                transactions = transactions.filter(**{field: request.query_params[param]})
        if request.query_params.get("date_from"):
            transactions = transactions.filter(transaction_at__date__gte=request.query_params["date_from"])
        if request.query_params.get("date_to"):
            transactions = transactions.filter(transaction_at__date__lte=request.query_params["date_to"])
        if request.query_params.get("amount_min"):
            transactions = transactions.filter(amount__gte=request.query_params["amount_min"])
        if request.query_params.get("amount_max"):
            transactions = transactions.filter(amount__lte=request.query_params["amount_max"])
        query = request.query_params.get("q", "").strip()
        if query:
            transactions = transactions.filter(
                Q(reference__icontains=query) | Q(tin__icontains=query) | Q(payment_reference__icontains=query)
            )
        return paginated(transactions, request, TransactionSerializer)

    def post(self, request):
        if request.user.role not in STAFF:
            return deny()
        serializer = TransactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("merchant") and not can_access_merchant(request.user, data["merchant"]):
            return deny()
        transaction_record = serializer.save(
            provenance="Manual entry by authorized user",
            is_demo=False,
        )
        record_audit(request, "transaction_created", transaction_record)
        return Response(TransactionSerializer(transaction_record).data, status=201)


class TransactionImportView(APIView):
    def post(self, request):
        if request.user.role not in {ADMIN, SUPERVISOR}:
            return deny()
        upload = request.FILES.get("file")
        source_code = str(request.data.get("source", "")).strip()
        if not upload:
            return Response({"error": "Choose a CSV file to import."}, status=400)
        source = FinancialDataSource.objects.filter(code=source_code, is_enabled=True).first()
        if not source:
            return Response({"error": "Choose an enabled financial data source."}, status=400)
        try:
            text = upload.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
        except (UnicodeDecodeError, csv.Error):
            return Response({"error": "The CSV file could not be read as UTF-8."}, status=400)
        required = {"transaction_reference", "tin", "transaction_at", "amount", "currency"}
        headers = set(reader.fieldnames or [])
        missing = sorted(required - headers)
        if missing:
            return Response({"error": "CSV is missing required columns.", "missing_columns": missing}, status=400)

        accepted = duplicate_count = rejected = 0
        row_errors = []
        with db_transaction.atomic():
            batch = ImportBatch.objects.create(
                source=source,
                file_name=upload.name[:255],
                created_by=request.user,
            )
            for row_number, row in enumerate(reader, start=2):
                try:
                    reference = (row.get("transaction_reference") or "").strip()
                    tin = (row.get("tin") or "").strip()
                    moment = parse_datetime((row.get("transaction_at") or "").strip())
                    if not reference:
                        raise ValueError("transaction_reference is required")
                    if tin and not TIN_RE.fullmatch(tin):
                        raise ValueError("TIN does not match the demonstration rule")
                    if not moment:
                        raise ValueError("transaction_at must be a valid ISO date or datetime")
                    if timezone.is_naive(moment):
                        moment = timezone.make_aware(moment)
                    try:
                        amount = Decimal((row.get("amount") or "").strip())
                    except InvalidOperation as exc:
                        raise ValueError("amount must be a number") from exc
                    if amount < 0:
                        raise ValueError("amount cannot be negative")
                    currency = (row.get("currency") or "").strip().upper()
                    if len(currency) != 3:
                        raise ValueError("currency must be a three-letter code")
                    if Transaction.objects.filter(
                        source=source, reference=reference, amount=amount, currency=currency
                    ).exists():
                        duplicate_count += 1
                        row_errors.append({"row": row_number, "kind": "duplicate", "message": "Duplicate source/reference/amount."})
                        continue
                    merchant = Merchant.objects.filter(tin=tin).first() if tin else None
                    Transaction.objects.create(
                        source=source,
                        merchant=merchant,
                        tin=tin,
                        reference=reference,
                        transaction_at=moment,
                        amount=amount,
                        currency=currency,
                        transaction_type=(row.get("transaction_type") or "").strip()[:40],
                        payment_reference=(row.get("payment_reference") or "").strip()[:120],
                        sender_reference_masked=(row.get("sender_reference_masked") or "").strip()[:80],
                        receiver_reference_masked=(row.get("receiver_reference_masked") or "").strip()[:80],
                        import_batch=batch,
                        provenance=f"CSV import: {upload.name[:150]}",
                        is_demo=False,
                    )
                    accepted += 1
                except (ValueError, TypeError, OverflowError) as exc:
                    rejected += 1
                    row_errors.append({"row": row_number, "kind": "invalid", "message": str(exc)})
            batch.accepted_count = accepted
            batch.rejected_count = rejected
            batch.duplicate_count = duplicate_count
            batch.row_errors = row_errors
            batch.status = ImportBatch.Status.PARTIAL if rejected or duplicate_count else ImportBatch.Status.COMPLETED
            batch.save()
        record_audit(
            request,
            "financial_csv_import",
            batch,
            {"accepted": accepted, "rejected": rejected, "duplicates": duplicate_count},
        )
        return Response(
            {
                "batch_id": batch.id,
                "status": batch.status,
                "accepted": accepted,
                "rejected": rejected,
                "duplicates": duplicate_count,
                "errors": row_errors,
            },
            status=201,
        )


class ImportHistoryView(APIView):
    def get(self, request):
        if request.user.role not in STAFF:
            return deny()
        batches = ImportBatch.objects.select_related("source").order_by("-created_at")
        return Response(
            [
                {
                    "id": batch.id,
                    "source": batch.source.name,
                    "file_name": batch.file_name,
                    "status": batch.status,
                    "accepted": batch.accepted_count,
                    "rejected": batch.rejected_count,
                    "duplicates": batch.duplicate_count,
                    "errors": batch.row_errors,
                    "created_at": batch.created_at,
                }
                for batch in batches[:100]
            ]
        )


class ReconciliationView(APIView):
    def get(self, request):
        if request.user.role not in STAFF:
            return deny()
        results = ReconciliationResult.objects.select_related("declaration", "declaration__merchant").prefetch_related("transactions")
        if request.user.role == OFFICER:
            results = results.filter(declaration__merchant_id__in=accessible_merchant_ids(request.user))
        if request.query_params.get("status"):
            results = results.filter(status=request.query_params["status"])
        return paginated(results, request, ReconciliationSerializer)

    def post(self, request):
        if request.user.role not in STAFF:
            return deny()
        results = run_reconciliation(request.user)
        record_audit(request, "reconciliation_run", details={"results": len(results)})
        return Response({"created": len(results), "results": ReconciliationSerializer(results, many=True).data})


class ReconciliationResolveView(APIView):
    def post(self, request, result_id):
        if request.user.role not in STAFF:
            return deny()
        result = ReconciliationResult.objects.filter(pk=result_id).first()
        if not result:
            return Response({"error": "Reconciliation result not found."}, status=404)
        if request.user.role == OFFICER and result.declaration_id not in Declaration.objects.filter(
            merchant_id__in=accessible_merchant_ids(request.user)
        ).values_list("id", flat=True):
            return deny()
        notes = str(request.data.get("notes", "")).strip()
        if not notes:
            return Response({"error": "Add a resolution note before resolving."}, status=400)
        result.resolution_notes = notes[:5000]
        result.resolved_by = request.user
        result.resolved_at = timezone.now()
        result.save(update_fields=["resolution_notes", "resolved_by", "resolved_at"])
        record_audit(request, "reconciliation_exception_resolved", result)
        return Response(ReconciliationSerializer(result).data)


class RiskAssessmentView(APIView):
    def get(self, request):
        if request.user.role not in STAFF:
            return deny()
        items = RiskAssessment.objects.select_related("merchant")
        if request.user.role == OFFICER:
            items = items.filter(merchant_id__in=accessible_merchant_ids(request.user))
        if request.query_params.get("band"):
            items = items.filter(band=request.query_params["band"])
        return paginated(items, request, RiskAssessmentSerializer)

    def post(self, request):
        if request.user.role not in STAFF:
            return deny()
        merchant = Merchant.objects.filter(pk=request.data.get("merchant_id")).first()
        if not merchant or not can_access_merchant(request.user, merchant):
            return Response({"error": "Merchant not found."}, status=404)
        assessment = assess_merchant_risk(merchant, request.user)
        record_audit(request, "risk_assessment_created", assessment, {"score": assessment.score})
        return Response(RiskAssessmentSerializer(assessment).data, status=201)


class RiskRuleListView(APIView):
    def get(self, request):
        if request.user.role not in STAFF:
            return deny()
        return Response(RiskRuleSerializer(RiskRule.objects.all(), many=True).data)

    def patch(self, request, rule_id):
        if request.user.role != ADMIN:
            return deny()
        rule = RiskRule.objects.filter(pk=rule_id).first()
        if not rule:
            return Response({"error": "Risk rule not found."}, status=404)
        serializer = RiskRuleSerializer(rule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        rule = serializer.save(version=rule.version + 1)
        record_audit(request, "risk_rule_updated", rule, {"version": rule.version})
        return Response(RiskRuleSerializer(rule).data)


class IdentityCandidateView(APIView):
    def get(self, request):
        if request.user.role not in STAFF:
            return deny()
        items = IdentityCandidate.objects.select_related("merchant", "candidate")
        if request.user.role == OFFICER:
            items = items.filter(merchant_id__in=accessible_merchant_ids(request.user))
        if request.query_params.get("status"):
            items = items.filter(status=request.query_params["status"])
        return paginated(items, request, IdentityCandidateSerializer)

    def patch(self, request, candidate_id):
        if request.user.role not in STAFF:
            return deny()
        item = IdentityCandidate.objects.filter(pk=candidate_id).select_related("merchant").first()
        if not item:
            return Response({"error": "Identity candidate not found."}, status=404)
        if request.user.role == OFFICER and not can_access_merchant(request.user, item.merchant):
            return deny()
        decision = request.data.get("status")
        if decision not in {
            IdentityCandidate.Status.ACCEPTED,
            IdentityCandidate.Status.REJECTED,
            IdentityCandidate.Status.DEFERRED,
        }:
            return Response({"error": "Choose accept, reject, or defer."}, status=400)
        item.status = decision
        item.decision_notes = str(request.data.get("decision_notes", ""))[:5000]
        item.decided_by = request.user
        item.decided_at = timezone.now()
        item.save()
        record_audit(request, "identity_candidate_decided", item, {"status": decision})
        return Response(IdentityCandidateSerializer(item).data)


class InvestigationListView(APIView):
    def get(self, request):
        if request.user.role not in STAFF | {MERCHANT_ROLE}:
            return deny()
        cases = accessible_cases(request.user)
        if request.user.role == OFFICER:
            cases = cases.filter(assigned_officer=request.user)
        query = request.query_params.get("q", "").strip()
        if query:
            cases = cases.filter(
                Q(reference__icontains=query)
                | Q(merchant__business_name__icontains=query)
                | Q(reason__icontains=query)
            )
        for param in ("status", "priority"):
            if request.query_params.get(param):
                cases = cases.filter(**{param: request.query_params[param]})
        return paginated(cases, request, CaseSerializer)

    def post(self, request):
        if request.user.role not in ADMIN_SUPERVISOR:
            return deny()
        data = request.data.copy()
        serializer = CaseSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        case = serializer.save(
            reference=make_reference("CASE"),
            created_by=request.user,
            supervisor=request.user,
        )
        record_audit(request, "case_created", case)
        return Response(CaseSerializer(case).data, status=201)


class InvestigationDetailView(APIView):
    def get_object(self, request, case_id):
        return accessible_cases(request.user).filter(pk=case_id).first()

    def get(self, request, case_id):
        case = self.get_object(request, case_id)
        if not case:
            return Response({"error": "Case not found."}, status=404)
        return Response(
            {
                **CaseSerializer(case).data,
                "notes": CaseNoteSerializer(case.notes.select_related("author"), many=True).data,
            }
        )

    def patch(self, request, case_id):
        case = self.get_object(request, case_id)
        if not case:
            return Response({"error": "Case not found."}, status=404)
        if request.user.role == OFFICER:
            allowed = {"findings", "recommendation", "priority"}
            if set(request.data.keys()) - allowed:
                return deny("Officers may update findings, recommendations, and priority on assigned cases.")
        elif request.user.role not in ADMIN_SUPERVISOR:
            return deny()
        elif set(request.data.keys()) - {
            "findings",
            "recommendation",
            "priority",
            "due_date",
            "supervisory_decision",
            "closure_outcome",
        }:
            return deny("Use the assignment and status actions for case workflow changes.")
        serializer = CaseSerializer(case, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        record_audit(request, "case_updated", updated)
        return Response(CaseSerializer(updated).data)


class InvestigationAssignView(APIView):
    def post(self, request, case_id):
        if request.user.role not in ADMIN_SUPERVISOR:
            return deny()
        case = accessible_cases(request.user).filter(pk=case_id).first()
        if not case:
            return Response({"error": "Case not found."}, status=404)
        officer = User.objects.filter(pk=request.data.get("officer_id"), role=OFFICER, is_active=True).first()
        if not officer:
            return Response({"error": "Select an active officer account."}, status=400)
        if request.user.role == SUPERVISOR and request.user.department and officer.department != request.user.department:
            return deny("You can only assign officers in your department.")
        case.assigned_officer = officer
        case.supervisor = request.user
        case.save(update_fields=["assigned_officer", "supervisor", "updated_at"])
        record_audit(request, "case_assigned", case, {"officer": officer.username})
        return Response(CaseSerializer(case).data)


class InvestigationTransitionView(APIView):
    def post(self, request, case_id):
        case = accessible_cases(request.user).filter(pk=case_id).first()
        if not case:
            return Response({"error": "Case not found."}, status=404)
        target = request.data.get("status")
        if request.user.role == OFFICER:
            transitions = {
                Investigation.Status.OPEN: {Investigation.Status.IN_REVIEW, Investigation.Status.ESCALATED},
                Investigation.Status.RETURNED: {
                    Investigation.Status.IN_REVIEW,
                    Investigation.Status.RECOMMENDED,
                    Investigation.Status.ESCALATED,
                },
                Investigation.Status.IN_REVIEW: {
                    Investigation.Status.RECOMMENDED,
                    Investigation.Status.ESCALATED,
                },
            }
        elif request.user.role in ADMIN_SUPERVISOR:
            transitions = {
                Investigation.Status.OPEN: {Investigation.Status.IN_REVIEW, Investigation.Status.ESCALATED},
                Investigation.Status.IN_REVIEW: {
                    Investigation.Status.RETURNED,
                    Investigation.Status.APPROVED,
                    Investigation.Status.ESCALATED,
                },
                Investigation.Status.RETURNED: {
                    Investigation.Status.IN_REVIEW,
                    Investigation.Status.APPROVED,
                    Investigation.Status.ESCALATED,
                },
                Investigation.Status.RECOMMENDED: {
                    Investigation.Status.RETURNED,
                    Investigation.Status.APPROVED,
                    Investigation.Status.ESCALATED,
                },
                Investigation.Status.APPROVED: {Investigation.Status.CLOSED},
                Investigation.Status.ESCALATED: {
                    Investigation.Status.IN_REVIEW,
                    Investigation.Status.CLOSED,
                },
            }
        else:
            return deny()
        if target not in transitions.get(case.status, set()):
            return Response({"error": "That case status transition is not allowed for your role."}, status=400)
        case.status = target
        if target in {Investigation.Status.APPROVED, Investigation.Status.RETURNED}:
            case.supervisory_decision = str(request.data.get("decision", ""))[:5000]
        if target == Investigation.Status.CLOSED:
            case.closure_outcome = str(request.data.get("closure_outcome", ""))[:180]
        case.save()
        record_audit(request, "case_status_changed", case, {"status": target})
        return Response(CaseSerializer(case).data)


class InvestigationNotesView(APIView):
    def post(self, request, case_id):
        case = accessible_cases(request.user).filter(pk=case_id).first()
        if not case:
            return Response({"error": "Case not found."}, status=404)
        body = str(request.data.get("body", "")).strip()
        if not body:
            return Response({"error": "Note cannot be empty."}, status=400)
        note = CaseNote.objects.create(
            case=case,
            author=request.user,
            body=body[:5000],
            is_evidence_note=bool(request.data.get("is_evidence_note", False)),
        )
        record_audit(request, "case_note_added", case)
        return Response(CaseNoteSerializer(note).data, status=201)


class UserAdminView(APIView):
    def get(self, request):
        if request.user.role != ADMIN:
            return deny()
        return Response(UserSerializer(User.objects.all().order_by("role", "username"), many=True).data)

    def post(self, request):
        if request.user.role != ADMIN:
            return deny()
        username = str(request.data.get("username", "")).strip()
        email = str(request.data.get("email", "")).strip().lower()
        role = request.data.get("role")
        password = str(request.data.get("password", ""))
        if role not in User.Role.values or not username or not email:
            return Response({"error": "Username, email, and a valid role are required."}, status=400)
        if User.objects.filter(Q(username=username) | Q(email=email)).exists():
            return Response({"error": "Username or email is already in use."}, status=409)
        user = User(username=username, email=email, role=role, department=str(request.data.get("department", "")))
        try:
            validate_password(password, user=user)
        except DjangoValidationError as exc:
            return Response({"error": list(exc.messages)}, status=400)
        user.set_password(password)
        user.save()
        record_audit(request, "user_created", user, {"role": role})
        return Response(UserSerializer(user).data, status=201)


class OfficerListView(APIView):
    def get(self, request):
        if request.user.role not in ADMIN_SUPERVISOR:
            return deny()
        officers = User.objects.filter(role=OFFICER, is_active=True)
        if request.user.role == SUPERVISOR and request.user.department:
            officers = officers.filter(department=request.user.department)
        return Response(UserSerializer(officers.order_by("username"), many=True).data)


class SocialLeadListView(APIView):
    def get(self, request):
        if request.user.role not in STAFF:
            return deny()
        leads = SocialLead.objects.select_related("linked_merchant", "assigned_officer", "linked_case")
        if request.user.role == OFFICER:
            leads = leads.filter(Q(assigned_officer=request.user) | Q(assigned_officer__isnull=True))
        if request.query_params.get("platform"):
            leads = leads.filter(platform=request.query_params["platform"])
        if request.query_params.get("status"):
            leads = leads.filter(review_status=request.query_params["status"])
        query = request.query_params.get("q", "").strip()
        if query:
            leads = leads.filter(
                Q(profile_name__icontains=query)
                | Q(public_business_identifier__icontains=query)
                | Q(observation__icontains=query)
            )
        return paginated(leads, request, SocialLeadSerializer)

    def post(self, request):
        if request.user.role not in STAFF:
            return deny()
        serializer = SocialLeadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lead = serializer.save(
            reference=make_reference("SOC"),
            collection_method="manual",
            is_demo=False,
            assigned_officer=request.user if request.user.role == OFFICER else None,
        )
        record_audit(request, "social_lead_created", lead, {"platform": lead.platform, "method": "manual"})
        return Response(SocialLeadSerializer(lead).data, status=201)


class SocialLeadImportView(APIView):
    def post(self, request):
        if request.user.role not in {ADMIN, SUPERVISOR}:
            return deny()
        platform = request.data.get("platform")
        if platform not in SocialLead.Platform.values:
            return Response({"error": "Select Facebook, Instagram, or X."}, status=400)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": "Choose a CSV file to import."}, status=400)
        try:
            rows = csv.DictReader(io.StringIO(upload.read().decode("utf-8-sig")))
        except UnicodeDecodeError:
            return Response({"error": "The CSV must be UTF-8 encoded."}, status=400)
        required = {"profile_name", "observation"}
        missing = sorted(required - set(rows.fieldnames or []))
        if missing:
            return Response({"error": "CSV is missing required columns.", "missing_columns": missing}, status=400)
        accepted = 0
        errors = []
        for row_number, row in enumerate(rows, start=2):
            name = (row.get("profile_name") or "").strip()
            observation = (row.get("observation") or "").strip()
            if not name or not observation:
                errors.append({"row": row_number, "message": "profile_name and observation are required"})
                continue
            profile_url = (row.get("profile_url") or "").strip()
            if profile_url and not profile_url.startswith(("https://", "http://")):
                errors.append({"row": row_number, "message": "profile_url must begin with http:// or https://"})
                continue
            lead = SocialLead.objects.create(
                reference=make_reference("SOC"),
                platform=platform,
                profile_name=name[:180],
                profile_url=profile_url[:200],
                public_business_identifier=(row.get("public_business_identifier") or "").strip()[:180],
                observation=observation[:5000],
                source_reference=(row.get("source_reference") or "").strip()[:180],
                collection_method="csv",
                assigned_officer=request.user if request.user.role == OFFICER else None,
            )
            accepted += 1
        record_audit(
            request, "social_lead_csv_import", details={"platform": platform, "accepted": accepted, "errors": len(errors)}
        )
        return Response({"accepted": accepted, "rejected": len(errors), "errors": errors}, status=201)


class SocialLeadReviewView(APIView):
    def patch(self, request, lead_id):
        if request.user.role not in STAFF:
            return deny()
        lead = SocialLead.objects.filter(pk=lead_id).first()
        if not lead:
            return Response({"error": "Social intelligence lead not found."}, status=404)
        if request.user.role == OFFICER and lead.assigned_officer_id not in {None, request.user.id}:
            return deny()
        status_value = request.data.get("review_status")
        allowed = {
            SocialLead.ReviewStatus.REVIEWED,
            SocialLead.ReviewStatus.REQUIRES_REVIEW,
            SocialLead.ReviewStatus.LINKED,
            SocialLead.ReviewStatus.REJECTED,
        }
        if status_value not in allowed:
            return Response({"error": "Choose a valid review status."}, status=400)
        merchant_id = request.data.get("linked_merchant")
        if status_value == SocialLead.ReviewStatus.LINKED and not (merchant_id or lead.linked_merchant_id):
            return Response({"error": "Select a merchant before confirming a link."}, status=400)
        if merchant_id:
            merchant = Merchant.objects.filter(pk=merchant_id).first()
            if not merchant or not can_access_merchant(request.user, merchant):
                return Response({"error": "Merchant not found."}, status=404)
            lead.linked_merchant = merchant
            lead.match_status = "proposed" if status_value != SocialLead.ReviewStatus.LINKED else "confirmed_by_reviewer"
        lead.review_status = status_value
        lead.reviewer_comments = str(request.data.get("reviewer_comments", ""))[:5000]
        if request.user.role == OFFICER and not lead.assigned_officer_id:
            lead.assigned_officer = request.user
        lead.save()
        record_audit(request, "social_lead_reviewed", lead, {"review_status": status_value})
        return Response(SocialLeadSerializer(lead).data)


class SocialLeadCaseView(APIView):
    def post(self, request, lead_id):
        if request.user.role not in ADMIN_SUPERVISOR:
            return deny()
        lead = SocialLead.objects.select_related("linked_merchant").filter(pk=lead_id).first()
        if not lead:
            return Response({"error": "Social intelligence lead not found."}, status=404)
        if not lead.linked_merchant or lead.review_status != SocialLead.ReviewStatus.LINKED:
            return Response({"error": "Review and link the lead to a merchant before creating a case."}, status=409)
        case = Investigation.objects.create(
            reference=make_reference("CASE"),
            merchant=lead.linked_merchant,
            source=f"{lead.platform.title()} social intelligence",
            reason=f"Reviewed lead {lead.reference}: {lead.observation[:1000]}",
            supervisor=request.user,
            created_by=request.user,
        )
        lead.linked_case = case
        lead.save(update_fields=["linked_case"])
        record_audit(request, "case_created_from_social_lead", case, {"lead": lead.reference})
        return Response(CaseSerializer(case).data, status=201)


class TarmStatusView(APIView):
    def get(self, request):
        if request.user.role not in STAFF:
            return deny()
        verifications = TarmVerification.objects.select_related("merchant")
        transfers = TarmTransfer.objects.select_related("merchant", "declaration")
        if request.user.role == OFFICER or (
            request.user.role == SUPERVISOR and request.user.department
        ):
            merchant_ids = accessible_merchant_ids(request.user)
            verifications = verifications.filter(merchant_id__in=merchant_ids)
            transfers = transfers.filter(merchant_id__in=merchant_ids)
        return Response(
            {
                "environment": "simulated",
                "source": "Simulated TaRMS adapter",
                "live_configured": False,
                "message": "Live service remains disabled until an authorized interface and credentials are supplied.",
                "recent_verifications": TarmVerificationSerializer(
                    verifications[:10], many=True
                ).data,
                "recent_transfers": TarmTransferSerializer(
                    transfers[:10], many=True
                ).data,
            }
        )


class TarmVerifyView(APIView):
    def post(self, request):
        merchant_id = request.data.get("merchant_id")
        merchant = Merchant.objects.filter(pk=merchant_id).first() if merchant_id else None
        if not merchant:
            return Response({"error": "Merchant not found."}, status=404)
        if request.user.role not in STAFF and not (
            request.user.role == MERCHANT_ROLE and merchant.user_id == request.user.id
        ):
            return deny()
        if request.user.role == OFFICER and not can_access_merchant(request.user, merchant):
            return deny()
        verification = simulated_tarm_check(merchant, request.user)
        record_audit(
            request,
            "tarm_tin_checked",
            verification,
            {"outcome": verification.outcome, "environment": "simulated"},
        )
        return Response(TarmVerificationSerializer(verification).data)


class TarmLinkView(APIView):
    def post(self, request):
        if request.user.role not in STAFF:
            return deny()
        merchant = Merchant.objects.filter(pk=request.data.get("merchant_id")).first()
        if not merchant or not can_access_merchant(request.user, merchant):
            return Response({"error": "Merchant not found."}, status=404)
        verification = merchant.tarm_verifications.order_by("-verified_at").first()
        if not verification or verification.outcome != "registered":
            return Response({"error": "Run a successful TaRMS registration check before linking."}, status=409)
        external_id = verification.permitted_details.get("external_id")
        if not external_id:
            return Response({"error": "The simulated adapter did not return a taxpayer identifier."}, status=409)
        if TarmLink.objects.filter(merchant=merchant).exists():
            return Response({"error": "This merchant already has a TaRMS link."}, status=409)
        if TarmLink.objects.filter(external_id=external_id).exists():
            return Response({"error": "That TaRMS taxpayer is already linked."}, status=409)
        link = TarmLink.objects.create(
            merchant=merchant,
            external_id=external_id,
            matched_tin=merchant.tin,
            source=verification.source,
            verified_at=verification.verified_at,
            linked_by=request.user,
        )
        record_audit(request, "tarm_taxpayer_linked", link, {"external_id": external_id})
        return Response(TarmLinkSerializer(link).data, status=201)


class TarmTransferPreviewView(APIView):
    def post(self, request):
        if request.user.role not in STAFF:
            return deny()
        raw_ids = request.data.get("declaration_ids", [])
        if not isinstance(raw_ids, list) or not raw_ids:
            return Response({"error": "Select at least one declaration."}, status=400)
        try:
            ids = [int(value) for value in raw_ids]
        except (TypeError, ValueError):
            return Response({"error": "Declaration IDs must be numbers."}, status=400)
        declarations = Declaration.objects.select_related("merchant").filter(id__in=ids)
        if request.user.role in {OFFICER, SUPERVISOR} and (
            request.user.role == OFFICER or request.user.department
        ):
            declarations = declarations.filter(merchant_id__in=accessible_merchant_ids(request.user))
        rows = []
        for declaration in declarations:
            linked = TarmLink.objects.filter(merchant=declaration.merchant).first()
            issues = []
            if declaration.status != Declaration.Status.SUBMITTED:
                issues.append("Declaration is not submitted.")
            if not linked:
                issues.append("Merchant has no verified TaRMS link.")
            if declaration.declared_revenue < 0 or declaration.tax_amount < 0:
                issues.append("Declaration contains an invalid amount.")
            rows.append(
                {
                    "declaration_id": declaration.id,
                    "reference": declaration.reference,
                    "merchant": declaration.merchant.business_name,
                    "tin": declaration.merchant.tin,
                    "period": declaration.period,
                    "currency": declaration.currency,
                    "declared_revenue": declaration.declared_revenue,
                    "tax_amount": declaration.tax_amount,
                    "external_taxpayer_id": linked.external_id if linked else None,
                    "eligible": not issues,
                    "issues": issues,
                }
            )
        return Response(
            {
                "environment": "simulated",
                "requires_confirmation": True,
                "eligible_count": sum(1 for row in rows if row["eligible"]),
                "excluded_count": sum(1 for row in rows if not row["eligible"]),
                "records": rows,
            }
        )


class TarmTransferView(APIView):
    def get(self, request):
        if request.user.role not in STAFF:
            return deny()
        transfers = TarmTransfer.objects.select_related("merchant", "declaration")
        if request.user.role == OFFICER:
            transfers = transfers.filter(merchant_id__in=accessible_merchant_ids(request.user))
        if request.query_params.get("status"):
            transfers = transfers.filter(status=request.query_params["status"])
        return paginated(transfers, request, TarmTransferSerializer)

    def post(self, request):
        if request.user.role not in STAFF:
            return deny()
        if request.data.get("confirm") is not True:
            return Response({"error": "Confirm the transfer after reviewing the preview."}, status=400)
        declaration = Declaration.objects.select_related("merchant").filter(
            pk=request.data.get("declaration_id")
        ).first()
        if not declaration or not can_access_merchant(request.user, declaration.merchant):
            return Response({"error": "Declaration not found."}, status=404)
        try:
            idem_key = UUID(str(request.data.get("idempotency_key")))
        except (TypeError, ValueError, AttributeError):
            return Response({"error": "A valid idempotency key is required."}, status=400)
        existing = TarmTransfer.objects.filter(idempotency_key=idem_key).first()
        if existing:
            return Response(TarmTransferSerializer(existing).data)
        linked = TarmLink.objects.filter(merchant=declaration.merchant).first()
        if not linked:
            return Response({"error": "Merchant has no verified TaRMS link."}, status=409)
        if declaration.status != Declaration.Status.SUBMITTED:
            return Response({"error": "Only submitted declarations can be transferred."}, status=409)
        if TarmTransfer.objects.filter(
            declaration=declaration, status=TarmTransfer.Status.SUCCESS
        ).exists():
            return Response({"error": "This declaration has already been transferred successfully."}, status=409)

        if declaration.tax_amount <= 0:
            outcome = TarmTransfer.Status.REJECTED
            response_data = {"code": "INVALID_TAX_AMOUNT", "message": "Tax amount must be greater than zero."}
        elif declaration.currency not in {"USD", "ZWL"}:
            outcome = TarmTransfer.Status.REVIEW
            response_data = {"code": "UNSUPPORTED_CURRENCY", "message": "Requires manual review in the simulated adapter."}
        else:
            outcome = TarmTransfer.Status.SUCCESS
            response_data = {
                "code": "SIMULATED_ACCEPTED",
                "message": "The simulated TaRMS adapter accepted this fictional record.",
                "external_receipt": make_reference("SIM"),
            }
        transfer = TarmTransfer.objects.create(
            reference=make_reference("TRF"),
            merchant=declaration.merchant,
            declaration=declaration,
            status=outcome,
            environment="simulated",
            idempotency_key=idem_key,
            adapter_response=response_data,
            submitted_by=request.user,
        )
        record_audit(request, "tarm_transfer_submitted", transfer, {"status": outcome})
        return Response(TarmTransferSerializer(transfer).data, status=201)


class AuditLogView(APIView):
    def get(self, request):
        if request.user.role not in ADMIN_SUPERVISOR:
            return deny()
        events = AuditEvent.objects.select_related("actor")
        if request.query_params.get("action"):
            events = events.filter(action=request.query_params["action"])
        return paginated(events, request, AuditEventSerializer)


class CsvExportView(APIView):
    def get(self, request):
        kind = request.query_params.get("type", "transactions")
        if request.user.role not in STAFF and not (
            request.user.role == MERCHANT_ROLE and kind == "declarations"
        ):
            return deny()
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="tmcis-{kind}-export.csv"'
        writer = csv.writer(response)
        if kind == "transactions":
            records = Transaction.objects.select_related("source", "merchant")
            if request.user.role == OFFICER:
                merchant_ids = accessible_merchant_ids(request.user)
                tins = Merchant.objects.filter(id__in=merchant_ids).values_list("tin", flat=True)
                records = records.filter(Q(merchant_id__in=merchant_ids) | Q(tin__in=tins))
            writer.writerow(["reference", "source", "tin", "transaction_at", "amount", "currency", "status", "provenance"])
            for row in records.order_by("-transaction_at")[:10000]:
                writer.writerow([
                    row.reference, row.source.name, row.tin, row.transaction_at.isoformat(),
                    row.amount, row.currency, row.reconciliation_status, row.provenance,
                ])
        elif kind == "declarations":
            records = Declaration.objects.select_related("merchant")
            if request.user.role == MERCHANT_ROLE:
                own = getattr(request.user, "merchant_profile", None)
                records = records.filter(merchant=own) if own else records.none()
            elif request.user.role in {OFFICER, SUPERVISOR} and (
                request.user.role == OFFICER or request.user.department
            ):
                records = records.filter(merchant_id__in=accessible_merchant_ids(request.user))
            writer.writerow(["reference", "merchant", "tin", "period", "currency", "revenue", "tax", "status"])
            for row in records.order_by("-created_at")[:10000]:
                writer.writerow([
                    row.reference, row.merchant.business_name, row.merchant.tin, row.period,
                    row.currency, row.declared_revenue, row.tax_amount, row.status,
                ])
        elif kind == "cases":
            records = accessible_cases(request.user)
            writer.writerow(["reference", "merchant", "priority", "status", "officer", "due_date"])
            for row in records[:10000]:
                writer.writerow([
                    row.reference, row.merchant.business_name, row.priority, row.status,
                    row.assigned_officer.username if row.assigned_officer else "", row.due_date or "",
                ])
        elif kind == "social-leads":
            if request.user.role == OFFICER:
                records = SocialLead.objects.filter(Q(assigned_officer=request.user) | Q(assigned_officer__isnull=True))
            else:
                records = SocialLead.objects.all()
            writer.writerow(["reference", "platform", "profile_name", "profile_url", "review_status", "collection_method"])
            for row in records[:10000]:
                writer.writerow([
                    row.reference, row.platform, row.profile_name, row.profile_url,
                    row.review_status, row.collection_method,
                ])
        else:
            return Response({"error": "Unsupported export type."}, status=400)
        record_audit(request, "csv_export", details={"type": kind})
        return response


class CsvTemplateView(APIView):
    def get(self, request, template_name):
        allowed = {
            "transactions.csv",
            "merchants.csv",
            "declarations.csv",
            "facebook-leads.csv",
            "instagram-leads.csv",
            "x-leads.csv",
            "tarm-transfer-preparation.csv",
            "ecocash.csv",
            "onemoney.csv",
            "cbz-bank.csv",
            "stanbic-bank.csv",
            "fbc-bank.csv",
            "cabs.csv",
            "zb-bank.csv",
            "other-bank.csv",
        }
        if template_name not in allowed:
            return Response({"error": "Template not found."}, status=404)
        template_path = Path(__file__).resolve().parent.parent / "csv_templates" / template_name
        if not template_path.is_file():
            return Response({"error": "Template not found."}, status=404)
        record_audit(request, "csv_template_downloaded", details={"template": template_name})
        return FileResponse(
            template_path.open("rb"),
            as_attachment=True,
            filename=template_name,
            content_type="text/csv",
        )
