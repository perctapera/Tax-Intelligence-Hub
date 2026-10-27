from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

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
    User as TmcisUser,
)


@admin.register(TmcisUser)
class TmcisUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("TMCIS access", {"fields": ("role", "department")}),)
    list_display = ("username", "email", "role", "department", "is_active")
    list_filter = ("role", "department", "is_active")


for model in [
    Merchant,
    Declaration,
    FinancialDataSource,
    ImportBatch,
    Transaction,
    ReconciliationResult,
    IdentityCandidate,
    RiskRule,
    RiskAssessment,
    Investigation,
    CaseNote,
    SocialLead,
    TarmTaxpayer,
    TarmVerification,
    TarmLink,
    TarmTransfer,
    AuditEvent,
]:
    admin.site.register(model)
