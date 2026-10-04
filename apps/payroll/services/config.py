"""
Service konfigurasi tambahan di atas Payroll Master existing.

Empat master kecil yang isinya angka, bukan proses. Yang dijaga
service-nya cuma satu: **baris yang sudah dipakai payroll terkunci tidak
boleh dihapus.** Menghapusnya membuat komponen di slip yang sudah terbit
menunjuk baris yang tidak ada lagi, dan rincian perhitungannya jadi
tidak bisa ditelusuri.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from apps.core.services.master import BaseMasterService
from apps.payroll.models import (
    AllowanceTemplateLine,
    DeductionTemplateLine,
    OvertimeGroupTier,
    PayrollLeaveRule,
    PayrollRunStatus,
    PayrollTaxBracket,
)


class _ComponentLineService(BaseMasterService):
    reference_type = ""

    @classmethod
    def get_queryset(cls):
        return super().get_queryset().select_related("template")

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        from apps.payroll.models import PayrollRunComponent

        used = (
            PayrollRunComponent.objects
            .filter(
                reference_type=cls.reference_type,
                reference_id=str(instance.pk),
                run_employee__run__status=PayrollRunStatus.FINALIZED,
                is_deleted=False,
            )
            .exists()
        )

        if used:
            raise ValidationError(
                {
                    "code": (
                        "Komponen ini sudah dipakai payroll yang "
                        "difinalisasi. Nonaktifkan saja (Active = off) "
                        "supaya rincian slip lama tetap bisa "
                        "ditelusuri."
                    ),
                },
            )

        return super().before_soft_delete(instance=instance, user=user, **kwargs)


class AllowanceTemplateLineService(_ComponentLineService):
    model = AllowanceTemplateLine
    reference_type = "payroll.allowance_template_line"


class DeductionTemplateLineService(_ComponentLineService):
    model = DeductionTemplateLine
    reference_type = "payroll.deduction_template_line"


class PayrollLeaveRuleService(BaseMasterService):
    model = PayrollLeaveRule

    @classmethod
    def get_queryset(cls):
        return super().get_queryset().select_related("leave_type")


class OvertimeGroupTierService(BaseMasterService):
    model = OvertimeGroupTier

    @classmethod
    def get_queryset(cls):
        return super().get_queryset().select_related("group")


class PayrollTaxBracketService(BaseMasterService):
    model = PayrollTaxBracket
