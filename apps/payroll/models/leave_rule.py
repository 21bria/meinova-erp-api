from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class PayrollLeaveRule(BaseModel):
    """
    Adapter Payroll → Cuti: jenis cuti mana yang **tidak dibayar**.

    `LeaveType` di master HR tidak menyimpan penanda dibayar/tidak, dan
    menambahkannya di sana berarti mengubah modul sumber hanya untuk
    kepentingan payroll. Aturannya karena itu tinggal di Payroll, persis
    seperti adapter lain di modul ini: dependensinya terisolasi, dan
    modul Cuti tidak perlu tahu payroll ada.

    **Baris yang tidak ada = cuti dibayar.** Itu perilaku lama, dan
    tenant yang belum mengisi tabel ini tidak kehilangan sepeser pun
    hanya karena sebuah tabel baru lahir kosong.
    """

    leave_type = models.ForeignKey(
        "administration.LeaveType",
        on_delete=models.CASCADE,
        related_name="payroll_rules",
    )

    is_unpaid = models.BooleanField(
        default=False,
        help_text=(
            "Hari cuti jenis ini dihitung sebagai hari tidak dibayar."
        ),
    )

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_leave_rule"
        ordering = ["leave_type__code"]
        verbose_name = "Payroll Leave Rule"
        verbose_name_plural = "Payroll Leave Rules"

        constraints = [
            models.UniqueConstraint(
                fields=["leave_type"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_leave_rule",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.leave_type_id} - unpaid={self.is_unpaid}"
