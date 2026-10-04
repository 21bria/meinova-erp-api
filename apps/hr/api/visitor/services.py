"""
Service Visitor Management.

Tiga tanggung jawab yang tidak boleh bocor ke serializer atau view:
penomoran dokumen, alur persetujuan, dan urutan kedatangan
(check-in → check-out → selesai). Aturan bisnis BR-01…BR-12 dari
spesifikasi ditegakkan di sini dan di `Model.clean()` — bukan di form,
karena form bisa dilewati siapa pun yang menembak API langsung.

Pembagiannya: yang menyangkut **satu record** (tanggal terbalik, tamu
internal yang menunjuk external visitor) di `clean()`; yang menyangkut
**keadaan dokumen atau baris lain** (belum disetujui tapi mau check-in,
check-out sebelum check-in) di sini. `clean()` tidak boleh menolak
berdasarkan status, kalau tidak setiap perpindahan status resmi ikut
terjegal validasinya sendiri.
"""

from __future__ import annotations

import logging

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.core.services.master import BaseMasterService
from apps.workflow.models import InstanceStatus
from apps.workflow.services import WorkflowService

from apps.hr.api.mixins import OrganizationDenormalizationMixin
from apps.hr.models import (
    ExternalVisitor,
    VisitorArrivalStatus,
    VisitorPass,
    VisitorPassStatus,
    VisitorRequest,
    VisitorRequestStatus,
    VisitorType,
    VISITOR_OPEN_STATUSES,
)


logger = logging.getLogger(__name__)


# BT-2A — Visitor Request hanya untuk orang luar. Pegawai sendiri yang
# datang ke HO/site sedang **dinas**, dan dokumennya Business Trip; satu
# perjalanan tidak boleh punya dua dokumen sumber. Pilihan `internal`
# tetap ada di `VisitorType` supaya dokumen lama tetap terbaca.
INTERNAL_VISITOR_REJECTED = (
    "Visitor Request hanya untuk tamu dari luar perusahaan. Pegawai "
    "yang berkunjung ke lokasi lain memakai Business Trip "
    "(HR → Business Trips)."
)

EMPLOYEE_VISITOR_REJECTED = (
    "Pegawai tidak bisa dicatat sebagai tamu. Perjalanan pegawai memakai "
    "Business Trip; pegawai hanya boleh tampil di Visitor Request "
    "sebagai host atau pemohon."
)

INTERNAL_VISIT_TYPE_CODE = "INTERNAL"


class ExternalVisitorService(BaseMasterService):
    """
    Master tamu luar.

    Satu-satunya hal yang tidak trivial di sini: nomor tamu, dan
    penolakan duplikat yang menyebut **siapa** pemakainya. Tanpa itu
    tabrakan nomor identitas muncul sebagai "Constraint
    uniq_active_hr_external_visitor_identity is violated" — kalimat
    yang tidak menempel di kolom mana pun dan tidak memberi tahu bahwa
    tamunya sudah terdaftar dan tinggal dipilih.
    """

    model = ExternalVisitor

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_identity_available(data.get("identity_number"))

        return cls.apply_visitor_number(data)

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        if "identity_number" in data:
            cls.assert_identity_available(
                data["identity_number"],
                exclude_pk=instance.pk,
            )

        return data

    @staticmethod
    def assert_identity_available(
        identity_number: str | None,
        *,
        exclude_pk=None,
    ) -> None:
        value = (identity_number or "").strip()

        if not value:
            return

        clash = (
            ExternalVisitor.objects
            .filter(identity_number__iexact=value, is_deleted=False)
            .exclude(pk=exclude_pk)
            .first()
        )

        if clash is None:
            return

        raise ValidationError(
            {
                "identity_number": (
                    f"Nomor identitas ini sudah terdaftar atas nama "
                    f"{clash.full_name} "
                    f"({clash.visitor_number or 'tanpa nomor'}). "
                    "Pakai data tamu yang sudah ada, jangan buat baru."
                ),
            },
        )

    @staticmethod
    def apply_visitor_number(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("visitor_number"):
            return data

        # Deret yang belum diseed mengembalikan string kosong, dan
        # tamunya tetap tersimpan. Satpam yang mencatat kedatangan
        # tengah malam tidak boleh terhalang master penomoran.
        data["visitor_number"] = DocumentNumberService.next(
            module="hr",
            document_type="external_visitor",
        )

        return data


class VisitorRequestService(
    OrganizationDenormalizationMixin,
    BaseMasterService,
):
    model = VisitorRequest

    WORKFLOW_MODULE = "hr"
    WORKFLOW_DOCUMENT_TYPE = "visitor_request"

    # ------------------------------------------------------------------
    # Penyiapan data
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_external_only(data)

        data = cls.apply_requester(data, user=user)
        data = cls.apply_organization_from_requester(data)
        data = cls.apply_visitor_defaults(data)
        data.setdefault("request_date", timezone.localdate())

        cls.assert_visitor_allowed(data)

        return cls.apply_document_number(data)

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
        cls.assert_external_only(data, instance=instance)

        data = cls.apply_organization_from_requester(
            data,
            fallback=instance.requester,
        )
        data = cls.apply_visitor_defaults(data, instance=instance)

        cls.assert_visitor_allowed(data, instance=instance)

        return data

    @staticmethod
    def assert_external_only(
        data: dict[str, Any],
        *,
        instance: VisitorRequest | None = None,
    ) -> None:
        """
        BT-2A — dokumen baru dan yang disunting harus tamu luar.

        Ditolak, bukan dikonversi: mengubah diam-diam kunjungan internal
        jadi eksternal (atau jadi Business Trip) menghasilkan dokumen
        yang tidak pernah diminta penggunanya.

        Draft internal lama ikut tertolak saat disunting — menyelesaikan
        draft itu berarti menjalankan alur yang sudah ditutup. Mengubah
        jenisnya ke External (dengan tamu luar) tetap boleh. Dokumen
        internal yang sudah berjalan tidak lewat sini: check-in,
        check-out, dan no-show tetap bisa menuntaskannya.
        """
        visitor_type = data.get(
            "visitor_type",
            getattr(instance, "visitor_type", None),
        )

        if visitor_type == VisitorType.INTERNAL:
            raise ValidationError({"visitor_type": INTERNAL_VISITOR_REJECTED})

        if data.get("employee") is not None:
            raise ValidationError({"employee": EMPLOYEE_VISITOR_REJECTED})

        visit_type = data.get("visit_type")

        if (
            visit_type is not None
            and getattr(visit_type, "code", "") == INTERNAL_VISIT_TYPE_CODE
        ):
            raise ValidationError({"visit_type": INTERNAL_VISITOR_REJECTED})

    @staticmethod
    def apply_requester(data: dict[str, Any], *, user=None) -> dict[str, Any]:
        """
        Mengisi pemohon dari akun yang mengetik, kalau tidak disebut.

        `employee_profile`, bukan `employee` — accessor-nya berasal dari
        `related_name` pada OneToOne, dan `getattr` untuk nama yang salah
        mengembalikan None tanpa error. Jebakan yang sudah kena sekali di
        `EmployeeDataPolicy`.
        """
        if data.get("requester") is not None:
            return data

        employee = getattr(user, "employee_profile", None)

        if employee is not None:
            data["requester"] = employee

        return data

    @classmethod
    def apply_organization_from_requester(
        cls,
        data: dict[str, Any],
        *,
        fallback=None,
    ) -> dict[str, Any]:
        """
        Cakupan dokumen diambil dari penempatan **pemohon**, bukan tamu.

        Alasannya cakupan data: yang berhak melihat kunjungan
        adalah unit yang mengundang. Tamu internal dari site lain tidak
        membuat dokumennya jadi milik site itu — kalau diambil dari
        tamunya, kunjungan pegawai Gebe ke Jakarta akan hilang dari
        layar admin Jakarta yang justru menerimanya.
        """
        requester = data.get("requester", fallback)

        if requester is None:
            return data

        # `apply_organization` membaca kunci "employee"; dokumen ini
        # memakai "requester" untuk peran yang sama, jadi dioper lewat
        # parameter fallback-nya alih-alih menyalin isi mixin-nya.
        return cls.apply_organization(data, fallback_employee=requester)

    @staticmethod
    def apply_visitor_defaults(
        data: dict[str, Any],
        *,
        instance: VisitorRequest | None = None,
    ) -> dict[str, Any]:
        """
        Mengosongkan kolom tamu yang tidak dipakai jenis kunjungannya.

        Kalau tidak, mengganti Internal → External meninggalkan
        `employee` yang lama menempel dan `clean()` menolaknya dengan
        pesan yang membingungkan: penggunanya baru saja memilih tamu
        eksternal dan diberi tahu bahwa kunjungan eksternal tidak boleh
        menunjuk Employee — kolom yang bahkan sudah tidak ada lagi di
        form-nya.
        """
        visitor_type = data.get(
            "visitor_type",
            getattr(instance, "visitor_type", None),
        )

        if visitor_type == VisitorType.INTERNAL:
            data["external_visitor"] = None
        elif visitor_type == VisitorType.EXTERNAL:
            data["employee"] = None

        return data

    @staticmethod
    def assert_visitor_allowed(
        data: dict[str, Any],
        *,
        instance: VisitorRequest | None = None,
    ) -> None:
        """
        BR-04 — tamu luar harus punya identitas minimum, dan yang masuk
        daftar hitam tidak bisa diundang.

        Diperiksa di service, bukan `clean()` milik request: yang dinilai
        keadaan **baris lain** (masternya), dan `clean()` sebuah dokumen
        yang membaca kelengkapan master akan menolak dokumen lama yang
        tadinya sah begitu ada yang mengosongkan satu kolom di master.
        """
        visitor = data.get(
            "external_visitor",
            getattr(instance, "external_visitor", None),
        )

        if visitor is None:
            return

        if visitor.is_blacklisted:
            raise ValidationError(
                {
                    "external_visitor": (
                        f"{visitor.full_name} berstatus blacklist: "
                        f"{visitor.blacklist_reason or 'tanpa alasan'}."
                    ),
                },
            )

        missing = [
            label
            for label, value in (
                ("Full Name", visitor.full_name),
                ("Identity Number", visitor.identity_number),
            )
            if not (value or "").strip()
        ]

        if missing:
            raise ValidationError(
                {
                    "external_visitor": (
                        f"Data tamu belum lengkap — "
                        f"{', '.join(missing)} masih kosong. Lengkapi "
                        "dulu di Visitor Master."
                    ),
                },
            )

    @staticmethod
    def apply_document_number(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("document_number"):
            return data

        data["document_number"] = DocumentNumberService.next(
            module="hr",
            document_type="visitor_request",
            company=data.get("company"),
        )

        return data

    # ------------------------------------------------------------------
    # Penjagaan sunting
    # ------------------------------------------------------------------

    @staticmethod
    def assert_editable(instance: VisitorRequest) -> None:
        """
        BR-10 / BR-11 — dokumen yang sedang berjalan atau sudah selesai
        tidak bisa disunting.

        Yang sudah ditandatangani harus tetap menunjuk isi yang
        ditandatangani. Untuk mengubahnya, tarik dulu pengajuannya —
        dan itu tindakan yang terlihat di jejak dokumen.
        """
        if instance.is_editable:
            return

        raise ValidationError(
            {
                "status": (
                    f"Dokumen berstatus "
                    f"{instance.get_status_display()} tidak bisa "
                    "disunting. Tarik kembali pengajuannya dulu "
                    "(Withdraw)."
                ),
            },
        )

    # ------------------------------------------------------------------
    # Alur persetujuan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit(cls, *, request: VisitorRequest, user=None, notes: str = ""):
        if request.status in VISITOR_OPEN_STATUSES:
            raise ValidationError(
                {"status": "Dokumen ini sudah diajukan."},
            )

        if request.status == VisitorRequestStatus.COMPLETED:
            raise ValidationError(
                {
                    "status": (
                        "Kunjungan sudah selesai — tidak ada yang perlu "
                        "diajukan lagi."
                    ),
                },
            )

        # BT-2A: draft/rejected internal lama tidak diteruskan ke alur.
        if request.visitor_type == VisitorType.INTERNAL:
            raise ValidationError({"visitor_type": INTERNAL_VISITOR_REJECTED})

        workflow = WorkflowService.submit(
            document=request,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
            # Cakupan approver dinilai dari penempatan **pemohon**:
            # tamunya boleh saja orang luar yang tidak punya penempatan
            # sama sekali, dan meja per-site tidak akan menemukan
            # siapa pun kalau diambil dari sana.
            employee=request.requester,
            user=user,
            context=cls.workflow_context(request),
            document_number=request.document_number or "",
            document_label=cls.workflow_label(request),
            notes=notes,
            on_complete=lambda wf, status: cls.on_workflow_done(
                request=request,
                status=status,
                user=user,
            ),
        )

        if workflow.status == InstanceStatus.PENDING:
            cls._set_status(
                request=request,
                status=VisitorRequestStatus.SUBMITTED,
                user=user,
            )

        return workflow

    @classmethod
    @transaction.atomic
    def decide(
        cls,
        *,
        request: VisitorRequest,
        approved: bool,
        user=None,
        notes: str = "",
    ):
        workflow = cls.workflow_for(request)

        if workflow is None:
            raise ValidationError(
                {"status": "Dokumen ini tidak sedang menunggu persetujuan."},
            )

        handler = (
            WorkflowService.approve
            if approved
            else WorkflowService.reject
        )

        result = handler(
            instance=workflow,
            user=user,
            comment=notes,
            on_complete=lambda wf, status: cls.on_workflow_done(
                request=request,
                status=status,
                user=user,
            ),
        )

        # Masih ada meja di depan berarti dokumennya sedang ditinjau,
        # bukan sekadar "sudah diajukan". Ini satu-satunya tempat
        # perpindahan itu bisa terjadi — engine sengaja tidak punya
        # hook per-step, jadi keputusan yang diambil dari kotak masuk
        # generik membiarkan statusnya SUBMITTED sampai meja terakhir.
        # Keduanya berarti "sedang berjalan"; yang membedakan cuma
        # keterbacaannya di layar daftar.
        workflow.refresh_from_db()

        if workflow.status == InstanceStatus.PENDING:
            cls._set_status(
                request=request,
                status=VisitorRequestStatus.UNDER_REVIEW,
                user=user,
            )

        return result

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, request: VisitorRequest, user=None, notes: str = ""):
        workflow = cls.workflow_for(request)

        if workflow is None:
            raise ValidationError(
                {"status": "Tidak ada pengajuan yang bisa ditarik."},
            )

        WorkflowService.cancel(
            instance=workflow,
            user=user,
            comment=notes,
        )

        cls._set_status(
            request=request,
            status=VisitorRequestStatus.DRAFT,
            user=user,
        )

        return workflow

    @classmethod
    def workflow_for(cls, request: VisitorRequest):
        return WorkflowService.instance_for(
            document=request,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
        )

    @classmethod
    def on_workflow_done(cls, *, request, status, user=None):
        """
        Dipanggil engine saat alurnya berhenti.

        Juga dipakai handler di `apps/hr/workflow_handlers.py` — jalur
        yang dilewati kalau approver menekan tombolnya dari kotak masuk
        generik, bukan dari layar Visitor Request.
        """
        mapping = {
            InstanceStatus.PENDING: VisitorRequestStatus.SUBMITTED,
            InstanceStatus.APPROVED: VisitorRequestStatus.APPROVED,
            InstanceStatus.REJECTED: VisitorRequestStatus.REJECTED,
            # Dikembalikan untuk diperbaiki: dokumennya harus bisa
            # disunting lagi, jadi turun ke DRAFT — bukan status baru
            # yang harus dikenali seluruh layar.
            InstanceStatus.RETURNED: VisitorRequestStatus.DRAFT,
            InstanceStatus.CANCELLED: VisitorRequestStatus.DRAFT,
        }

        target = mapping.get(status)

        if target is None:
            return request

        return cls._set_status(request=request, status=target, user=user)

    @staticmethod
    def _set_status(*, request, status, user=None):
        if request.status == status:
            return request

        request.status = status
        request.updated_by = user

        request.save(
            update_fields=["status", "updated_by", "updated_at"],
        )

        return request

    @staticmethod
    def workflow_context(request: VisitorRequest) -> dict:
        """Nilai yang bisa dipakai `WorkflowStep.condition`."""
        return {
            "visitor_type": request.visitor_type,
            "visit_purpose_code": getattr(request.visit_purpose, "code", None),
            "visit_type_code": getattr(request.visit_type, "code", None),
            "location_code": getattr(request.location, "code", None),
            "number_of_visitors": request.number_of_visitors,
            "travel_required": request.travel_required,
            "accommodation_required": request.accommodation_required,
            "duration_days": request.expected_duration_days,
            "visit_start_date": (
                request.visit_start_date.isoformat()
                if request.visit_start_date
                else None
            ),
        }

    @staticmethod
    def workflow_label(request: VisitorRequest) -> str:
        return (
            f"Visitor Request {request.document_number or ''} — "
            f"{request.visitor_name}"
        ).strip()

    # ------------------------------------------------------------------
    # Kedatangan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def check_in(
        cls,
        *,
        request: VisitorRequest,
        user=None,
        gate: str = "",
        remarks: str = "",
        issue_pass: bool = True,
    ) -> VisitorRequest:
        """
        BR-08 — hanya dokumen yang sudah disetujui bisa check-in.

        Barisnya dikunci lebih dulu dan keadaannya dibaca ulang dari
        database: dua satpam yang menekan tombol bersamaan sama-sama
        memegang instance yang masih berbunyi "belum check-in", dan
        tanpa penguncian keduanya berhasil — jam masuk yang belakangan
        menimpa yang duluan, dan dua kartu terbit untuk satu orang.
        """
        request = (
            VisitorRequest.objects
            .select_for_update()
            .get(pk=request.pk)
        )

        if request.status != VisitorRequestStatus.APPROVED:
            raise ValidationError(
                {
                    "status": (
                        f"Kunjungan berstatus "
                        f"{request.get_status_display()} belum bisa "
                        "check-in. Hanya dokumen yang sudah Approved "
                        "yang boleh masuk."
                    ),
                },
            )

        if request.checked_in_at is not None:
            raise ValidationError(
                {
                    "arrival_status": (
                        f"Tamu ini sudah check-in pada "
                        f"{timezone.localtime(request.checked_in_at):%d/%m/%Y %H:%M}."
                    ),
                },
            )

        now = timezone.now()

        request.checked_in_at = now
        request.checked_in_by = user
        request.check_in_gate = gate or request.check_in_gate
        request.check_in_remarks = remarks or request.check_in_remarks
        request.arrival_status = VisitorArrivalStatus.CHECKED_IN
        request.updated_by = user

        request.save(
            update_fields=[
                "checked_in_at",
                "checked_in_by",
                "check_in_gate",
                "check_in_remarks",
                "arrival_status",
                "updated_by",
                "updated_at",
            ],
        )

        if issue_pass:
            VisitorPassService.issue(request=request, user=user)

        return request

    @classmethod
    @transaction.atomic
    def check_out(
        cls,
        *,
        request: VisitorRequest,
        user=None,
        remarks: str = "",
    ) -> VisitorRequest:
        """
        BR-09 — check-out hanya setelah check-in, dan itu yang menutup
        kunjungannya (`COMPLETED`).

        Kartu yang masih dipegang tamunya ikut ditandai kembali. Kalau
        tidak, laporan "kartu belum kembali" akan memuat setiap tamu
        yang pernah datang, dan sesudah itu tidak ada yang membacanya.
        """
        request = (
            VisitorRequest.objects
            .select_for_update()
            .get(pk=request.pk)
        )

        if request.checked_in_at is None:
            raise ValidationError(
                {
                    "arrival_status": (
                        "Tamu ini belum check-in, jadi tidak ada yang "
                        "bisa di-check-out."
                    ),
                },
            )

        if request.checked_out_at is not None:
            raise ValidationError(
                {
                    "arrival_status": (
                        f"Tamu ini sudah check-out pada "
                        f"{timezone.localtime(request.checked_out_at):%d/%m/%Y %H:%M}."
                    ),
                },
            )

        now = timezone.now()

        request.checked_out_at = now
        request.checked_out_by = user
        request.check_out_remarks = remarks or request.check_out_remarks
        request.arrival_status = VisitorArrivalStatus.CHECKED_OUT
        request.status = VisitorRequestStatus.COMPLETED
        request.updated_by = user

        request.save(
            update_fields=[
                "checked_out_at",
                "checked_out_by",
                "check_out_remarks",
                "arrival_status",
                "status",
                "updated_by",
                "updated_at",
            ],
        )

        VisitorPassService.close_open_passes(request=request, user=user)

        return request

    @classmethod
    @transaction.atomic
    def mark_no_show(
        cls,
        *,
        request: VisitorRequest,
        user=None,
        remarks: str = "",
    ) -> VisitorRequest:
        """
        Tamu yang tidak jadi datang.

        Dokumennya **tidak** dibatalkan: kunjungan yang disetujui lalu
        tidak dihadiri adalah fakta yang perlu terbaca, dan menandainya
        Cancelled membuatnya tidak bisa dibedakan dari yang ditarik
        pengajunya sendiri.
        """
        if request.checked_in_at is not None:
            raise ValidationError(
                {
                    "arrival_status": (
                        "Tamu ini sudah check-in — tidak bisa ditandai "
                        "No Show."
                    ),
                },
            )

        request.arrival_status = VisitorArrivalStatus.NO_SHOW
        request.check_in_remarks = remarks or request.check_in_remarks
        request.updated_by = user

        request.save(
            update_fields=[
                "arrival_status",
                "check_in_remarks",
                "updated_by",
                "updated_at",
            ],
        )

        return request


class VisitorPassService(BaseMasterService):
    """
    Kartu tamu.

    Penerbitannya lewat service, bukan `objects.create` di view: nomor
    kartu diambil dari deret bersama, dan dua tempat yang menerbitkan
    kartu berarti dua tempat yang bisa lupa mengambil nomornya.
    """

    model = VisitorPass

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_issuable(data.get("request"))

        data = cls.apply_validity(data)

        return cls.apply_pass_number(data)

    @staticmethod
    def assert_issuable(request: VisitorRequest | None) -> None:
        """
        BR-12 — kartu hanya untuk kunjungan yang sudah disetujui.

        `COMPLETED` ikut diterima: kunjungan yang sudah check-out masih
        bisa perlu cetak ulang kartunya untuk arsip, dan menolaknya
        berarti kartu yang hilang di hari terakhir tidak bisa diganti.
        """
        if request is None:
            return

        allowed = {
            VisitorRequestStatus.APPROVED,
            VisitorRequestStatus.COMPLETED,
        }

        if request.status in allowed:
            return

        raise ValidationError(
            {
                "request": (
                    f"Visitor Pass hanya bisa diterbitkan untuk "
                    f"kunjungan yang sudah disetujui. Dokumen ini "
                    f"berstatus {request.get_status_display()}."
                ),
            },
        )

    @staticmethod
    def apply_validity(data: dict[str, Any]) -> dict[str, Any]:
        """
        Masa berlaku mengikuti rentang kunjungannya kalau tidak disebut.

        Kartu yang berlaku lebih lama daripada kunjungannya adalah
        justru hal yang dicegah kartu tamu.
        """
        request = data.get("request")

        if request is None:
            return data

        if data.get("valid_from") is None:
            data["valid_from"] = request.visit_start_date

        if data.get("valid_until") is None:
            data["valid_until"] = request.visit_end_date

        return data

    @staticmethod
    def apply_pass_number(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("pass_number"):
            return data

        request = data.get("request")

        data["pass_number"] = DocumentNumberService.next(
            module="hr",
            document_type="visitor_pass",
            company=getattr(request, "company", None),
        )

        return data

    @classmethod
    def issue(cls, *, request: VisitorRequest, user=None) -> VisitorPass:
        """
        Menerbitkan satu kartu untuk kunjungan ini.

        Kalau masih ada kartu yang dipegang tamunya, kartu itu yang
        dikembalikan — bukan kartu kedua. Satu orang di dalam lokasi
        memegang satu kartu; menerbitkan yang kedua membuat laporan
        "siapa yang sedang di dalam" menghitungnya dua kali.
        """
        existing = (
            request.passes
            .filter(status=VisitorPassStatus.ISSUED, is_deleted=False)
            .order_by("-id")
            .first()
        )

        if existing is not None:
            return existing

        return cls.create(
            data={
                "request": request,
                "issued_at": timezone.now(),
                "issued_by": user,
                "status": VisitorPassStatus.ISSUED,
            },
            user=user,
        )

    @classmethod
    def close_open_passes(cls, *, request: VisitorRequest, user=None) -> int:
        """
        Menandai kembali seluruh kartu yang masih dipegang.

        Lewat query langsung, bukan `update()` per baris via service:
        ini penutupan turunan dari check-out, bukan tindakan tersendiri
        yang layak punya barisnya sendiri di jejak audit.
        """
        now = timezone.now()

        return (
            request.passes
            .filter(status=VisitorPassStatus.ISSUED, is_deleted=False)
            .update(
                status=VisitorPassStatus.RETURNED,
                returned_at=now,
                returned_by=user,
                updated_by=user,
                updated_at=now,
            )
        )

    @classmethod
    @transaction.atomic
    def mark_returned(
        cls,
        *,
        instance: VisitorPass,
        user=None,
        notes: str = "",
    ) -> VisitorPass:
        if instance.status != VisitorPassStatus.ISSUED:
            raise ValidationError(
                {
                    "status": (
                        f"Kartu ini berstatus "
                        f"{instance.get_status_display()}, bukan Issued."
                    ),
                },
            )

        return cls.update(
            instance=instance,
            data={
                "status": VisitorPassStatus.RETURNED,
                "returned_at": timezone.now(),
                "returned_by": user,
                "notes": notes or instance.notes,
            },
            user=user,
        )

    @classmethod
    @transaction.atomic
    def mark_lost(
        cls,
        *,
        instance: VisitorPass,
        user=None,
        notes: str = "",
    ) -> VisitorPass:
        if not notes.strip():
            raise ValidationError(
                {"notes": "Keterangan wajib diisi kalau kartu hilang."},
            )

        return cls.update(
            instance=instance,
            data={
                "status": VisitorPassStatus.LOST,
                "notes": notes,
            },
            user=user,
        )
