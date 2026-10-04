"""
Tanggal go-live cuti per perusahaan.

Service-nya tipis dengan sengaja: yang disimpan cuma satu tanggal, dan
seluruh akibatnya dibaca di tempat lain (`LeaveEntitlementCalculator`
lewat `LeaveGoLiveResolver`). Menaruh perhitungan apa pun di sini
berarti ada dua tempat yang memutuskan tahun mana yang dipegang sistem
lama.
"""

from __future__ import annotations

from typing import Any

from apps.core.services.master import BaseMasterService
from apps.hr.models import LeaveGoLive, LeaveOpeningBalance, LeaveOpeningStatus


class LeaveGoLiveService(BaseMasterService):
    model = LeaveGoLive

    @classmethod
    def list(cls, filters: dict[str, Any] | None = None, **kwargs):
        # `BaseMasterService` sengaja tidak menyediakan `list()`, dan
        # turunan yang lupa menulisnya membalas AssertionError begitu
        # daftarnya dibuka — lihat catatan asimetri di CLAUDE.md.
        queryset = (
            cls.model.objects
            .filter(is_deleted=False)
            .select_related("company")
        )

        if filters:
            queryset = queryset.filter(**filters)

        return queryset

    @classmethod
    def readiness(cls, instance) -> dict[str, Any]:
        """
        Ringkasan kesiapan satu perusahaan, dibaca layarnya.

        Angka-angka ini yang menjawab "sudah boleh dipakai belum" tanpa
        mengharuskan orang membuka layar saldo awal lalu menghitung
        sendiri berapa baris yang masih draft. Yang masih draft **belum**
        berlaku, dan itu justru keadaan yang paling mudah tidak
        disadari: barisnya sudah ada di layar, angkanya sudah benar, dan
        kartunya masih nol.
        """
        rows = LeaveOpeningBalance.objects.filter(
            employee__organization__company_id=instance.company_id,
            is_deleted=False,
        )

        draft = rows.filter(status=LeaveOpeningStatus.DRAFT).count()
        posted = rows.filter(status=LeaveOpeningStatus.POSTED).count()

        return {
            "draft_count": draft,
            "posted_count": posted,
            "total_count": draft + posted,
        }
