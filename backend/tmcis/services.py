from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from uuid import uuid4

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    AuditEvent,
    Declaration,
    FinancialDataSource,
    Investigation,
    Merchant,
    ReconciliationResult,
    RiskAssessment,
    RiskRule,
    SocialLead,
    TarmTaxpayer,
    TarmVerification,
    Transaction,
)

RISK_LIMITATIONS = [
    "This score is an explainable review aid, not proof of wrongdoing or a tax determination.",
    "All included bank, mobile-money, social-intelligence, and TaRMS records are fictional demo data.",
    "Only authorized, reviewed source data should be considered; missing or unavailable data can change results.",
]


def make_reference(prefix):
    return f"{prefix}-{uuid4().hex[:10].upper()}"


def record_audit(request, action, obj=None, details=None):
    actor = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        entity_type=obj.__class__.__name__ if obj else "",
        entity_id=str(obj.pk) if obj and obj.pk else "",
        details=details or {},
        ip_address=request.META.get("REMOTE_ADDR") if request else None,
    )


def band_for_score(score):
    if score >= 75:
        return RiskAssessment.Band.CRITICAL
    if score >= 50:
        return RiskAssessment.Band.HIGH
    if score >= 25:
        return RiskAssessment.Band.MEDIUM
    return RiskAssessment.Band.LOW


def assess_merchant_risk(merchant, user=None):
    rules = {rule.code: rule for rule in RiskRule.objects.filter(enabled=True)}
    exceptions = ReconciliationResult.objects.filter(
        declaration__merchant=merchant
    ).exclude(status=ReconciliationResult.Status.MATCHED)
    unresolved = exceptions.filter(resolved_at__isnull=True).count()
    duplicate_transactions = Transaction.objects.filter(
        Q(merchant=merchant) | Q(tin=merchant.tin),
        reconciliation_status=Transaction.ReconciliationStatus.DUPLICATE,
    ).count()
    missing_information = Declaration.objects.filter(
        merchant=merchant,
        status=Declaration.Status.NEEDS_INFO,
    ).count()

    signals = {
        "reconciliation_discrepancy": {
            "triggered": exceptions.exists(),
            "evidence": f"{exceptions.count()} reconciliation exception(s) recorded.",
        },
        "repeated_unresolved_exceptions": {
            "triggered": unresolved >= 2,
            "evidence": f"{unresolved} unresolved exception(s) are recorded.",
        },
        "duplicate_transaction_indicator": {
            "triggered": duplicate_transactions > 0,
            "evidence": f"{duplicate_transactions} transaction record(s) are flagged as potential duplicates.",
        },
        "information_requested": {
            "triggered": missing_information > 0,
            "evidence": f"{missing_information} declaration(s) have an outstanding information request.",
        },
    }

    triggered = []
    evidence = []
    score = 0
    for code, signal in signals.items():
        rule = rules.get(code)
        if not rule or not signal["triggered"]:
            continue
        score += rule.points
        triggered.append(
            {"code": rule.code, "title": rule.title, "points": rule.points, "description": rule.description}
        )
        evidence.append({"rule": rule.code, "summary": signal["evidence"]})
    score = min(score, 100)
    version = max((rule.version for rule in rules.values()), default=1)
    return RiskAssessment.objects.create(
        merchant=merchant,
        score=score,
        band=band_for_score(score),
        triggered_rules=triggered,
        evidence=evidence,
        limitations=RISK_LIMITATIONS,
        rule_set_version=version,
        created_by=user,
    )


def run_reconciliation(user=None):
    results = []
    declarations = Declaration.objects.filter(
        status__in=[Declaration.Status.SUBMITTED, Declaration.Status.NEEDS_INFO]
    ).select_related("merchant")
    for declaration in declarations:
        year, month = map(int, declaration.period.split("-"))
        start = timezone.make_aware(datetime(year, month, 1))
        if month == 12:
            end = timezone.make_aware(datetime(year + 1, 1, 1))
        else:
            end = timezone.make_aware(datetime(year, month + 1, 1))

        base = Transaction.objects.filter(
            Q(merchant=declaration.merchant) | Q(tin=declaration.merchant.tin),
            transaction_at__gte=start,
            transaction_at__lt=end,
        ).distinct()
        same_currency = base.filter(currency=declaration.currency)
        total = same_currency.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        other_currency = base.exclude(currency=declaration.currency)
        if not base.exists():
            status = ReconciliationResult.Status.UNMATCHED_DECLARATION
            reason = "No transaction records matched the merchant, TIN, and declaration period."
            matched = base
            total_value = Decimal("0.00")
        elif not same_currency.exists():
            status = ReconciliationResult.Status.CURRENCY
            reason = "Candidate transaction records exist, but none use the declaration currency."
            matched = other_currency
            total_value = Decimal("0.00")
        else:
            matched = same_currency
            total_value = total
            delta = total_value - declaration.declared_revenue
            if abs(delta) <= Decimal("0.01"):
                status = ReconciliationResult.Status.MATCHED
                reason = "Recorded transaction total equals declared revenue for the period and currency."
            elif total_value < declaration.declared_revenue:
                status = ReconciliationResult.Status.PARTIAL
                reason = "Available transaction total is lower than declared revenue; review source coverage."
            else:
                status = ReconciliationResult.Status.AMOUNT
                reason = "Available transaction total is higher than declared revenue; review source coverage."

        result = ReconciliationResult.objects.create(
            declaration=declaration,
            status=status,
            declared_amount=declaration.declared_revenue,
            observed_amount=total_value,
            amount_difference=total_value - declaration.declared_revenue,
            reason=reason,
            rule_snapshot={
                "method": "TIN or merchant link + period + currency aggregate",
                "source_codes": list(matched.values_list("source__code", flat=True).distinct()),
                "candidate_count": matched.count(),
                "data_scope": "Fictional demo sources unless explicitly imported by an authorized operator.",
            },
            is_demo=declaration.is_demo,
        )
        result.transactions.set(matched)
        if status == ReconciliationResult.Status.MATCHED:
            matched.update(reconciliation_status=Transaction.ReconciliationStatus.MATCHED)
        else:
            matched.update(reconciliation_status=Transaction.ReconciliationStatus.REVIEW)
        results.append(result)
    return results


def simulated_tarm_check(merchant, user=None):
    if not merchant.tin.isdigit() or len(merchant.tin) != 10 or not merchant.tin.startswith("200076899"):
        outcome = TarmVerification.Outcome.INVALID
        details = {}
    else:
        taxpayer = TarmTaxpayer.objects.filter(tin=merchant.tin).first()
        if taxpayer:
            outcome = TarmVerification.Outcome.REGISTERED
            details = {
                "external_id": taxpayer.external_id,
                "taxpayer_name": taxpayer.permitted_name,
                "registration_status": taxpayer.status,
            }
        else:
            outcome = TarmVerification.Outcome.NOT_REGISTERED
            details = {}
    return TarmVerification.objects.create(
        merchant=merchant,
        checked_by=user,
        outcome=outcome,
        environment="simulated",
        source="Simulated TaRMS adapter",
        permitted_details=details,
    )


def dashboard_counts(user):
    role = user.role
    merchant = getattr(user, "merchant_profile", None)
    cases = Investigation.objects.all()
    declarations = Declaration.objects.all()
    transactions = Transaction.objects.all()
    if role == "merchant" and merchant:
        declarations = declarations.filter(merchant=merchant)
        transactions = transactions.filter(Q(merchant=merchant) | Q(tin=merchant.tin))
        cases = cases.filter(merchant=merchant)
        leads = SocialLead.objects.none()
    elif role == "officer":
        cases = cases.filter(assigned_officer=user)
        merchant_ids = cases.values_list("merchant_id", flat=True)
        declarations = declarations.filter(merchant_id__in=merchant_ids)
        transactions = transactions.filter(
            Q(merchant_id__in=merchant_ids)
            | Q(tin__in=Merchant.objects.filter(id__in=merchant_ids).values("tin"))
        )
        leads = SocialLead.objects.filter(Q(assigned_officer=user) | Q(assigned_officer__isnull=True))
    else:
        if role == "supervisor" and user.department:
            cases = cases.filter(
                Q(supervisor=user)
                | Q(assigned_officer__department=user.department)
                | Q(supervisor__isnull=True)
            )
        leads = SocialLead.objects.all()

    value_by_currency = list(
        transactions.values("currency").annotate(total=Sum("amount")).order_by("currency")
    )
    source_totals = list(
        transactions.values("source__name", "source__code")
        .annotate(count=Count("id"), total=Sum("amount"))
        .order_by("source__name")
    )
    return {
        "role": role,
        "merchants": Merchant.objects.count() if role in {"admin", "supervisor"} else 0,
        "declarations": declarations.count(),
        "submitted_declarations": declarations.filter(status=Declaration.Status.SUBMITTED).count(),
        "transactions": transactions.count(),
        "transaction_value_by_currency": value_by_currency,
        "source_totals": source_totals,
        "open_cases": cases.exclude(status__in=[Investigation.Status.CLOSED, Investigation.Status.APPROVED]).count(),
        "overdue_cases": cases.filter(due_date__lt=timezone.localdate()).exclude(
            status__in=[Investigation.Status.CLOSED, Investigation.Status.APPROVED]
        ).count(),
        "social_leads": leads.count(),
        "new_social_leads": leads.filter(review_status=SocialLead.ReviewStatus.NEW).count(),
        "reconciliation_exceptions": ReconciliationResult.objects.exclude(
            status=ReconciliationResult.Status.MATCHED
        ).count(),
        "recent_transactions": list(transactions.select_related("source", "merchant")[:6].values(
            "id", "reference", "source__name", "amount", "currency", "transaction_at", "reconciliation_status"
        )),
        "recent_cases": list(cases.select_related("merchant", "assigned_officer")[:6].values(
            "id", "reference", "merchant__business_name", "status", "priority", "assigned_officer__username"
        )),
    }
