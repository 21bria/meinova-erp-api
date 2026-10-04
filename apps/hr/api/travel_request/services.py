"""
Service Travel Request.

Tiga hal yang jadi tanggung jawabnya dan tidak boleh bocor ke tempat
lain: mengisi dokumen dari blok jadwal (kalau ada), menjalankan alur
persetujuan, dan menerbitkan catatan cuti begitu pengajuannya disetujui.

Yang **tidak** dilakukan di sini: menghitung hari cuti dan memotong
saldo. Itu tetap milik `EmployeeLeaveService` — menyalin logikanya ke
sini berarti dua sumber angka untuk cuti yang sama, dan yang satu
diam-diam salah.
"""

from __future__ import annotations

import logging

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.administration.models import RotationPurpose
from apps.core.services.master import BaseMasterService
from apps.workflow.models import InstanceStatus
from apps.workflow.services import WorkflowService

from apps.hr.api.leave.rules import LeaveRuleEvaluator
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.api.mixins import OrganizationDenormalizationMixin
from apps.hr.applicability import HRFeature, is_applicable
from apps.hr.api.site_rotation.services import (
    inbound_travel_window,
    outbound_travel_window,
)
from apps.hr.api.travel_request import notifications as travel_notifications
from apps.hr.models import (
    LEAVE_DEDUCTING_STATUSES,
    TRAVEL_REQUEST_ACTIVE_STATUSES,
    Employee,
    LeaveStatus,
    RosterSegmentType,
    RotationPeriodType,
    TravelArrangement,
    TravelDirection,
    TravelRequest,
    TravelRequestPurpose,
    TravelRequestStatus,
)


logger = logging.getLogger(__name__)


# Pita perjalanan pada jalur roster baru. Bukan blok off yang bisa
# diajukan sebagai kepulangan, walau `period_type`-nya sama-sama OFF.
TRAVEL_SEGMENT_TYPES = frozenset(
    {
        RosterSegmentType.TRAVEL_OUT,
        RosterSegmentType.TRAVEL_IN,
    },
)


class TravelRequestService(
    OrganizationDenormalizationMixin,
    BaseMasterService,
):
    model = TravelRequest

    WORKFLOW_MODULE = "hr"
    WORKFLOW_DOCUMENT_TYPE = "travel_request"

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
        cls.assert_field_break_applicable(data.get("employee"))

        data = cls.apply_organization(data)
        data = cls.apply_rotation_period(data)

        cls.assert_dates(data)
        cls.assert_period_available(data.get("rotation_period"))

        # Nomor dokumen diambil paling akhir: deret nomor tidak
        # dikembalikan kalau validasinya gagal sesudahnya, jadi
        # penolakan di atas tidak boleh meninggalkan lubang di
        # penomoran.
        return cls.apply_document_number(data)

    @staticmethod
    def assert_field_break_applicable(employee) -> None:
        """
        Travel Request adalah dokumen **satu kepulangan site** — blok
        Field Break-nya yang jadi isi utama, dan cuti tahunan cuma bisa
        ditumpuk di atasnya. Karena itu penanda yang dibaca
        `field_break_applicable`, bukan `leave_applicable`: yang tidak
        punya blok off site tidak punya kepulangan untuk diajukan, walau
        cutinya tetap berlaku lewat modul Cuti.

        Diperiksa di jalur **create dan submit** (TR/BT POLICY-1, pola
        yang sama dengan Business Trip), tidak di `clean()`. Dokumen
        yang sudah diajukan atau disetujui tetap bisa dirawat sampai
        selesai kalau kebijakan group-nya berubah di tengah jalan —
        menolaknya di `clean()` akan mengunci dokumen yang sudah
        disetujui dan sudah dibelikan tiket.
        """
        if employee is None:
            return

        if is_applicable(employee, HRFeature.FIELD_BREAK):
            return

        group = getattr(
            getattr(employee, "employment", None),
            "employee_group",
            None,
        )

        raise ValidationError(
            {
                "employee": (
                    f"Employee Group \"{getattr(group, 'name', '-')}\" "
                    "tidak memakai Field Break, jadi tidak punya blok "
                    "kepulangan site untuk diajukan. Nyalakan Field "
                    "Break pada master Employee Group kalau "
                    "kebijakannya berubah."
                ),
            },
        )

    @staticmethod
    def assert_dates(data: dict[str, Any]) -> None:
        """
        Menolak pengajuan tanpa tanggal dengan pesan yang bisa
        ditindaklanjuti.

        Dijaga di sini, bukan di `Model.clean()`: `full_clean()`
        menjalankan `clean_fields()` lebih dulu, dan pesan bawaannya
        ("This field cannot be null") muncul sebagai error pertama —
        yang justru itu yang ditampilkan form. Menjaganya sebelum model
        membuat pesan yang berguna jadi satu-satunya yang keluar.
        """
        missing = {
            field_name: (
                f"{label} wajib diisi. Pilih Blok Jadwal supaya terisi "
                "otomatis dari periode off-nya, atau isi manual."
            )
            for field_name, label in (
                ("start_date", "Off Mulai"),
                ("end_date", "Off Selesai"),
            )
            if data.get(field_name) is None
        }

        if missing:
            raise ValidationError(missing)

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

        data = cls.apply_organization(
            data,
            fallback_employee=instance.employee,
        )

        data = cls.apply_rotation_period(data, instance=instance)

        # Dokumen yang sudah menunjuk sebuah blok tidak boleh menabrak
        # dirinya sendiri, jadi dirinya dikecualikan. Yang dijaga di
        # sini adalah PATCH yang **memindahkan** `rotation_period` ke
        # blok yang sudah dipegang dokumen lain.
        cls.assert_period_available(
            data.get(
                "rotation_period",
                instance.rotation_period,
            ),
            exclude=instance,
        )

        return data

    @classmethod
    def assert_period_available(
        cls,
        period,
        *,
        exclude: TravelRequest | None = None,
    ) -> None:
        """
        Satu blok jadwal hanya boleh punya satu Travel Request aktif.

        Tanpa ini `from-rotation-period` yang ditekan dua kali — atau
        satu klik yang terkirim ganda — menerbitkan dua dokumen untuk
        kepulangan yang sama. Keduanya lolos sampai akhir, dan begitu
        dua-duanya disetujui `issue_leave_records` memotong saldo
        cutinya dua kali; yang ketahuan belakangan lewat saldo yang
        tidak cocok, bukan lewat error.

        Dijaga di service, bukan di view: `from-rotation-period`,
        create biasa, dan PATCH yang memindahkan `rotation_period`
        adalah tiga jalur masuk yang berbeda ke lubang yang sama.

        REJECTED dan CANCELLED tidak menghalangi — pengajuan yang
        ditolak harus bisa diajukan ulang untuk blok yang sama.
        """
        if period is None:
            return

        candidates = TravelRequest.objects.filter(
            rotation_period=period,
            status__in=TRAVEL_REQUEST_ACTIVE_STATUSES,
            is_deleted=False,
        )

        # `.exclude(pk=None)` tidak menyaring apa pun tapi terbaca
        # seperti menyaring, jadi pengecualiannya dinyatakan terpisah.
        if exclude is not None and exclude.pk:
            candidates = candidates.exclude(pk=exclude.pk)

        existing = candidates.order_by("pk").first()

        if existing is None:
            return

        # Nomor dokumennya ikut disebut supaya penolakannya bisa
        # ditindaklanjuti tanpa mencari dulu. Dokumen yang deret
        # nomornya belum diseed terbit tanpa nomor — itu keadaan yang
        # sah, jadi ada teks penggantinya.
        label = existing.document_number or f"#{existing.pk}"

        raise ValidationError(
            {
                "rotation_period": (
                    f"Blok jadwal ini sudah punya Travel Request "
                    f"{label} berstatus "
                    f"{existing.get_status_display()}. Batalkan atau "
                    "tolak dokumen itu dulu sebelum membuat yang baru."
                ),
            },
        )

    @staticmethod
    def assert_editable(instance: TravelRequest) -> None:
        """
        Dokumen yang sedang menunggu atau sudah disetujui tidak boleh
        disunting.

        Bukan kerewelan: yang sudah ditandatangani harus tetap menunjuk
        isi yang ditandatangani. Kalau memang perlu diubah, tarik dulu
        pengajuannya (Withdraw) — dan itu tindakan yang terlihat.
        """
        if instance.is_editable:
            return

        raise ValidationError(
            {
                "status": (
                    f"Dokumen berstatus "
                    f"{instance.get_status_display()} tidak bisa "
                    "disunting. Tarik kembali pengajuannya dulu."
                ),
            },
        )

    @staticmethod
    def apply_document_number(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("document_number"):
            return data

        data["document_number"] = DocumentNumberService.next(
            module="hr",
            document_type="travel_request",
            company=data.get("company"),
        )

        return data

    @staticmethod
    def apply_rotation_period(
        data: dict[str, Any],
        *,
        instance: TravelRequest | None = None,
    ) -> dict[str, Any]:
        """
        Menyalin tanggal dari blok off jadwal yang ditunjuk.

        Hanya mengisi yang masih kosong. Blok jadwal adalah **usulan**
        tanggal, bukan pengunci: kepulangan yang dimajukan tiga hari
        karena kapal berubah tetap harus bisa diajukan tanpa mengubah
        jadwal tahunannya lebih dulu.
        """
        period = data.get(
            "rotation_period",
            getattr(instance, "rotation_period", None),
        )

        if period is None:
            return data

        data.setdefault("start_date", period.start_date)
        data.setdefault("end_date", period.end_date)

        return data

    # ------------------------------------------------------------------
    # Prefill dari jadwal
    # ------------------------------------------------------------------

    @classmethod
    def build_from_period(cls, *, period, user=None) -> TravelRequest:
        """
        Membuat TR dari satu blok off jadwal, lengkap dengan perkiraan
        tanggal travel-nya.

        Jalan pintas untuk kasus yang paling sering: admin membuka
        jadwal, melihat blok off berikutnya, dan mengajukannya apa
        adanya. Semua isinya masih bisa disunting sesudahnya — ini
        pengisi awal, bukan penerbit dokumen final.
        """
        # Segmen travel jalur baru juga ber-`period_type` OFF (hari
        # perjalanan tidak dihitung hari kerja), jadi memeriksa
        # `period_type` saja akan menerima pita perjalanan sebagai
        # "blok off" dan menerbitkan TR untuk kepulangan yang tidak ada.
        # Yang dicari field break-nya.
        if (
            period.period_type != RotationPeriodType.OFF
            or period.segment_type in TRAVEL_SEGMENT_TYPES
        ):
            raise ValidationError(
                {
                    "rotation_period": (
                        "Travel Request hanya dibuat dari blok Off. "
                        "Blok kerja dan pita perjalanan bukan "
                        "kepulangan."
                    ),
                },
            )

        rotation = period.rotation

        request = cls.create(
            data={
                "employee": period.employee,
                "rotation_period": period,
                "company": rotation.company,
                "branch": rotation.branch,
                "location": rotation.location,
                "start_date": period.start_date,
                "end_date": period.end_date,
            },
            user=user,
        )

        # Satu baris tujuan bawaan kalau blok jadwalnya sudah menyebut
        # alasannya. Kalau belum, pengaju yang mengisinya — menebak
        # "Field Break" untuk semua orang akan membuat cuti tahunan
        # tercatat sebagai field break dan saldonya tidak pernah
        # terpotong. Alasan milik Business Trip tidak disalin: sama
        # dengan blok tanpa alasan, pengaju yang memilih.
        if (
            period.purpose_id
            and not period.purpose.is_business_trip_domain
        ):
            TravelRequestPurposeService.create(
                data={
                    "request": request,
                    "purpose": period.purpose,
                    "start_date": period.start_date,
                    "end_date": period.end_date,
                },
                user=user,
            )

        # Perkiraan jendela travel **dibaca dari jadwal**, tidak
        # dihitung ulang di sini.
        #
        # `cycle_travel_days` adalah total pulang-pergi. Dulu angka itu
        # dipakai utuh untuk kedua arah, jadi etape keluar mundur satu
        # hari terlalu jauh sampai menabrak hari kerja terakhir dan
        # etape pulang jadi dua kali lebih panjang dari jendela yang
        # sama di layar roster — dua tanggal berbeda untuk perjalanan
        # yang sama, dan yang satu diam-diam salah. Pemecahannya milik
        # roster (`ceil` keluar, `floor` kembali), dan sekarang cuma ada
        # di sana.
        site, point_of_hire = cls.route_endpoints(period.employee)

        outbound = outbound_travel_window(period)
        inbound = inbound_travel_window(period)

        # Satu etape per arah sebagai titik awal. Rute bersambungnya
        # tidak ditebak: Jakarta → Sorong → Gebe dan Makassar → Sorong →
        # Gebe berangkat di hari yang berbeda walau tiba bersamaan, dan
        # itu bergantung jadwal penerbangan hari itu — bukan sesuatu
        # yang bisa dihitung dari master. Barisnya dipecah pengaju lewat
        # tombol Add Row di tabel Travel Arrangement.
        #
        # Dua arah diperiksa terpisah: jendela yang tidak disediakan
        # jadwal berarti barisnya tidak dibuat, bukan barisnya ditebak.
        if outbound is not None:
            cls.build_leg(
                request=request,
                direction=TravelDirection.OUTBOUND,
                window=outbound,
                origin=site,
                destination=point_of_hire,
                user=user,
            )

        if inbound is not None:
            cls.build_leg(
                request=request,
                direction=TravelDirection.INBOUND,
                window=inbound,
                origin=point_of_hire,
                destination=site,
                user=user,
            )

        return cls.sync_totals(request)

    @staticmethod
    def build_leg(
        *,
        request: TravelRequest,
        direction: str,
        window: tuple,
        origin: str,
        destination: str,
        user=None,
    ) -> TravelArrangement:
        """
        Satu etape awal dari sebuah jendela travel.

        `travel_end_date` dikosongkan kalau jendelanya sehari — kolom
        itu memang berarti "tiba di hari yang lain", dan mengisinya
        dengan tanggal yang sama membuat setiap perjalanan sehari
        terbaca seperti perjalanan yang tanggal tibanya sudah
        dipastikan.
        """
        start, end = window

        return TravelArrangementService.create(
            data={
                "request": request,
                "direction": direction,
                "travel_start_date": start,
                "travel_end_date": end if end != start else None,
                "origin": origin,
                "destination": destination,
            },
            user=user,
        )

    @staticmethod
    def route_endpoints(employee) -> tuple[str, str]:
        """
        Titik ujung rute pegawai: site tempatnya bekerja dan kota
        rekrutnya.

        Teks, bukan relasi. Site dan Point of Hire memang master
        (Location dan City), tapi titik transit di tengah — Sorong,
        Ternate — belum tentu terdaftar di keduanya, dan memaksa setiap
        bandara transit dibuatkan baris master lebih dulu akan
        menghentikan orang yang cuma mau mengetik nomor tiket.
        """
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        location = getattr(organization, "location", None)
        point_of_hire = getattr(employment, "point_of_hire", None)

        return (
            getattr(location, "name", "") or "",
            getattr(point_of_hire, "name", "") or "",
        )

    # ------------------------------------------------------------------
    # Rekap
    # ------------------------------------------------------------------

    @classmethod
    def sync_totals(cls, request: TravelRequest) -> TravelRequest:
        """
        Menjumlahkan ulang hari dan merapatkan rentang dokumen ke baris
        tujuannya.

        Dijumlahkan ulang dari baris, bukan ditambah inkremental:
        penjumlahan ulang tidak bisa hanyut kalau ada baris yang diubah
        tanggalnya atau dihapus.
        """
        purposes = list(
            request.purposes.filter(is_deleted=False),
        )

        if purposes:
            total = sum(
                (purpose.total_days or 0)
                for purpose in purposes
            )

            start = min(purpose.start_date for purpose in purposes)
            end = max(purpose.end_date for purpose in purposes)
        else:
            # Baris tujuan terakhir dihapus. Dulu fungsi ini keluar
            # lebih awal di sini dan `total_days` tertinggal memakai
            # angka baris yang sudah tidak ada — dokumen kosong yang
            # tetap melaporkan 14 hari di kolom tabel yang bisa
            # disortir.
            #
            # Rentangnya dikembalikan ke blok jadwal yang ditunjuk
            # kalau ada, karena itu asal-usulnya; kalau tidak, tanggal
            # yang ada dipertahankan — kolomnya `NOT NULL` dan
            # menebak nilai baru untuk dokumen yang sedang disunting
            # lebih buruk daripada membiarkan yang terakhir diketik.
            total = None

            period = request.rotation_period

            start = period.start_date if period else request.start_date
            end = period.end_date if period else request.end_date

        changed = [
            field
            for field, value in (
                ("total_days", total),
                ("start_date", start),
                ("end_date", end),
            )
            if getattr(request, field) != value
        ]

        if not changed:
            return request

        request.total_days = total
        request.start_date = start
        request.end_date = end

        request.save(update_fields=changed + ["updated_at"])

        return request

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit(cls, *, request: TravelRequest, user=None, notes: str = ""):
        # Hanya DRAFT dan REJECTED yang boleh diajukan.
        #
        # `WorkflowService.submit` sendiri cuma menolak instance yang
        # masih **terbuka**; dokumen yang sudah APPROVED instance-nya
        # sudah ditutup, jadi tanpa penjagaan ini pengajuan kedua
        # terbentuk dengan mulus dan statusnya mundur APPROVED →
        # SUBMITTED — dokumen yang tiketnya sudah dibeli kembali
        # menunggu tanda tangan. Tombolnya memang disembunyikan
        # `visible_when` di schema, tapi itu tampilan, bukan pagar.
        cls.assert_editable(request)

        # Kelayakan diperiksa ulang saat diajukan, bukan hanya saat
        # dibuat (pola Business Trip, TR/BT POLICY-1): group pegawainya
        # bisa saja dimatikan Field Break-nya selama dokumennya masih
        # draf. Dokumen yang sudah SUBMITTED/APPROVED tidak tersentuh —
        # yang diperiksa cuma pengajuan baru. Dibaca segar dari
        # database: `request.employee` bisa membawa group yang ter-cache
        # sejak dokumennya dibuat, persis keadaan yang sedang diperiksa.
        cls.assert_field_break_applicable(
            Employee.objects
            .select_related("employment__employee_group")
            .get(pk=request.employee_id),
        )

        if not request.purposes.filter(is_deleted=False).exists():
            raise ValidationError(
                {
                    "purposes": (
                        "Isi dulu minimal satu baris Travel Purpose — "
                        "pengajuan tanpa alasan tidak bisa dinilai "
                        "penyetujunya."
                    ),
                },
            )

        # Draf lama yang barisnya masih DUTY/TRAINING tidak boleh
        # diajukan sebagai Travel Request (TR-CLEANUP-1). Dokumen yang
        # sudah SUBMITTED/APPROVED tidak lewat sini dan tidak tersentuh.
        business_trip_rows = [
            row.purpose.name
            for row in (
                request.purposes
                .filter(is_deleted=False)
                .select_related("purpose")
            )
            if row.purpose.is_business_trip_domain
        ]

        if business_trip_rows:
            raise ValidationError(
                {
                    "purposes": (
                        "Travel Purpose "
                        + ", ".join(sorted(set(business_trip_rows)))
                        + " adalah tugas dinas perusahaan — ganti "
                        "alasannya atau ajukan lewat Business Trip."
                    ),
                },
            )

        cls.sync_totals(request)
        cls.assert_no_leave_conflict(request)

        # Penjagaan timbal balik dengan Business Trip (BT-2, keputusan
        # BT-0B #2): satu hari tidak dimiliki dua dokumen perjalanan, dan
        # hasilnya tidak bergantung pada dokumen mana yang diajukan lebih
        # dulu. Satu-satunya perubahan perilaku TR dari pekerjaan
        # Business Trip.
        from apps.hr.api.business_trip.overlap import (
            assert_travel_request_has_no_business_trip,
        )

        assert_travel_request_has_no_business_trip(request)

        workflow = WorkflowService.submit(
            document=request,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
            employee=request.employee,
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
                status=TravelRequestStatus.SUBMITTED,
                user=user,
            )

        return workflow

    @classmethod
    def assert_no_leave_conflict(cls, request: TravelRequest) -> None:
        """
        Menolak pengajuan yang baris cutinya bentrok dengan catatan cuti
        yang sudah ada.

        Diperiksa **saat Submit**, bukan saat penerbitan di akhir alur.
        Kalau menunggu sampai HRGA menekan Approve, kegagalannya
        membatalkan persetujuan yang sah dan muncul di layar orang yang
        tidak bisa memperbaikinya — pengajunya yang harus mengubah
        tanggal, dan dia sudah tidak memegang dokumen itu lagi.
        """
        purposes = (
            request.purposes
            .filter(is_deleted=False)
            .select_related("purpose", "purpose__leave_type")
        )

        for purpose in purposes:
            if not purpose.purpose.deducts_leave:
                continue

            # Sudah tertaut ke catatan cuti dari pengajuan sebelumnya —
            # itu bukan bentrokan, itu dokumen yang sama.
            if purpose.employee_leave_id:
                continue

            clashing = EmployeeLeaveService.find_overlap(
                employee=request.employee,
                start=purpose.start_date,
                end=purpose.end_date,
            )

            if clashing is None:
                continue

            label = clashing.document_number or f"#{clashing.pk}"

            raise ValidationError(
                {
                    "purposes": (
                        f"Baris '{purpose.purpose.name}' "
                        f"({purpose.start_date:%d/%m/%Y}–"
                        f"{purpose.end_date:%d/%m/%Y}) bentrok dengan "
                        f"{clashing.leave_type.name} {label} yang sudah "
                        "tercatat. Saldonya akan terpotong dua kali. "
                        "Ubah tanggalnya, atau batalkan catatan cuti "
                        "yang lama dulu."
                    ),
                },
            )

    @classmethod
    @transaction.atomic
    def decide(
        cls,
        *,
        request: TravelRequest,
        approved: bool,
        user=None,
        notes: str = "",
    ):
        workflow = cls.workflow_for(request)

        if workflow is None:
            raise ValidationError(
                {
                    "status": (
                        "Dokumen ini tidak sedang menunggu persetujuan."
                    ),
                },
            )

        handler = (
            WorkflowService.approve
            if approved
            else WorkflowService.reject
        )

        return handler(
            instance=workflow,
            user=user,
            comment=notes,
            on_complete=lambda wf, status: cls.on_workflow_done(
                request=request,
                status=status,
                user=user,
            ),
        )

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, request: TravelRequest, user=None, notes: str = ""):
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
            status=TravelRequestStatus.DRAFT,
            user=user,
        )

        return workflow

    @classmethod
    @transaction.atomic
    def cancel(cls, *, request: TravelRequest, user=None, notes: str = ""):
        """
        Membatalkan Travel Request yang **sudah disetujui**.

        Jalur ini bukan pengganti Withdraw. Withdraw menarik pengajuan
        yang alurnya masih terbuka dan mengembalikan dokumennya ke
        Draft supaya bisa diperbaiki — dokumen itu belum menerbitkan
        apa pun. Yang sudah APPROVED sebaliknya: alurnya sudah tertutup
        dan catatan cutinya sudah terbit, jadi yang dibutuhkan bukan
        "kembali ke Draft" melainkan akhir yang tercatat, dengan cuti
        yang ikut dicabut.

        Alur persetujuannya sengaja **tidak** disentuh. Instance-nya
        sudah tertutup berstatus APPROVED, dan persetujuan yang memang
        terjadi harus tetap terbaca di riwayat; membatalkannya surut
        akan menghapus tanda tangan yang benar-benar diberikan.

        Dokumennya berhenti di CANCELLED — tidak bisa disunting
        (`is_editable`), tidak bisa diajukan ulang (`submit` memanggil
        `assert_editable`), dan tidak lagi menghalangi TR baru untuk
        blok jadwal yang sama (`TRAVEL_REQUEST_ACTIVE_STATUSES`).
        Kalau perjalanannya jadi lagi, yang benar adalah dokumen baru
        dengan nomor baru.
        """
        if request.status == TravelRequestStatus.CANCELLED:
            # Idempotent. Pemanggilan kedua tidak boleh menyentuh
            # catatan cuti lagi — bukan karena `set_status` akan
            # menggandakan potongannya (tidak, saldo dihitung ulang
            # dari nol tiap kali), tapi supaya pembatalan yang sudah
            # selesai tidak menulis ulang `updated_by` catatan cuti
            # orang lain setiap kali tombolnya tertekan dua kali.
            return request

        if request.status != TravelRequestStatus.APPROVED:
            raise ValidationError(
                {
                    "status": (
                        f"Hanya dokumen berstatus "
                        f"{TravelRequestStatus.APPROVED.label} yang "
                        f"bisa dibatalkan lewat jalur ini. Dokumen ini "
                        f"berstatus {request.get_status_display()} — "
                        "pengajuan yang masih menunggu ditarik lewat "
                        "Withdraw, dan draft cukup dihapus."
                    ),
                },
            )

        cls.cancel_leave_records(request=request, user=user)

        cls._set_status(
            request=request,
            status=TravelRequestStatus.CANCELLED,
            user=user,
        )

        if notes:
            logger.info(
                "TR %s dibatalkan. Alasan: %s",
                request.document_number or request.pk,
                notes,
            )

        return request

    @classmethod
    def cancel_leave_records(cls, *, request: TravelRequest, user=None) -> int:
        """
        Mencabut catatan cuti yang **terbit dari** dokumen ini.

        Lewat `EmployeeLeaveService.set_status`, mekanisme yang sudah
        dipakai modul Cuti sendiri — bukan penghapusan, bukan
        pengurangan saldo dengan tangan. `LeaveStatus.CANCELLED` tidak
        ada di `LEAVE_DEDUCTING_STATUSES`, jadi
        `LeaveBalanceService.recalculate_used` yang dipanggil
        `set_status` menjumlahkan ulang kartu cutinya tanpa baris ini
        dan saldonya pulih sendiri. Menyentuh `LeaveBalance` dari sini
        berarti dua sumber angka untuk saldo yang sama.

        Yang dicabut hanya baris ber-`leave_issued`. Catatan cuti yang
        cuma **diadopsi** `issue_leave_records` (HR sudah mencatatnya
        lebih dulu di tanggal yang sama) tidak ikut: cutinya benar-benar
        terjadi, dan mengembalikan saldonya karena dokumen perjalanan
        dibatalkan akan memberi orang itu jatah yang sudah dipakai.

        Recordnya tetap ada dengan nomor LV-nya, dan tautannya ke baris
        Travel Purpose tidak dilepas — jejak "cuti ini pernah terbit
        dari TR ini, lalu dibatalkan" justru yang harus tersimpan.
        """
        cancelled = 0

        # Sengaja tanpa filter `is_deleted`: baris yang sudah dihapus
        # lunak pun catatan cutinya masih memotong saldo, dan
        # pembatalan yang melewatinya meninggalkan potongan yang tidak
        # punya dokumen lagi.
        purposes = (
            request.purposes
            .filter(leave_issued=True, employee_leave__isnull=False)
            .select_related("employee_leave", "employee_leave__leave_type")
        )

        for purpose in purposes:
            leave = purpose.employee_leave

            if leave.status == LeaveStatus.CANCELLED:
                continue

            EmployeeLeaveService.set_status(
                instance=leave,
                status=LeaveStatus.CANCELLED,
                user=user,
            )

            logger.info(
                "TR %s dibatalkan: catatan cuti %s (%s) ikut "
                "dibatalkan, saldonya dihitung ulang.",
                request.document_number or request.pk,
                leave.document_number or leave.pk,
                leave.leave_type.name,
            )

            cancelled += 1

        return cancelled

    @classmethod
    def workflow_for(cls, request: TravelRequest):
        return WorkflowService.instance_for(
            document=request,
            module=cls.WORKFLOW_MODULE,
            document_type=cls.WORKFLOW_DOCUMENT_TYPE,
        )

    @classmethod
    def on_workflow_done(cls, *, request, status, user=None):
        """
        Dipanggil engine saat alurnya berhenti.

        Juga dipakai handler di `apps/hr/workflow_handlers.py`, yaitu
        jalur yang dilewati kalau approver menekan tombolnya dari kotak
        masuk generik — bukan dari layar TR.
        """
        cls._apply_status(
            request=request,
            workflow_status=status,
            user=user,
        )

        if status == InstanceStatus.APPROVED:
            cls.issue_leave_records(request=request, user=user)

            # Setelah catatan cutinya terbit, bukan sebelum: kalau
            # penerbitannya gagal (master Travel Purpose belum menunjuk
            # Leave Type), transaksinya dibatalkan dan pegawainya sudah
            # terlanjur diberi tahu jadwal yang tidak jadi tersimpan.
            #
            # `notify()` sendiri menjadwalkan emailnya lewat
            # `transaction.on_commit`, jadi surat tetap tidak terkirim
            # kalau ada yang gagal di belakang baris ini.
            travel_notifications.notify_issued(request)

        return request

    @classmethod
    def _apply_status(cls, *, request, workflow_status, user=None):
        mapping = {
            InstanceStatus.PENDING: TravelRequestStatus.SUBMITTED,
            InstanceStatus.APPROVED: TravelRequestStatus.APPROVED,
            InstanceStatus.REJECTED: TravelRequestStatus.REJECTED,
            # Dikembalikan untuk diperbaiki: dokumennya harus bisa
            # disunting lagi, jadi turun ke DRAFT — bukan status baru
            # yang harus dikenali seluruh layar.
            InstanceStatus.RETURNED: TravelRequestStatus.DRAFT,
            # Alur yang ditarik pengaju (Withdraw) — dokumennya belum
            # menerbitkan apa pun dan memang harus bisa diisi lagi.
            # **Bukan** `TravelRequestStatus.CANCELLED`: status itu
            # hanya diset `cancel()`, untuk dokumen yang sudah
            # disetujui dan cutinya sudah terbit.
            InstanceStatus.CANCELLED: TravelRequestStatus.DRAFT,
        }

        target = mapping.get(workflow_status)

        if target is None:
            return request

        return cls._set_status(
            request=request,
            status=target,
            user=user,
        )

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
    def workflow_context(request: TravelRequest) -> dict:
        """Nilai yang bisa dipakai `WorkflowStep.condition`."""
        return {
            "total_days": request.total_days,
            "document_number": request.document_number or "",
            "start_date": (
                request.start_date.isoformat()
                if request.start_date
                else None
            ),
            "end_date": (
                request.end_date.isoformat()
                if request.end_date
                else None
            ),
            "employee_number": request.employee.employee_number,
            "location_code": getattr(request.location, "code", None),
        }

    @staticmethod
    def workflow_label(request: TravelRequest) -> str:
        return (
            f"Travel Request {request.document_number or ''} — "
            f"{request.employee.full_name}"
        ).strip()

    # ------------------------------------------------------------------
    # Penerbitan catatan cuti
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def issue_leave_records(cls, *, request: TravelRequest, user=None) -> int:
        """
        Menerbitkan `EmployeeLeave` untuk baris yang memang memotong
        saldo — dan hanya setelah pengajuannya disetujui.

        Kenapa saat disetujui, bukan saat diketik: cuti yang belum
        disetujui tidak boleh sudah mengurangi saldo orang. Kalau
        ditolak, tidak ada yang perlu dibatalkan.

        Kenapa lewat `EmployeeLeaveService`, bukan `objects.create`:
        service itu yang menghitung hari kerja pegawai (roster vs
        kalender HO) dan menjumlahkan ulang `LeaveBalance.used`.
        Membuat recordnya langsung lewat ORM akan menghasilkan cuti
        yang tidak pernah terhitung di saldo mana pun.

        Field Break tidak lewat sini sama sekali — `deducts_leave`-nya
        mati, dan itu memang blok off rosternya sendiri.
        """
        issued = 0

        # Satu evaluator untuk seluruh dokumen, bukan satu per baris:
        # `LeavePolicyResolver.resolve` menembak satu query tiap
        # dipanggil dan satu TR lazimnya berisi beberapa baris yang
        # menunjuk Leave Type yang sama. Pola yang sama dengan
        # `LeaveSerializer.get_policy_rules`.
        evaluator = LeaveRuleEvaluator()

        purposes = (
            request.purposes
            .filter(is_deleted=False)
            .select_related("purpose", "purpose__leave_type")
        )

        for purpose in purposes:
            if not purpose.purpose.deducts_leave:
                continue

            # Sudah pernah diterbitkan — pengajuan yang disetujui ulang
            # setelah ditarik tidak boleh memotong saldo dua kali.
            if purpose.employee_leave_id:
                continue

            leave_type = purpose.purpose.leave_type

            if leave_type is None:
                # Master-nya yang belum lengkap. Berisik di log lebih
                # baik daripada saldo yang diam-diam tidak terpotong,
                # tapi tidak boleh menggagalkan persetujuan yang sudah
                # terjadi.
                raise ValidationError(
                    {
                        "purposes": (
                            f"Travel Purpose '{purpose.purpose.name}' "
                            "ditandai memotong saldo tapi belum "
                            "menunjuk Leave Type. Lengkapi masternya "
                            "dulu."
                        ),
                    },
                )

            # Jaring terakhir. Penjagaannya sudah di `submit()`, tapi
            # keadaan bisa berubah selama dokumen berjalan — HR mencatat
            # cuti yang sama secara manual sementara TR-nya menunggu
            # tanda tangan. Di titik ini alurnya **sudah** disetujui;
            # melempar ValidationError akan membatalkan persetujuan yang
            # sah dan menampilkan pesan di layar orang yang tidak bisa
            # memperbaikinya. Jadi: yang **sudah memotong saldo** dan
            # sejenis ditaut; yang beda jenis atau yang statusnya belum
            # memotong apa pun dilewati dan dicatat berisik di log.
            clashing = EmployeeLeaveService.find_overlap(
                employee=request.employee,
                start=purpose.start_date,
                end=purpose.end_date,
            )

            if clashing is not None:
                if clashing.status not in LEAVE_DEDUCTING_STATUSES:
                    # `find_overlap` mencari lintas
                    # `LEAVE_BLOCKING_STATUSES`, jadi yang balik bisa
                    # saja masih SUBMITTED — sudah **memesan** tanggal,
                    # tapi belum memotong saldo apa pun
                    # (`LeaveBalanceService.recalculate_used` cuma
                    # menjumlahkan `LEAVE_DEDUCTING_STATUSES`).
                    #
                    # Menautkannya ke baris ini akan mencatat pekerjaan
                    # yang belum selesai sebagai pekerjaan yang sudah
                    # selesai: `employee_leave_id` terisi, jadi approve
                    # berikutnya melewati baris ini, dan kalau pengajuan
                    # cuti itu akhirnya ditolak TR-nya menunjuk catatan
                    # cuti yang tidak pernah terbit — saldo tidak
                    # terpotong dan tidak ada satu pun tanda di layar.
                    #
                    # Jadi: dilewati, tidak ditaut, dan berisik di log.
                    # Menolak bukan pilihan — di titik ini alurnya sudah
                    # disetujui.
                    logger.warning(
                        "TR %s: baris %s (%s–%s) bentrok dengan cuti %s "
                        "%s yang statusnya masih %s. Status itu belum "
                        "memotong saldo, jadi barisnya TIDAK ditaut dan "
                        "catatan cutinya TIDAK diterbitkan — selesaikan "
                        "dulu pengajuan cuti itu, lalu catat manual.",
                        request.document_number,
                        purpose.purpose.name,
                        purpose.start_date,
                        purpose.end_date,
                        clashing.leave_type.name,
                        clashing.document_number or clashing.pk,
                        clashing.status,
                    )
                elif clashing.leave_type_id == leave_type.pk:
                    purpose.employee_leave = clashing
                    purpose.updated_by = user

                    purpose.save(
                        update_fields=[
                            "employee_leave",
                            "updated_by",
                            "updated_at",
                        ],
                    )

                    logger.info(
                        "TR %s: baris %s ditaut ke catatan cuti yang "
                        "sudah ada (%s), bukan diterbitkan ulang.",
                        request.document_number,
                        purpose.purpose.name,
                        clashing.document_number or clashing.pk,
                    )
                else:
                    logger.warning(
                        "TR %s: baris %s (%s–%s) bentrok dengan %s %s "
                        "yang jenisnya berbeda. Catatan cuti TIDAK "
                        "diterbitkan supaya saldonya tidak terpotong "
                        "dua kali — periksa manual.",
                        request.document_number,
                        purpose.purpose.name,
                        purpose.start_date,
                        purpose.end_date,
                        clashing.leave_type.name,
                        clashing.document_number or clashing.pk,
                    )

                continue

            leave = EmployeeLeaveService.create(
                data={
                    "employee": request.employee,
                    "leave_type": leave_type,
                    "start_date": purpose.start_date,
                    "end_date": purpose.end_date,
                    # RECORDED, bukan APPROVED. `LeaveBalanceService.
                    # recalculate_used` hanya menjumlahkan cuti
                    # berstatus RECORDED — modul Cuti memang pencatatan,
                    # dan RECORDED berarti "benar-benar terjadi".
                    # Menerbitkannya sebagai APPROVED membuat catatannya
                    # ada tapi saldonya tidak pernah terpotong: gagal
                    # tanpa suara, dan baru ketahuan saat ada yang
                    # membandingkan kartu cuti dengan dokumen TR.
                    "status": LeaveStatus.RECORDED,
                    "notes": (
                        f"Diterbitkan otomatis dari "
                        f"{request.document_number or 'Travel Request'}."
                    ),
                },
                user=user,
            )

            purpose.employee_leave = leave
            # Terbit dari dokumen ini, bukan diadopsi — jadi ikut
            # dibatalkan kalau dokumennya dibatalkan. Baris yang ditaut
            # ke catatan cuti milik HR di atas sengaja tidak ditandai.
            purpose.leave_issued = True
            purpose.updated_by = user

            purpose.save(
                update_fields=[
                    "employee_leave",
                    "leave_issued",
                    "updated_by",
                    "updated_at",
                ],
            )

            cls._warn_when_policy_has_no_balance(
                request=request,
                purpose=purpose,
                leave=leave,
                evaluator=evaluator,
            )

            issued += 1

        return issued

    @staticmethod
    def _warn_when_policy_has_no_balance(
        *,
        request: TravelRequest,
        purpose: TravelRequestPurpose,
        leave,
        evaluator: LeaveRuleEvaluator,
    ) -> None:
        """
        `deducts_leave` menyala tapi aturan yang berlaku tidak bersaldo.

        Dua master yang mengatakan hal berbeda tentang cuti yang sama:
        `RotationPurpose.deducts_leave` bilang baris ini memotong,
        `LeavePolicy.uses_balance` bilang jenis cutinya memang tidak
        punya kartu saldo untuk dipotong. Yang benar **bukan** menolak
        pengajuannya — di titik ini alurnya sudah disetujui sampai meja
        terakhir, dan orang yang membaca penolakannya tidak punya cara
        memperbaiki master dari layar itu. Catatan cutinya tetap sah
        dan tetap terbit lewat `EmployeeLeaveService`; yang tidak
        terjadi cuma pemotongan saldo, karena memang tidak ada saldo.

        Penilaiannya memakai evaluator Leave yang sama dengan modul
        Cuti (`LeaveRuleEvaluator` lewat `evaluate_rules`) — Travel
        Request tidak boleh punya pembacaan policy sendiri.

        `uses_balance` bawaannya **True** saat aturannya belum dibuat
        sama sekali, jadi jenis cuti yang masternya belum diisi tidak
        ikut berbunyi di sini: yang dilaporkan hanya aturan yang
        benar-benar menyatakan dirinya tanpa saldo.
        """
        report = EmployeeLeaveService.evaluate_rules(
            instance=leave,
            evaluator=evaluator,
            # Riwayat dan kartu saldo tidak dipakai keputusan ini, dan
            # keduanya query tambahan per baris.
            with_history=False,
            with_balance=False,
        )

        if report.uses_balance:
            return

        logger.warning(
            "TR %s: baris %s ditandai memotong saldo (deducts_leave), "
            "tapi Leave Policy %s yang berlaku untuk Leave Type '%s' "
            "tidak memakai saldo (uses_balance=False). Catatan cuti %s "
            "tetap diterbitkan dan tetap sah, tapi tidak ada saldo yang "
            "berkurang — samakan master Travel Purpose dengan Leave "
            "Policy-nya.",
            request.document_number or request.pk,
            purpose.purpose.name,
            getattr(report.policy, "code", "-"),
            leave.leave_type.name,
            leave.document_number or leave.pk,
        )


class TravelRequestPurposeService(BaseMasterService):
    model = TravelRequestPurpose

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        # Penjagaan yang sama dengan update dan hapus. Dulu hanya dua
        # jalur itu yang memeriksanya, jadi baris **baru** masih bisa
        # ditambahkan ke dokumen yang sedang menunggu tanda tangan atau
        # sudah disetujui — dan isi yang ditandatangani berubah
        # sesudahnya. Melarang menyunting baris tapi membolehkan
        # menambah baris bukan setengah pagar, itu bukan pagar.
        cls.assert_parent_editable(data)
        cls.assert_purpose_allowed(data.get("purpose"))

        data = cls.apply_sequence(data)

        return cls.apply_total_days(data)

    @staticmethod
    def assert_parent_editable(data: dict[str, Any]) -> None:
        request = data.get("request")

        if request is not None:
            TravelRequestService.assert_editable(request)

    @staticmethod
    def assert_purpose_allowed(purpose) -> None:
        """
        Travel Request = kepulangan site (Field Break + cuti yang
        menumpang perjalanannya). Dinas Luar dan Training adalah tugas
        perusahaan — dokumennya Business Trip (TR-CLEANUP-1).

        Dipanggil di create dan saat alasannya **diganti**. Baris lama
        yang sudah menunjuk DUTY/TRAINING tetap bisa dibaca dan
        disunting kolom lainnya; yang menghentikannya `submit()`.
        """
        if purpose is None:
            return

        if not isinstance(purpose, RotationPurpose):
            purpose = RotationPurpose.objects.filter(pk=purpose).first()

        if purpose is not None and purpose.is_business_trip_domain:
            raise ValidationError(
                {
                    "purpose": (
                        f"'{purpose.name}' adalah tugas dinas perusahaan "
                        "dan diajukan lewat Business Trip, bukan Travel "
                        "Request."
                    ),
                },
            )

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        TravelRequestService.assert_editable(instance.request)

        # Baris tidak berpindah dokumen (TR-CLEANUP-2) — sama dengan
        # etape. Grid mengirim ulang id induknya di setiap baris.
        moved_to = data.get("request")

        if moved_to is not None and (
            getattr(moved_to, "pk", moved_to) != instance.request_id
        ):
            raise ValidationError(
                {
                    "request": (
                        "Baris Travel Purpose tidak bisa dipindah ke "
                        "Travel Request lain."
                    ),
                },
            )

        # Grid inline mengirim ulang seluruh isi baris, termasuk alasan
        # yang tidak disentuh — yang diperiksa hanya penggantiannya.
        purpose = data.get("purpose")

        if purpose is not None and (
            getattr(purpose, "pk", purpose) != instance.purpose_id
        ):
            cls.assert_purpose_allowed(purpose)

        data = cls.apply_sequence(data, instance=instance)

        return cls.apply_total_days(data, instance=instance)

    @staticmethod
    def apply_sequence(
        data: dict[str, Any],
        *,
        instance: TravelRequestPurpose | None = None,
    ) -> dict[str, Any]:
        if data.get("sequence") is not None:
            return data

        if instance is not None and instance.sequence:
            data["sequence"] = instance.sequence

            return data

        request = data.get(
            "request",
            getattr(instance, "request", None),
        )

        if request is None:
            return data

        last = (
            TravelRequestPurpose.objects
            .filter(request=request, is_deleted=False)
            .order_by("-sequence")
            .values_list("sequence", flat=True)
            .first()
        )

        data["sequence"] = (last or 0) + 1

        return data

    @staticmethod
    def apply_total_days(
        data: dict[str, Any],
        *,
        instance: TravelRequestPurpose | None = None,
    ) -> dict[str, Any]:
        # Isian manual dihormati: ada kasus yang tidak bisa disimpulkan
        # dari selisih tanggal, mis. setengah hari.
        if data.get("total_days") is not None:
            return data

        def resolved(field_name):
            if field_name in data:
                return data[field_name]

            return getattr(instance, field_name, None)

        start = resolved("start_date")
        end = resolved("end_date")

        if start and end and end >= start:
            data["total_days"] = (end - start).days + 1

        return data

    @classmethod
    def after_create(cls, *, instance, user=None, **kwargs):
        instance = super().after_create(
            instance=instance,
            user=user,
            **kwargs,
        )

        TravelRequestService.sync_totals(instance.request)

        return instance

    @classmethod
    def after_update(cls, *, instance, user=None, **kwargs):
        instance = super().after_update(
            instance=instance,
            user=user,
            **kwargs,
        )

        TravelRequestService.sync_totals(instance.request)

        return instance

    @classmethod
    @transaction.atomic
    def soft_delete(cls, *, instance, user=None, **kwargs):
        TravelRequestService.assert_editable(instance.request)

        instance = super().soft_delete(
            instance=instance,
            user=user,
            **kwargs,
        )

        TravelRequestService.sync_totals(instance.request)

        return instance


class TravelArrangementService(BaseMasterService):
    model = TravelArrangement

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        # Sama dengan baris Travel Purpose: etape baru tidak boleh
        # disisipkan ke dokumen yang sudah diajukan. Nomor tiket yang
        # muncul setelah KTT menandatangani adalah perubahan isi
        # dokumen, bukan pelengkapan.
        cls.assert_parent_editable(data)

        data = cls.apply_departure_from_stay(data)
        data = cls.apply_counts_as_work(data)
        data = cls.apply_sequence(data)

        return cls.apply_accommodation(data)

    @staticmethod
    def apply_departure_from_stay(data: dict[str, Any]) -> dict[str, Any]:
        """
        Baris yang ditambahkan dari tab Accommodation (TR-CLEANUP-1).

        Akomodasi bukan tabel sendiri — ia kolom pada etape yang
        menginap di ujungnya ("semalam di Ternate"). Tab itu tidak
        menampilkan Departure Date, jadi etape barunya berangkat pada
        hari check-in: hari orangnya tiba di kota transit. Tetap tampil
        dan bisa dikoreksi di tab Travel Arrangement — bukan baris
        tersembunyi.
        """
        if data.get("travel_start_date"):
            return data

        if data.get("accommodation_checkin"):
            data["travel_start_date"] = data["accommodation_checkin"]

            return data

        raise ValidationError(
            {
                "travel_start_date": (
                    "Isi Departure Date di Travel Arrangement, atau "
                    "Check-in kalau barisnya ditambahkan dari tab "
                    "Accommodation."
                ),
            },
        )

    @staticmethod
    def assert_parent_editable(data: dict[str, Any]) -> None:
        request = data.get("request")

        if request is not None:
            TravelRequestService.assert_editable(request)

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        TravelRequestService.assert_editable(instance.request)

        # Etape tidak berpindah dokumen. Grid mengirim ulang id induknya
        # di setiap baris; yang beda berarti baris ini dipindah ke TR
        # lain — melewati pagar editable dan cakupan dokumen tujuannya.
        moved_to = data.get("request")

        if moved_to is not None and (
            getattr(moved_to, "pk", moved_to) != instance.request_id
        ):
            raise ValidationError(
                {
                    "request": (
                        "Baris perjalanan/akomodasi tidak bisa dipindah "
                        "ke Travel Request lain."
                    ),
                },
            )

        data = cls.apply_sequence(data, instance=instance)

        return cls.apply_accommodation(data, instance=instance)

    @staticmethod
    def apply_sequence(
        data: dict[str, Any],
        *,
        instance: TravelArrangement | None = None,
    ) -> dict[str, Any]:
        """
        Nomor etape berikutnya **di dalam arahnya**.

        Dihitung per arah, bukan per dokumen: keberangkatan dan
        kepulangan masing-masing punya deret sendiri, jadi rute pulang
        dua etape tetap bernomor 1 dan 2 walau keberangkatannya sudah
        memakai nomor itu.
        """
        if data.get("sequence") is not None:
            return data

        if instance is not None and instance.sequence:
            data["sequence"] = instance.sequence

            return data

        request = data.get(
            "request",
            getattr(instance, "request", None),
        )

        direction = data.get(
            "direction",
            getattr(instance, "direction", None),
        )

        if request is None or not direction:
            return data

        last = (
            TravelArrangement.objects
            .filter(
                request=request,
                direction=direction,
                is_deleted=False,
            )
            .exclude(pk=getattr(instance, "pk", None))
            .order_by("-sequence")
            .values_list("sequence", flat=True)
            .first()
        )

        data["sequence"] = (last or 0) + 1

        return data

    @staticmethod
    def apply_counts_as_work(data: dict[str, Any]) -> dict[str, Any]:
        """
        Perjalanan kembali ke site dihitung hari kerja; kepulangan
        tidak, karena hari itu sudah masuk blok off-nya.

        Hanya bawaan — nilai yang dikirim eksplisit dihormati, sebab
        kapal pulang yang delay dua hari juga masih tanggungan
        perusahaan dan itu tidak bisa disimpulkan dari arahnya saja.
        """
        if "counts_as_work" in data:
            return data

        direction = data.get("direction")

        if direction:
            data["counts_as_work"] = (
                direction == TravelDirection.INBOUND
            )

        return data

    @staticmethod
    def apply_accommodation(
        data: dict[str, Any],
        *,
        instance: TravelArrangement | None = None,
    ) -> dict[str, Any]:
        def resolved(field_name):
            if field_name in data:
                return data[field_name]

            return getattr(instance, field_name, None)

        checkin = resolved("accommodation_checkin")
        checkout = resolved("accommodation_checkout")

        filled = any(
            resolved(field_name)
            for field_name in (
                "accommodation_type",
                "accommodation_name",
                "accommodation_checkin",
                "accommodation_checkout",
            )
        )

        # Turunan dua arah. Dulu hanya menyala, tidak pernah padam:
        # mengosongkan hotel di tab Accommodation tetap membawa
        # `accommodation_needed=True` dari baris lamanya, lalu `clean()`
        # menuntut check-in/out yang baru dikosongkan — akomodasi tidak
        # bisa dibatalkan dari layarnya sendiri. Penanda tanpa isian
        # memang tidak pernah sah (`clean()` menolaknya), jadi padam di
        # sini tidak membuang keadaan sah apa pun.
        if filled != bool(resolved("accommodation_needed")):
            data["accommodation_needed"] = filled

        if data.get("accommodation_nights") is None:
            if checkin and checkout and checkout >= checkin:
                data["accommodation_nights"] = (checkout - checkin).days
            elif "accommodation_nights" not in data:
                data["accommodation_nights"] = None

        return data

    @classmethod
    @transaction.atomic
    def soft_delete(cls, *, instance, user=None, **kwargs):
        TravelRequestService.assert_editable(instance.request)

        return super().soft_delete(
            instance=instance,
            user=user,
            **kwargs,
        )
