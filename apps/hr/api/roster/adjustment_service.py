"""
Dokumen penyesuaian jadwal roster yang sudah berjalan.

Kenapa ini dokumen, bukan tombol
--------------------------------
Menggeser jadwal orang yang tiketnya sudah dibeli bukan koreksi data —
itu keputusan. Karena itu ia punya nomor, alasan wajib, pengaju,
rangkaian persetujuan, dan jejak versi. Tombol "geser 2 hari" di layar
jadwal memberi hasil yang sama tanpa satu pun dari itu, dan enam bulan
kemudian tidak ada yang bisa menjawab kenapa jadwalnya begitu.

Yang dilakukan tiap jenis
-------------------------
Yang membedakan bukan berapa harinya, melainkan **siapa penyebabnya** —
dan itu tidak bisa disimpulkan dari selisih tanggal.

========================  ===============================  ==============
Jenis                     Jadwal                           Kredit (bawaan)
========================  ===============================  ==============
Work Extension            blok diperpanjang `days`         EARN
Early Return              blok dipendekkan `days`          —
Deferred Leave (KTT)      blok kerja diperpanjang `days`   EARN
Late Return (kesalahan)   blok off diperpanjang `days`     USE
Loyalty                   tidak berubah                    —
No Impact                 tidak berubah                    —
Schedule Shift            sisanya digeser `days`           —
Use Rotation Credit       blok dipendekkan `days`          USE
========================  ===============================  ==============

Tiga hal yang sengaja begitu:

* **Loyalty dan No Impact tetap dicatat.** Keduanya tidak mengubah satu
  tanggal pun, tapi "kenapa jadwal saya tidak berubah" harus punya
  jawaban tertulis — diam adalah jawaban terburuk.
* **Kompensasi off tidak diberikan langsung, melainkan lewat ledger.**
  Aturan #13 menyebut tambahan off = hari ÷ rasio; angka itu masuk
  sebagai kredit, lalu dipakai kapan pegawainya mau lewat dokumen
  ``Use Rotation Credit``. Memberikannya langsung berarti dua sumber
  angka untuk hak yang sama, dan yang satu diam-diam basi.
* **Blok berikutnya tidak dipendekkan** saat blok kerja diperpanjang.
  Yang tertahan di site seminggu tetap berhak atas field break penuh;
  memotongnya berarti perusahaan mengambil dua kali.
"""

from __future__ import annotations

import logging

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.core.services.master import BaseMasterService

from apps.hr.api.roster.credit_service import RotationCreditService
from apps.hr.api.roster.recalculation import RosterRecalculationService
from apps.hr.api.site_rotation.policy import (
    ConversionRatio,
    RosterPolicyResolver,
)
from apps.hr.models import (
    AdjustmentKind,
    AdjustmentStatus,
    CreditEntryType,
    CreditImpact,
    RosterAdjustment,
    RosterSegmentType,
    RosterVersionSource,
    SiteRotationStatus,
)


logger = logging.getLogger(__name__)


MODULE = "hr"
DOCUMENT_TYPE = "roster_adjustment"


# Bawaan dampak kredit per jenis. **Bawaan**, bukan aturan mati —
# kolomnya tetap bisa diubah pemakai, karena kapal yang delay pun
# kadang memang layak diberi kompensasi dan itu keputusan yang tidak
# bisa disimpulkan dari jenisnya saja.
DEFAULT_CREDIT_IMPACT = {
    AdjustmentKind.WORK_EXTENSION: CreditImpact.EARN,
    AdjustmentKind.DEFERRED_LEAVE: CreditImpact.EARN,
    AdjustmentKind.LATE_RETURN: CreditImpact.USE,
    AdjustmentKind.CREDIT_USE: CreditImpact.USE,
}


class RosterAdjustmentService(BaseMasterService):
    model = RosterAdjustment

    # ------------------------------------------------------------------
    # Penyiapan
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls.apply_plan_scope(data)
        data = cls.apply_credit_defaults(data)

        if not data.get("document_number"):
            data["document_number"] = DocumentNumberService.next(
                module=MODULE,
                document_type=DOCUMENT_TYPE,
                company=data.get("company"),
            )

        return data

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_editable(instance)

        data = cls.apply_plan_scope(data, instance=instance)
        data = cls.apply_credit_defaults(data, instance=instance)

        return data

    @staticmethod
    def apply_plan_scope(data, *, instance=None) -> dict[str, Any]:
        """
        Menyalin pegawai dan organisasi dari rencananya.

        Didenormalisasi supaya cakupan data dan filter tabel
        tidak perlu menembus dokumen induknya untuk tiap baris.
        """
        plan = data.get("plan") or getattr(instance, "plan", None)

        if plan is None:
            return data

        data["employee"] = plan.employee

        organization = getattr(plan.employee, "organization", None)

        data.setdefault("company", getattr(organization, "company", None))
        data.setdefault("branch", getattr(organization, "branch", None))
        data.setdefault("location", getattr(organization, "location", None))

        return data

    @classmethod
    def apply_credit_defaults(cls, data, *, instance=None) -> dict[str, Any]:
        """
        Mengisi dampak kredit dan angkanya kalau form tidak
        menyebutkannya.

        Angkanya dihitung dari rasio pola pegawai sendiri — 56:14 = 4,
        42:14 = 3 — bukan dari daftar per pola. Perusahaan yang besok
        memakai 9:3 tidak perlu menunggu ada yang menambah baris master.
        """
        kind = data.get("adjustment_kind") or getattr(
            instance, "adjustment_kind", None,
        )

        if kind is None:
            return data

        if not data.get("credit_impact") and instance is None:
            data["credit_impact"] = DEFAULT_CREDIT_IMPACT.get(
                kind, CreditImpact.NONE,
            )

        impact = data.get("credit_impact") or getattr(
            instance, "credit_impact", CreditImpact.NONE,
        )

        if impact == CreditImpact.NONE:
            data["credit_days"] = Decimal("0.00")

            return data

        if data.get("credit_days"):
            return data

        days = data.get("days") or getattr(instance, "days", 0)

        employee = data.get("employee") or getattr(
            instance, "employee", None,
        )

        if not days or employee is None:
            return data

        if impact == CreditImpact.EARN:
            plan = data.get("plan") or getattr(instance, "plan", None)

            data["credit_days"] = cls.convert(
                plan=plan,
                employee=employee,
                excess_days=days,
            ).credit_days
        else:
            # Pemakaian dihitung dalam satuan hari field break, jadi
            # tidak lewat rasio: satu hari libur yang diambil lebih awal
            # memakan satu hari saldo.
            data["credit_days"] = Decimal(str(days))

        return data

    @staticmethod
    def ratio_for(*, plan) -> "ConversionRatio":
        """
        Rasio kerja:off yang berlaku untuk rencana ini.

        Diambil dari pola yang **dibekukan ke rencana**, bukan dari
        policy yang berlaku di master sekarang. Dua alasan, dan yang
        kedua yang menentukan: (1) mengoreksi policy bulan depan tidak
        boleh mengubah arti penyesuaian atas jadwal yang sudah
        disetujui, dan (2) rencana bisa saja dibuat sebelum policy-nya
        menempel ke penempatan pegawai — dan rasio yang tidak ketemu
        menghasilkan nol kredit tanpa satu pun pesan.
        """
        return RosterPolicyResolver.ratio_from_pattern(
            work_days=getattr(plan, "cycle_work_days", None),
            off_days=getattr(plan, "cycle_off_days", None),
            policy=getattr(plan, "roster_policy", None),
        )

    @classmethod
    def convert(cls, *, plan, employee, excess_days):
        """Kelebihan hari kerja → kredit, memakai rasio rencana."""
        policy = getattr(plan, "roster_policy", None)

        balance = RotationCreditService.balance_for(employee)

        return RotationCreditService.convert(
            excess_days=excess_days,
            ratio=cls.ratio_for(plan=plan).value,
            rounding=getattr(policy, "credit_rounding", "floor"),
            carry_remainder=getattr(policy, "credit_carry_remainder", True),
            carried_days=balance.carried_excess_days,
        )

    @staticmethod
    def assert_editable(instance: RosterAdjustment) -> None:
        if instance.is_editable:
            return

        raise ValidationError(
            {
                "status": (
                    f"Dokumen berstatus {instance.get_status_display()} "
                    "tidak bisa disunting. Tarik dulu pengajuannya."
                ),
            },
        )

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    @classmethod
    def preview(cls, *, adjustment: RosterAdjustment) -> dict:
        """
        Jadwal sesudah penyesuaian, **tanpa menulis apa pun**.

        Yang dikembalikan sama persis dengan yang akan disimpan — sama
        perhitungannya, bukan sekadar mirip.
        """
        findings = cls.validate(adjustment)

        blocked = [
            item for item in findings if item.level == "blocking"
        ]

        result = {
            "validations": [item.as_dict() for item in findings],
            "credit": cls.credit_explanation(adjustment),
            "can_submit": not blocked,
        }

        if blocked or not adjustment.changes_schedule:
            result["schedule"] = None

            return result

        try:
            result["schedule"] = RosterRecalculationService.simulate(
                **cls.operation_kwargs(adjustment),
            )
        except ValidationError as error:
            result["schedule"] = None
            result["can_submit"] = False

            result["validations"].append(
                {
                    "level": "blocking",
                    "code": "recalculation_failed",
                    "message": "; ".join(
                        str(message)
                        for messages in getattr(
                            error, "message_dict", {},
                        ).values()
                        for message in messages
                    ) or str(error),
                },
            )

        return result

    @classmethod
    def validate(cls, adjustment: RosterAdjustment) -> list:
        from apps.hr.api.roster.services import blocking, warning

        findings = []

        plan = adjustment.plan

        if plan.status not in {
            SiteRotationStatus.ACTIVE,
            SiteRotationStatus.APPROVED,
        }:
            findings.append(
                blocking(
                    "plan_not_active",
                    f"Rencana {plan.document_number or plan.pk} berstatus "
                    f"{plan.get_status_display()}. Penyesuaian hanya "
                    "berlaku untuk jadwal yang sudah dibaselinekan — "
                    "yang masih draft cukup disunting langsung.",
                ),
            )

        if plan.baseline_version_id is None:
            findings.append(
                blocking(
                    "no_baseline",
                    "Rencana ini belum punya baseline. Setujui dulu "
                    "jadwalnya sebelum menyesuaikannya.",
                ),
            )

        block = RosterRecalculationService.block_at(
            plan=plan,
            on=adjustment.effective_date,
        )

        if adjustment.changes_schedule and block is None:
            findings.append(
                blocking(
                    "no_segment",
                    f"Tidak ada segmen jadwal yang memuat "
                    f"{adjustment.effective_date}. Periksa tanggalnya "
                    "terhadap horizon rencana.",
                ),
            )
        elif block is not None:
            expected = cls.expected_segment(adjustment.adjustment_kind)

            if expected and block.segment_type not in expected:
                findings.append(
                    warning(
                        "unexpected_segment",
                        f"{adjustment.get_adjustment_kind_display()} "
                        f"biasanya jatuh di blok "
                        f"{'/'.join(expected)}, tapi "
                        f"{adjustment.effective_date} ada di blok "
                        f"{block.get_segment_type_display()}. Tidak "
                        "menghalangi — cuma pastikan tanggalnya benar.",
                    ),
                )

        # Dua penyesuaian terbuka pada rencana yang sama akan diterapkan
        # berturut-turut, dan yang belakangan menghitung ulang di atas
        # jadwal yang sudah digeser yang duluan. Dua-duanya "disetujui",
        # dua-duanya terlihat benar.
        duplicate = (
            RosterAdjustment.objects
            .filter(
                plan=plan,
                is_deleted=False,
                status__in={
                    AdjustmentStatus.SUBMITTED,
                    AdjustmentStatus.APPROVED,
                },
            )
            .exclude(pk=adjustment.pk)
            .first()
        )

        if duplicate is not None:
            findings.append(
                blocking(
                    "open_adjustment_exists",
                    f"Masih ada penyesuaian berjalan untuk rencana ini "
                    f"({duplicate.document_number or duplicate.pk}). "
                    "Selesaikan dulu — dua penyesuaian yang berjalan "
                    "bersamaan dihitung berturut-turut dan hasilnya "
                    "bukan yang ditinjau siapa pun.",
                ),
            )

        if (
            adjustment.credit_impact == CreditImpact.USE
            and adjustment.credit_days
        ):
            balance = RotationCreditService.balance_for(adjustment.employee)

            if balance.balance < adjustment.credit_days:
                findings.append(
                    warning(
                        "insufficient_credit",
                        f"Saldo rotation credit {balance.balance}, "
                        f"dipakai {adjustment.credit_days}. Kalau policy "
                        "tidak mengizinkan saldo minus, penerapannya "
                        "akan gagal.",
                    ),
                )

        return findings

    @staticmethod
    def expected_segment(kind: str) -> tuple:
        if kind in {
            AdjustmentKind.WORK_EXTENSION,
            AdjustmentKind.DEFERRED_LEAVE,
            AdjustmentKind.EARLY_RETURN,
            AdjustmentKind.CREDIT_USE,
        }:
            return (RosterSegmentType.WORK,)

        if kind == AdjustmentKind.LATE_RETURN:
            return (RosterSegmentType.FIELD_BREAK,)

        return ()

    @classmethod
    def credit_explanation(cls, adjustment: RosterAdjustment) -> dict:
        """
        Penjelasan tertulis, termasuk untuk yang tidak berdampak.

        `loyalty` dan `no_impact` tidak mengubah apa pun — dan justru
        karena itu penjelasannya wajib ada.
        """
        if adjustment.adjustment_kind == AdjustmentKind.LOYALTY:
            return {
                "impact": CreditImpact.NONE,
                "days": "0.00",
                "reason": (
                    "Cuti yang dimundurkan tanpa persetujuan tidak "
                    "menghasilkan tambahan apa pun — dokumen menyebutnya "
                    "loyalitas. Jadwalnya tetap."
                ),
            }

        if adjustment.adjustment_kind == AdjustmentKind.NO_IMPACT:
            return {
                "impact": CreditImpact.NONE,
                "days": "0.00",
                "reason": (
                    "Penyebabnya di luar kendali pegawai (aturan #17), "
                    "jadi tidak ada penambahan on-site maupun "
                    "pengurangan saldo. Jadwalnya tetap."
                ),
            }

        if adjustment.credit_impact == CreditImpact.NONE:
            return {
                "impact": CreditImpact.NONE,
                "days": "0.00",
                "reason": "Tidak ada dampak ke saldo rotation credit.",
            }

        ratio = cls.ratio_for(plan=adjustment.plan)

        if adjustment.credit_impact == CreditImpact.EARN:
            reason = (
                f"{adjustment.days} hari kerja lebih ÷ rasio "
                f"{ratio.value} = {adjustment.credit_days} hari kredit."
            )
        else:
            reason = (
                f"{adjustment.credit_days} hari saldo dipakai untuk "
                f"memajukan field break. Setara "
                f"{adjustment.credit_days * ratio.value} hari kerja "
                f"menurut rasio {ratio.value}."
            )

        return {
            "impact": adjustment.credit_impact,
            "days": str(adjustment.credit_days),
            "ratio": str(ratio.value),
            "reason": reason,
        }

    # ------------------------------------------------------------------
    # Pemetaan jenis → operasi jadwal
    # ------------------------------------------------------------------

    @classmethod
    def operation_kwargs(cls, adjustment: RosterAdjustment) -> dict:
        """
        Argumen `RosterRecalculationService` untuk satu dokumen.

        Dipakai preview **dan** penerapan, jadi keduanya tidak bisa
        berbeda. Kalau berbeda, layar menunjukkan satu jadwal dan
        menyimpan yang lain.
        """
        kind = adjustment.adjustment_kind

        common = {
            "plan": adjustment.plan,
            "effective_date": adjustment.effective_date,
        }

        block = RosterRecalculationService.block_at(
            plan=adjustment.plan,
            on=adjustment.effective_date,
        )

        if kind == AdjustmentKind.SCHEDULE_SHIFT:
            if adjustment.new_cycle_start:
                return {
                    **common,
                    "tail_anchor": adjustment.new_cycle_start,
                    "tail_start_with": RosterSegmentType.WORK,
                }

            from datetime import timedelta

            anchor = adjustment.effective_date + timedelta(
                days=int(adjustment.days or 0),
            )

            return {
                **common,
                "tail_anchor": anchor,
                "tail_start_with": (
                    block.segment_type if block is not None else None
                ),
                "tail_cycle_number": (
                    block.cycle_number if block is not None else None
                ),
            }

        if block is None:
            return common

        from datetime import timedelta

        direction = (
            -1
            if kind in {
                AdjustmentKind.EARLY_RETURN,
                AdjustmentKind.CREDIT_USE,
            }
            else 1
        )

        end = block.end_date + timedelta(
            days=direction * int(adjustment.days or 0),
        )

        if end < block.start_date:
            raise ValidationError(
                {
                    "days": (
                        f"Blok {block.start_date}–{block.end_date} cuma "
                        f"{block.day_count} hari, tidak bisa dipendekkan "
                        f"{adjustment.days} hari."
                    ),
                },
            )

        from apps.hr.api.roster.calculation import SegmentRow

        return {
            "plan": adjustment.plan,
            # Bloknya ditulis ulang seluruhnya, jadi yang ditutup mulai
            # dari awalnya — bukan dari tanggal kejadiannya.
            "effective_date": block.start_date,
            "head_segments": [
                SegmentRow(
                    sequence=0,
                    segment_type=block.segment_type,
                    start_date=block.start_date,
                    end_date=end,
                    total_days=(end - block.start_date).days + 1,
                    counts_as_roster_day=block.counts_as_roster_day,
                    cycle_number=block.cycle_number,
                ),
            ],
        }

    # ------------------------------------------------------------------
    # Pengajuan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit(cls, *, adjustment: RosterAdjustment, user=None):
        from apps.workflow.services.workflow_service import WorkflowService

        if not adjustment.is_editable:
            raise ValidationError(
                {
                    "status": (
                        f"Dokumen berstatus "
                        f"{adjustment.get_status_display()} tidak bisa "
                        "diajukan lagi."
                    ),
                },
            )

        preview = cls.preview(adjustment=adjustment)

        if not preview["can_submit"]:
            raise ValidationError(
                {
                    "roster": [
                        item["message"]
                        for item in preview["validations"]
                        if item["level"] == "blocking"
                    ],
                },
            )

        instance = WorkflowService.submit(
            document=adjustment,
            module=MODULE,
            document_type=DOCUMENT_TYPE,
            employee=adjustment.employee,
            user=user,
            document_number=adjustment.document_number,
            document_label=cls.document_label(adjustment),
            context={
                "adjustment_kind": adjustment.adjustment_kind,
                "days": int(adjustment.days or 0),
                "credit_impact": adjustment.credit_impact,
                "credit_days": str(adjustment.credit_days),
                "effective_date": str(adjustment.effective_date),
            },
            on_complete=lambda inst, status: cls.on_workflow_done(
                adjustment=adjustment,
                status=status,
                user=user,
            ),
        )

        adjustment.status = AdjustmentStatus.SUBMITTED
        adjustment.submitted_at = timezone.now()
        adjustment.submitted_by = user

        adjustment.save(
            update_fields=[
                "status",
                "submitted_at",
                "submitted_by",
                "updated_at",
            ],
        )

        return instance

    @staticmethod
    def document_label(adjustment: RosterAdjustment) -> str:
        parts = [
            adjustment.get_adjustment_kind_display(),
            str(adjustment.employee),
            f"berlaku {adjustment.effective_date}",
        ]

        if adjustment.days:
            parts.append(f"{adjustment.days} hari")

        return " — ".join(parts)

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, adjustment: RosterAdjustment, user=None):
        from apps.workflow.services.workflow_service import WorkflowService

        if adjustment.status != AdjustmentStatus.SUBMITTED:
            raise ValidationError(
                {
                    "status": (
                        "Hanya dokumen yang sedang menunggu persetujuan "
                        "yang bisa ditarik."
                    ),
                },
            )

        instance = WorkflowService.instance_for(
            document=adjustment,
            module=MODULE,
            document_type=DOCUMENT_TYPE,
        )

        if instance is not None:
            WorkflowService.cancel(
                instance=instance,
                user=user,
                comment="Ditarik oleh pengaju.",
            )

        adjustment.status = AdjustmentStatus.DRAFT

        adjustment.save(update_fields=["status", "updated_at"])

        return adjustment

    # ------------------------------------------------------------------
    # Penyelesaian alur → penerapan
    # ------------------------------------------------------------------

    @classmethod
    def on_workflow_done(cls, *, adjustment, status, user=None):
        from apps.workflow.models import InstanceStatus

        if status != InstanceStatus.APPROVED:
            mapping = {
                InstanceStatus.REJECTED: AdjustmentStatus.REJECTED,
                InstanceStatus.CANCELLED: AdjustmentStatus.CANCELLED,
                InstanceStatus.RETURNED: AdjustmentStatus.DRAFT,
            }

            adjustment.status = mapping.get(status, adjustment.status)

            adjustment.save(update_fields=["status", "updated_at"])

            return adjustment

        adjustment.status = AdjustmentStatus.APPROVED

        adjustment.save(update_fields=["status", "updated_at"])

        try:
            return cls.apply(adjustment=adjustment, user=user)
        except Exception as error:  # noqa: BLE001
            # Kegagalan penerapan **tidak** membatalkan persetujuan.
            # Alurnya sudah selesai dan keputusan approver-nya sah;
            # melempar di titik ini menampilkan error pada orang yang
            # tidak bisa memperbaikinya.
            logger.exception(
                "Gagal menerapkan penyesuaian roster %s.", adjustment.pk,
            )

            RosterAdjustment.objects.filter(pk=adjustment.pk).update(
                apply_error=str(error)[:2000],
                updated_at=timezone.now(),
            )

            return adjustment

    @classmethod
    @transaction.atomic
    def apply(cls, *, adjustment: RosterAdjustment, user=None):
        """
        Menerapkan penyesuaian ke jadwal dan ke saldo.

        Idempotensinya dijaga `applied_at` yang **dibaca ulang di bawah
        kunci baris**, bukan `status`: dua permintaan bersamaan
        sama-sama membaca "approved" sebelum salah satunya sempat
        mengubahnya, dan jadwalnya digeser dua kali.
        """
        locked = (
            RosterAdjustment.objects
            .select_for_update()
            .select_related("plan", "employee")
            .get(pk=adjustment.pk)
        )

        if locked.applied_at is not None:
            return locked

        if locked.status not in {
            AdjustmentStatus.APPROVED,
            AdjustmentStatus.SUBMITTED,
        }:
            raise ValidationError(
                {
                    "status": (
                        "Hanya penyesuaian yang sudah disetujui yang "
                        "bisa diterapkan."
                    ),
                },
            )

        version = None

        if locked.changes_schedule:
            version, _ = RosterRecalculationService.recalculate(
                **cls.operation_kwargs(locked),
                source=RosterVersionSource.ADJUSTMENT,
                reason=(
                    f"{locked.get_adjustment_kind_display()}: "
                    f"{locked.reason}"
                ),
                reference_type=DOCUMENT_TYPE,
                reference_id=locked.pk,
                user=user,
            )

        cls.apply_credit(adjustment=locked, user=user)

        locked.applied_at = timezone.now()
        locked.status = AdjustmentStatus.APPLIED
        locked.apply_error = ""
        locked.resulting_version = version

        locked.save(
            update_fields=[
                "applied_at",
                "status",
                "apply_error",
                "resulting_version",
                "updated_at",
            ],
        )

        logger.info(
            "Penyesuaian roster %s diterapkan (%s, versi %s).",
            locked.pk,
            locked.adjustment_kind,
            getattr(version, "version_no", None),
        )

        return locked

    @classmethod
    def apply_credit(cls, *, adjustment: RosterAdjustment, user=None):
        if (
            adjustment.credit_impact == CreditImpact.NONE
            or not adjustment.credit_days
        ):
            return None

        common = {
            "employee": adjustment.employee,
            "effective_date": adjustment.effective_date,
            "reason": (
                f"{adjustment.get_adjustment_kind_display()} "
                f"{adjustment.document_number}: {adjustment.reason}"
            ),
            "source_type": DOCUMENT_TYPE,
            "source_id": adjustment.pk,
            "plan": adjustment.plan,
            "user": user,
        }

        if adjustment.credit_impact == CreditImpact.EARN:
            # Angkanya sudah dibekukan ke dokumen saat diajukan, jadi
            # dicatat apa adanya — rasio yang diubah di master minggu
            # depan tidak boleh mengubah arti yang sudah disetujui.
            return RotationCreditService.record(
                entry_type=CreditEntryType.EARNED,
                days=adjustment.credit_days,
                conversion_ratio=cls.ratio_for(plan=adjustment.plan).value,
                **common,
            )

        return RotationCreditService.use(
            days=adjustment.credit_days,
            **common,
        )

    # ------------------------------------------------------------------
    # Perpanjangan horizon — tanpa approval, dan itu disengaja
    # ------------------------------------------------------------------

    @staticmethod
    def extend_horizon(*, plan, months=None, until=None, user=None):
        """
        Menyambung jadwal di ujung.

        Tidak lewat dokumen penyesuaian karena tidak ada keputusan yang
        dibatalkannya: ia menempel halaman baru di bawah kalender, bukan
        mencetak ulang kalendernya.
        """
        from apps.hr.api.roster.services import RosterGenerationService

        return RosterGenerationService.extend_horizon(
            plan=plan,
            months=months,
            until=until,
            user=user,
        )


__all__ = [
    "DOCUMENT_TYPE",
    "MODULE",
    "RosterAdjustmentService",
]
