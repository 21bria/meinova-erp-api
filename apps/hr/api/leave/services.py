from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.core.services.master import BaseMasterService

from apps.hr.api.leave.allocation import (
    POCKET_CARRIED_OVER,
    POCKET_OPENING,
    allocate,
    claims_from_leaves,
    pockets_from_balance,
)
from apps.hr.api.leave.calculator import LeaveDayCalculator
from apps.hr.api.leave.rules import LeaveRuleEvaluator, LeaveRuleReport
from apps.hr.api.mixins import OrganizationDenormalizationMixin
from apps.hr.models import (
    LEAVE_BLOCKING_STATUSES,
    LEAVE_DEDUCTING_STATUSES,
    EmployeeLeave,
    LeaveBalance,
    LeaveStatus,
)
from apps.uploads.services import AttachmentLifecycleService
from apps.workflow.models import InstanceStatus
from apps.workflow.services import WorkflowService


class LeaveBalanceService(BaseMasterService):
    model = LeaveBalance

    @classmethod
    def recalculate_used(
        cls,
        *,
        employee,
        leave_type,
        year: int,
    ) -> LeaveBalance | None:
        """
        Menjumlahkan ulang pemakaian cuti dari record EmployeeLeave,
        bukan menambah/mengurangi secara inkremental. Penjumlahan ulang
        tidak bisa hanyut kalau ada record yang diubah tanggalnya,
        dipindah tipenya, atau di-soft-delete.

        Record cuti yang melintasi pergantian tahun dihitung penuh pada
        tahun `start_date` — memecahnya per tahun butuh aturan kalender
        cuti yang belum ada.

        Sekalian membagi pemakaian itu ke kantongnya masing-masing
        (`allocation.allocate`). Dua-duanya di sini, bukan dipisah jadi
        perintah tersendiri: keduanya turunan dari daftar catatan cuti
        yang sama, dan menghitungnya di dua tempat berarti dua kali
        query untuk satu jawaban — plus kesempatan keduanya berbeda.
        """
        balance = (
            LeaveBalance.objects
            .filter(
                employee=employee,
                leave_type=leave_type,
                year=year,
                is_deleted=False,
            )
            .first()
        )

        if balance is None:
            return None

        # RECORDED **dan** APPROVED. Yang masih SUBMITTED sengaja tidak
        # dihitung: cuti yang belum disetujui tidak boleh sudah
        # mengurangi jatah orang, dan kalau ditolak tidak ada yang perlu
        # dikembalikan.
        leaves = list(
            EmployeeLeave.objects
            .filter(
                employee=employee,
                leave_type=leave_type,
                start_date__year=year,
                status__in=LEAVE_DEDUCTING_STATUSES,
                is_deleted=False,
            )
            .only("id", "start_date", "total_days")
        )

        used = sum(
            (leave.total_days or Decimal("0.0"))
            for leave in leaves
        ) or Decimal("0.0")

        result = allocate(
            pockets=pockets_from_balance(balance),
            claims=claims_from_leaves(leaves),
        )

        changed = {
            "used": used,
            "opening_used": result.taken(POCKET_OPENING),
            "carried_over_used": result.taken(POCKET_CARRIED_OVER),
            "advance_used": result.advance,
        }

        if all(
            getattr(balance, field_name) == value
            for field_name, value in changed.items()
        ):
            return balance

        for field_name, value in changed.items():
            setattr(balance, field_name, value)

        balance.save(
            update_fields=[*changed.keys(), "updated_at"],
        )

        return balance


class EmployeeLeaveService(
    OrganizationDenormalizationMixin,
    AttachmentLifecycleService,
    BaseMasterService,
):
    model = EmployeeLeave

    attachment_fields = ("uploaded_file",)

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls.apply_organization(data)
        data = cls.apply_document_number(data)

        cls.assert_no_overlap(data)

        data = cls.apply_total_days(data)

        cls.assert_policy_rules(data)

        return data

    # ------------------------------------------------------------------
    # Tumpang tindih
    # ------------------------------------------------------------------

    @classmethod
    def find_overlap(
        cls,
        *,
        employee,
        start,
        end,
        exclude_pk=None,
    ):
        """
        Cuti lain milik pegawai yang sama yang rentangnya bersinggungan.

        Dicari lintas **jenis cuti**, bukan per jenis: orang tidak bisa
        sedang cuti tahunan sekaligus sakit di hari yang sama, dan yang
        mau dicegah justru saldonya terpotong dua kali.

        Status yang dihitung hanya yang benar-benar memesan tanggal —
        RECORDED, APPROVED, dan SUBMITTED. Draft belum jadi apa-apa,
        yang ditolak atau dibatalkan sudah selesai; keduanya tidak boleh
        menghalangi pengajuan ulang di tanggal yang sama.
        """
        if employee is None or start is None or end is None:
            return None

        queryset = (
            EmployeeLeave.objects
            .filter(
                employee=employee,
                is_deleted=False,
                status__in=LEAVE_BLOCKING_STATUSES,
                # Dua rentang bersinggungan kalau yang satu mulai
                # sebelum yang lain selesai, dan sebaliknya.
                start_date__lte=end,
                end_date__gte=start,
            )
            .select_related("leave_type")
            .order_by("start_date")
        )

        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)

        return queryset.first()

    @classmethod
    def assert_no_overlap(
        cls,
        data: dict[str, Any],
        *,
        instance: EmployeeLeave | None = None,
    ) -> None:
        """
        Menolak cuti yang tanggalnya bersinggungan dengan cuti lain.

        Ini penjagaan terhadap dua pintu yang menuju hal yang sama:
        pegawai site bisa mendapat cuti lewat baris Travel Request
        **dan** lewat modul Cuti langsung. Tanpa penjagaan ini, tujuh
        hari yang sama terpotong dua kali dari saldonya dan tidak ada
        yang berbunyi sampai orangnya membandingkan kartu cuti dengan
        dokumen TR.

        Pesannya menyebut nomor dokumen yang bentrok — "sudah ada cuti
        lain" tanpa menyebut yang mana tidak bisa ditindaklanjuti.
        """

        def resolved(field_name, default=None):
            if field_name in data:
                return data[field_name]

            return getattr(instance, field_name, default)

        clashing = cls.find_overlap(
            employee=resolved("employee"),
            start=resolved("start_date"),
            end=resolved("end_date"),
            exclude_pk=getattr(instance, "pk", None),
        )

        if clashing is None:
            return

        label = clashing.document_number or f"#{clashing.pk}"

        raise ValidationError(
            {
                "start_date": (
                    f"Pegawai ini sudah punya {clashing.leave_type.name} "
                    f"({label}) pada {clashing.start_date:%d/%m/%Y}–"
                    f"{clashing.end_date:%d/%m/%Y}. Tanggalnya "
                    "bersinggungan, dan saldonya akan terpotong dua "
                    "kali. Ubah tanggalnya, atau batalkan dokumen yang "
                    "lama dulu."
                ),
            },
        )

    # ------------------------------------------------------------------
    # Aturan jenis cuti (`LeavePolicy`)
    # ------------------------------------------------------------------
    #
    # Cuti tanpa saldo tidak punya angka yang berkurang, jadi tidak ada
    # apa pun yang menahan seseorang mengajukannya berulang kali.
    # Batasnya ada di `LeavePolicy` — `max_days`, `document_required`,
    # dan riwayat pemakaian — dan blok ini yang menegakkannya.
    #
    # Berlaku untuk cuti bersaldo juga: batas per pengajuan dan
    # kewajiban dokumen tidak ada hubungannya dengan ada-tidaknya kartu
    # saldo. Yang membedakan cuma bahwa untuk cuti bersaldo kolom-kolom
    # itu lazimnya memang dikosongkan.

    @classmethod
    def evaluate_rules(
        cls,
        data: dict[str, Any] | None = None,
        *,
        instance: EmployeeLeave | None = None,
        evaluator: LeaveRuleEvaluator | None = None,
        with_history: bool = True,
        with_balance: bool = True,
    ) -> LeaveRuleReport:
        """
        Penilaian satu dokumen terhadap aturan yang berlaku untuknya.

        Menerima `data` (jalur tulis, nilainya belum tersimpan) maupun
        `instance` saja (jalur baca, dipakai serializer). Nilai dari
        `data` menang — yang sedang dinilai adalah dokumen **setelah**
        perubahan, bukan sebelumnya.
        """
        data = data or {}

        def resolved(name, default=None):
            if name in data:
                return data[name]

            return getattr(instance, name, default)

        engine = evaluator or LeaveRuleEvaluator()

        return engine.evaluate(
            employee=resolved("employee"),
            leave_type=resolved("leave_type"),
            start_date=resolved("start_date"),
            total_days=resolved("total_days"),
            # Kiriman menang **termasuk saat isinya kosong**: PATCH
            # yang mencabut lampiran berarti dokumennya memang sedang
            # dihapus. Kalau di-`or` dengan nilai instance, pencabutan
            # itu tidak pernah terbaca dan pengajuan tanpa dokumen
            # lolos gerbang yang seharusnya menahannya.
            has_document=bool(
                data["uploaded_file"]
                if "uploaded_file" in data
                else getattr(instance, "uploaded_file_id", None)
            ),
            exclude_pk=getattr(instance, "pk", None),
            with_history=with_history,
            with_balance=with_balance,
            own_deduction=cls.own_deduction(
                instance=instance,
                employee=resolved("employee"),
                leave_type=resolved("leave_type"),
                start_date=resolved("start_date"),
            ),
        )

    @staticmethod
    def own_deduction(
        *,
        instance: EmployeeLeave | None,
        employee,
        leave_type,
        start_date,
    ) -> Decimal:
        """
        Bagian saldo yang **sudah** dipotong dokumen ini sendiri.

        Dokumen RECORDED atau APPROVED yang sedang disunting sudah ikut
        terhitung di `LeaveBalance.used`. Tanpa dikembalikan lebih dulu,
        ia diadu dengan sisa yang sudah dikurangi dirinya sendiri — dan
        cuti 3 hari yang diperpanjang jadi 4 ditolak walau saldonya
        jelas cukup, dengan angka yang tidak cocok dengan angka mana pun
        di kartunya.

        Nol begitu salah satu dari tiga kuncinya berpindah: kartu yang
        diperiksa adalah kartu (pegawai, jenis cuti, tahun) **tujuan**,
        dan potongan lama tidak pernah ada di sana.
        """
        if instance is None or instance.pk is None:
            return Decimal("0.0")

        if instance.status not in LEAVE_DEDUCTING_STATUSES:
            return Decimal("0.0")

        if instance.start_date is None or start_date is None:
            return Decimal("0.0")

        same_card = (
            instance.start_date.year == start_date.year
            and instance.employee_id == getattr(employee, "pk", None)
            and instance.leave_type_id == getattr(leave_type, "pk", None)
        )

        if not same_card:
            return Decimal("0.0")

        return instance.total_days or Decimal("0.0")

    @classmethod
    def assert_policy_rules(
        cls,
        data: dict[str, Any],
        *,
        instance: EmployeeLeave | None = None,
        require_document: bool = False,
    ) -> LeaveRuleReport:
        """
        Menolak pengajuan yang melanggar aturan jenis cutinya.

        Dua hal yang **tidak** ditolak di sini, dan keduanya disengaja:

        **Jalur pencatatan (RECORDED).** HR mencatat cuti yang sudah
        terjadi, dan Travel Request menerbitkannya sesudah alurnya
        disetujui. Menolak di titik itu berarti fakta yang sudah
        terjadi tidak punya tempat tersimpan, dan pesannya muncul di
        layar orang yang tidak bisa memperbaikinya. Temuannya tetap
        dihitung dan tetap tampil sebagai peringatan di dokumennya.

        **Dokumen pendukung, sampai Submit.** Surat dokter lazim baru
        ada setelah orangnya pulang berobat; mewajibkannya sejak draft
        membuat isian yang sudah diketik tidak bisa disimpan sama
        sekali. `submit()` yang mewajibkannya, lewat
        `require_document=True`.
        """
        report = cls.evaluate_rules(data, instance=instance)

        status = data.get("status") or getattr(
            instance,
            "status",
            LeaveStatus.RECORDED,
        )

        if status == LeaveStatus.RECORDED:
            return report

        errors: dict[str, list[str]] = {}

        for finding in report.blocking:
            if (
                finding.code == "document_required"
                and not require_document
            ):
                continue

            errors.setdefault(finding.field, []).append(finding.message)

        if errors:
            raise ValidationError(errors)

        return report

    @staticmethod
    def apply_document_number(data: dict[str, Any]) -> dict[str, Any]:
        """
        Nomor dari deret `hr/leave`, hanya saat record dibuat.

        Tidak pernah dihitung ulang saat update — nomor yang sudah
        dirujuk di surat atau percakapan harus tetap menunjuk dokumen
        yang sama. Deret yang belum diseed menghasilkan nomor kosong dan
        recordnya tetap tersimpan; cuti tidak boleh gagal dicatat gara-
        gara master penomoran belum diisi.
        """
        if data.get("document_number"):
            return data

        data["document_number"] = DocumentNumberService.next(
            module="hr",
            document_type="leave",
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
        cls.assert_editable(instance, data=data)

        data = cls.apply_organization(
            data,
            fallback_employee=instance.employee,
        )

        cls.assert_no_overlap(data, instance=instance)

        data = cls.apply_total_days(
            data,
            instance=instance,
        )

        cls.assert_policy_rules(data, instance=instance)

        return data

    @staticmethod
    def assert_editable(instance: EmployeeLeave, *, data=None) -> None:
        """
        Cuti yang sedang menunggu atau sudah disetujui tidak boleh
        disunting isinya.

        Perpindahan status yang dilakukan engine sendiri dikecualikan —
        tanpa itu, `on_complete` yang menulis APPROVED akan ditolak oleh
        penjagaan ini dan alurnya berhenti tepat di langkah terakhir.
        """
        if instance.is_editable:
            return

        if data is not None and set(data).issubset(
            {"status", "updated_by", "updated_at"}
        ):
            return

        raise ValidationError(
            {
                "status": (
                    f"Cuti berstatus {instance.get_status_display()} "
                    "tidak bisa disunting. Tarik kembali pengajuannya "
                    "dulu."
                ),
            },
        )

    @staticmethod
    def apply_total_days(
        data: dict[str, Any],
        *,
        instance: EmployeeLeave | None = None,
    ) -> dict[str, Any]:
        """
        Dihitung dari hari kerja pegawai (lihat `LeaveDayCalculator`),
        bukan hari kalender: akhir pekan dan hari libur tidak memotong
        saldo. Isian manual tetap dihormati — ada kasus yang tidak bisa
        disimpulkan dari kalender, mis. cuti setengah hari beruntun.
        """
        if data.get("total_days") is not None:
            return data

        def resolved(field_name, default=None):
            if field_name in data:
                return data[field_name]

            return getattr(instance, field_name, default)

        total = LeaveDayCalculator.calculate(
            employee=resolved("employee"),
            start=resolved("start_date"),
            end=resolved("end_date"),
            is_half_day=resolved("is_half_day", False),
        )

        if total is not None:
            data["total_days"] = total

        return data

    # ------------------------------------------------------------------
    # Sinkronisasi saldo
    # ------------------------------------------------------------------

    @classmethod
    def sync_balance(cls, instance: EmployeeLeave) -> None:
        if instance.start_date is None:
            return

        LeaveBalanceService.recalculate_used(
            employee=instance.employee,
            leave_type=instance.leave_type,
            year=instance.start_date.year,
        )

    @classmethod
    def after_create(cls, *, instance, user=None, **kwargs):
        instance = super().after_create(
            instance=instance,
            user=user,
            **kwargs,
        )

        cls.sync_balance(instance)

        return instance

    @classmethod
    @transaction.atomic
    def update(cls, *, instance, data: dict[str, Any], user=None, **kwargs):
        # Kombinasi (pegawai, tipe, tahun) sebelum perubahan ikut
        # disinkronkan — kalau tidak, memindahkan cuti ke tipe atau
        # tahun lain akan meninggalkan saldo lama yang kelebihan.
        previous_employee = instance.employee
        previous_leave_type = instance.leave_type
        previous_year = (
            instance.start_date.year
            if instance.start_date
            else None
        )

        instance = super().update(
            instance=instance,
            data=data,
            user=user,
            **kwargs,
        )

        if previous_year is not None:
            LeaveBalanceService.recalculate_used(
                employee=previous_employee,
                leave_type=previous_leave_type,
                year=previous_year,
            )

        cls.sync_balance(instance)

        return instance

    @classmethod
    @transaction.atomic
    def soft_delete(cls, *, instance, user=None, **kwargs):
        # Sengaja tidak lewat hook `after_soft_delete`:
        # `AttachmentLifecycleService.soft_delete` (yang menang di MRO
        # karena ia yang ikut menghapus lampiran) tidak memanggil hook
        # milik BaseMasterService, jadi sinkronisasi saldo harus
        # dipanggil eksplisit di sini.
        instance = AttachmentLifecycleService.soft_delete(
            instance=instance,
            user=user,
        )

        cls.sync_balance(instance)

        return instance

    @classmethod
    @transaction.atomic
    def restore(cls, *, instance, user=None, **kwargs):
        instance = AttachmentLifecycleService.restore(
            instance=instance,
            user=user,
        )

        cls.sync_balance(instance)

        return instance

    # ------------------------------------------------------------------
    # Alur persetujuan
    # ------------------------------------------------------------------
    #
    # Cuti pegawai HO diajukan sendiri oleh pegawainya, lalu berjalan
    # lewat engine generik di `apps.workflow`. Jalur pencatatan lama
    # (status RECORDED, dipakai HR dan Travel Request) tidak lewat sini
    # sama sekali dan tidak berubah.

    WORKFLOW_MODULE = "hr"
    WORKFLOW_DOCUMENT_TYPE = "leave_request"

    @classmethod
    @transaction.atomic
    def submit(cls, *, instance: EmployeeLeave, user=None, notes: str = ""):
        """
        Mengajukan cuti ke alur persetujuan.

        `total_days` dihitung ulang lebih dulu, bukan dipercaya apa
        adanya: syarat step bisa bergantung pada jumlah hari (mis. cuti
        5 hari ke atas naik ke HR Manager), dan angka yang basi akan
        membangun rantai persetujuan yang salah — diam-diam.
        """
        if instance.status == LeaveStatus.SUBMITTED:
            raise ValidationError(
                {
                    "status": (
                        "Cuti ini sudah diajukan dan masih menunggu "
                        "persetujuan."
                    ),
                },
            )

        if instance.status == LeaveStatus.APPROVED:
            raise ValidationError(
                {"status": "Cuti ini sudah disetujui."},
            )

        if instance.start_date is None or instance.end_date is None:
            raise ValidationError(
                {
                    "start_date": (
                        "Lengkapi dulu tanggal mulai dan selesainya."
                    ),
                },
            )

        cls.refresh_total_days(instance)

        # Enforcement penuh, dan **hanya di sini** yang mewajibkan
        # dokumen pendukung. Ini titik terakhir sebelum dokumennya
        # mendarat di meja orang lain; sesudah ini yang menanggung
        # kekurangannya adalah approver yang tidak punya bahan untuk
        # memutuskan.
        cls.assert_policy_rules(
            {},
            instance=instance,
            require_document=True,
        )

        workflow = WorkflowService.submit(
            document=instance,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
            employee=instance.employee,
            user=user,
            context=cls.workflow_context(instance),
            document_number=instance.document_number or "",
            document_label=cls.workflow_label(instance),
            notes=notes,
            on_complete=lambda wf, status: cls.apply_workflow_status(
                instance=instance,
                status=status,
                user=user,
            ),
        )

        # Alur yang seluruh step-nya terlewat sudah menutup dirinya
        # sendiri dan `on_complete` menulis APPROVED. Selain itu,
        # dokumennya sedang menunggu.
        if workflow.status == InstanceStatus.PENDING:
            cls.set_status(
                instance=instance,
                status=LeaveStatus.SUBMITTED,
                user=user,
            )

        return workflow

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, instance: EmployeeLeave, user=None, notes: str = ""):
        """Menarik kembali pengajuan supaya isinya bisa diperbaiki."""
        workflow = WorkflowService.instance_for(
            document=instance,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
        )

        if workflow is None:
            raise ValidationError(
                {
                    "status": (
                        "Tidak ada pengajuan berjalan yang bisa "
                        "ditarik."
                    ),
                },
            )

        WorkflowService.cancel(
            instance=workflow,
            user=user,
            comment=notes,
        )

        cls.set_status(
            instance=instance,
            status=LeaveStatus.DRAFT,
            user=user,
        )

        return workflow

    @classmethod
    def apply_workflow_status(cls, *, instance, status, user=None):
        """
        Memindahkan status cuti mengikuti hasil alurnya.

        Inilah satu-satunya tempat engine menyentuh kolom status modul
        ini — lewat callback, bukan karena engine mengenal
        `LeaveStatus`. `RETURNED` sengaja jatuh ke DRAFT: dokumen yang
        dikembalikan memang harus bisa disunting lagi.
        """
        mapping = {
            InstanceStatus.APPROVED: LeaveStatus.APPROVED,
            InstanceStatus.REJECTED: LeaveStatus.REJECTED,
            InstanceStatus.RETURNED: LeaveStatus.DRAFT,
            InstanceStatus.CANCELLED: LeaveStatus.DRAFT,
        }

        target = mapping.get(status)

        if target is None:
            return instance

        return cls.set_status(
            instance=instance,
            status=target,
            user=user,
        )

    @classmethod
    def set_status(cls, *, instance, status, user=None):
        """
        Menulis status lalu menjumlahkan ulang saldo.

        Sinkronisasi saldo wajib ikut: APPROVED memotong dan REJECTED
        tidak, jadi perpindahan status yang tidak diikuti perhitungan
        ulang meninggalkan kartu cuti yang salah tanpa ada yang tahu.
        """
        if instance.status == status:
            return instance

        instance.status = status
        instance.updated_by = user

        instance.save(
            update_fields=["status", "updated_by", "updated_at"],
        )

        cls.sync_balance(instance)

        return instance

    @classmethod
    def refresh_total_days(cls, instance: EmployeeLeave) -> EmployeeLeave:
        total = LeaveDayCalculator.calculate(
            employee=instance.employee,
            start=instance.start_date,
            end=instance.end_date,
            is_half_day=instance.is_half_day,
        )

        if total is None or instance.total_days == total:
            return instance

        instance.total_days = total

        instance.save(update_fields=["total_days", "updated_at"])

        return instance

    @classmethod
    def workflow_context(cls, instance: EmployeeLeave) -> dict:
        """
        Cuplikan nilai yang dinilai `WorkflowStep.condition`.

        Sengaja nilai sederhana (angka dan kode), bukan objek: konteks
        disimpan sebagai JSON dan dibekukan, jadi apa pun yang masuk ke
        sini harus tetap terbaca setahun lagi tanpa relasi yang masih
        hidup.
        """
        organization = getattr(instance.employee, "organization", None)
        employment = getattr(instance.employee, "employment", None)

        return {
            "total_days": (
                str(instance.total_days)
                if instance.total_days is not None
                else None
            ),
            "is_half_day": instance.is_half_day,
            "leave_type_code": getattr(instance.leave_type, "code", None),
            "leave_type_name": getattr(instance.leave_type, "name", None),
            "start_date": (
                instance.start_date.isoformat()
                if instance.start_date
                else None
            ),
            "end_date": (
                instance.end_date.isoformat()
                if instance.end_date
                else None
            ),
            "has_attachment": instance.uploaded_file_id is not None,
            "employee_number": instance.employee.employee_number,
            "location_code": getattr(
                getattr(organization, "location", None),
                "code",
                None,
            ),
            "department_code": getattr(
                getattr(organization, "department", None),
                "code",
                None,
            ),
            # Pembeda pegawai roster vs pegawai kantor, sama seperti
            # yang dipakai `LeaveDayCalculator`. Alur boleh memakainya
            # sebagai syarat tanpa harus menebak dari lokasi.
            "has_roster_crew": bool(
                getattr(employment, "roster_crew_id", None),
            ),
            # Aturan yang berlaku, dibekukan bersama konteks lainnya.
            # Ini yang membuat sebuah step bisa dibuat bersyarat "hanya
            # kalau butuh diperiksa" tanpa menebak dari jenis cutinya —
            # dan yang membuat peringatan riwayat ikut terbaca di kotak
            # masuk approver, bukan cuma di layar pengajunya.
            **cls.workflow_rule_context(instance),
        }

    @classmethod
    def workflow_rule_context(cls, instance: EmployeeLeave) -> dict:
        """
        Ringkasan temuan aturan, dalam bentuk yang tetap terbaca setahun
        lagi.

        Nilai sederhana saja — angka, boolean, dan kalimat yang sudah
        jadi. Konteks disimpan sebagai JSON dan **dibekukan**, jadi
        objek apa pun di dalamnya akan jadi sampah begitu relasinya
        berubah. Kalimatnya ikut dibekukan dengan sengaja: yang dibaca
        approver harus tetap kalimat yang dilihat pengajunya saat
        menekan Submit, walau aturannya disunting sesudah itu.
        """
        report = cls.evaluate_rules(instance=instance)

        return {
            "policy_code": getattr(report.policy, "code", None),
            "uses_balance": report.uses_balance,
            "needs_review": report.needs_review,
            "history_total": report.history_total,
            "rule_messages": [
                row.message for row in report.findings
            ],
        }

    @staticmethod
    def workflow_label(instance: EmployeeLeave) -> str:
        leave_type = getattr(instance.leave_type, "name", "Cuti")

        return (
            f"{leave_type} — {instance.employee.full_name} "
            f"({instance.start_date:%d/%m/%Y} s/d "
            f"{instance.end_date:%d/%m/%Y})"
        )
