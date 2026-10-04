"""
Resolusi perlakuan payroll atas izin kehadiran.

Satu pintu, tiga lapis, urutan yang tetap — pola yang sama dengan
`PayrollPolicyService` di sebelah:

    1. `PayrollPermissionRule` yang menyebut kebijakan payroll pegawai
    2. `PayrollPermissionRule` yang menyebut company-nya
    3. baris global (company & policy kosong)

Tidak ada satu pun yang cocok → `INFORMATION_ONLY`, dan itu **bukan**
bawaan yang dipilih siapa pun: ia yang menjaga payroll yang sudah
berjalan tidak bergeser angkanya hanya karena modul izin lahir. Yang
membedakannya dari keputusan yang kebetulan sama adalah temuannya
(`PeriodFacts.notes`), bukan angkanya.

Ditulis sebagai resolver tersendiri, bukan sebagai `if` di adapter
sumber, karena pertanyaan "izin ini dibayar atau tidak" akan ditanyakan
lagi oleh laporan dan oleh layar rekap — dan tiga salinan aturan yang
harus sepakat tidak pernah tetap sepakat.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.payroll.models import (
    PayrollPermissionRule,
    PermissionPayTreatment,
)


@dataclass(frozen=True)
class ResolvedPermissionRule:
    treatment: str
    unpaid_over_minutes: int = 0
    rule_id: int | None = None

    @property
    def is_paid(self) -> bool:
        return self.treatment == PermissionPayTreatment.PAID

    @property
    def is_unpaid(self) -> bool:
        return self.treatment == PermissionPayTreatment.UNPAID

    @property
    def is_information_only(self) -> bool:
        return self.treatment == PermissionPayTreatment.INFORMATION_ONLY

    def split(self, minutes: int) -> tuple[int, int]:
        """
        Menit izin → `(dibayar, tidak dibayar)`.

        Ambang `unpaid_over_minutes` memotong **hanya kelebihannya**.
        Memotong seluruh durasinya membuat ambang jadi hukuman alih-alih
        batas: orang yang izin dua jam satu menit dipotong sama dengan
        yang izin sehari, dan tidak ada kebijakan yang bermaksud begitu.
        """
        minutes = max(0, int(minutes or 0))

        if minutes == 0:
            return (0, 0)

        if self.is_unpaid:
            return (0, minutes)

        if self.is_information_only:
            # Bukan nol-nol: menitnya tetap ada dan tetap dilaporkan.
            # Yang tidak ada perlakuan payroll-nya — dan itu terbaca
            # dari `permission_minutes` yang tidak habis dibagi
            # `paid + unpaid`.
            return (0, 0)

        if self.unpaid_over_minutes and minutes > self.unpaid_over_minutes:
            return (
                self.unpaid_over_minutes,
                minutes - self.unpaid_over_minutes,
            )

        return (minutes, 0)


DEFAULT = ResolvedPermissionRule(
    treatment=PermissionPayTreatment.INFORMATION_ONLY,
)


class PayrollPermissionRuleService:
    @staticmethod
    def load(*, company_id=None, payroll_policy_id=None) -> dict:
        """
        Aturan per jenis izin, sekali query.

        Mengembalikan `{permission_type: ResolvedPermissionRule}`.
        Jenis yang tidak punya baris **tidak** ikut di dalamnya —
        pemanggil memakai `resolve()` yang menjatuhkannya ke `DEFAULT`,
        supaya tidak ada dua tempat yang harus sepakat soal bawaannya.
        """
        rows = (
            PayrollPermissionRule.objects
            .filter(is_deleted=False, is_active=True)
            .filter(
                # Kosong berarti **berlaku untuk semua**, bukan "tidak
                # berlaku" — jebakan yang sudah berkali-kali muncul di
                # master berjenjang lain di sistem ini.
                models_scope(company_id, payroll_policy_id),
            )
        )

        best: dict[str, PayrollPermissionRule] = {}

        for row in rows:
            current = best.get(row.permission_type)

            if current is None or row.specificity > current.specificity:
                best[row.permission_type] = row

        return {
            key: ResolvedPermissionRule(
                treatment=row.treatment,
                unpaid_over_minutes=row.unpaid_over_minutes or 0,
                rule_id=row.pk,
            )
            for key, row in best.items()
        }

    @staticmethod
    def resolve(rules: dict, permission_type: str) -> ResolvedPermissionRule:
        return rules.get(permission_type, DEFAULT)


def models_scope(company_id, payroll_policy_id):
    from django.db.models import Q

    scope = Q(company__isnull=True) | Q(company_id=company_id)

    scope &= (
        Q(payroll_policy__isnull=True)
        | Q(payroll_policy_id=payroll_policy_id)
    )

    return scope
