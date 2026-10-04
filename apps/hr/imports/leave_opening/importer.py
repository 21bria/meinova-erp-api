"""
Import saldo cuti awal dari sistem lama.

Satu baris file = satu titik awal untuk satu pegawai pada satu jenis
cuti. Yang **tidak** diimport: histori pemakaian cuti tahun-tahun
sebelumnya — itu memang tidak lengkap di sistem lama, dan mengarangnya
menghasilkan data yang tidak bisa dipertanggungjawabkan siapa pun.

Seluruh penolakan ditulis di `resolve()`, bukan dibiarkan jatuh di
`write()`. Bedanya besar: yang di `resolve()` muncul di layar preview
sebelum satu baris pun ditulis, lengkap dengan nomor barisnya; yang
jatuh di `write()` baru terbaca setelah job selesai, di laporan error
yang harus dibuka sendiri.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.administration.models import LeaveType
from apps.framework.imports import BaseImporter, register_importer
from apps.hr.api.leave.eligibility import (
    LeaveEligibilityResolver,
    OpeningValidation,
)
from apps.hr.api.leave.go_live import LeaveGoLiveResolver
from apps.hr.api.leave_opening.services import LeaveOpeningBalanceService
from apps.hr.imports.services.matcher import AttendanceEmployeeMatcher
from apps.hr.models import (
    Employee,
    LeaveOpeningBalance,
    LeaveOpeningSource,
    LeaveOpeningStatus,
)


# Header file di-`strip().lower()` parser, **tanpa** mengubah spasi jadi
# garis bawah. Jadi "Employee Code" mendarat sebagai "employee code" dan
# tidak cocok dengan alias "employee_code" — dua bentuk itu harus
# dua-duanya ditulis. Ini gagal tanpa suara: kolomnya cuma terbaca
# kosong, lalu barisnya ditolak sebagai "employee_code is required"
# padahal isinya ada.
LEAVE_OPENING_IMPORT_MAPPING: dict[str, list[str]] = {
    "employee_code": [
        "employee_code",
        "employee code",
        "employee_number",
        "employee number",
        "employee_no",
        "employee no",
        "nomor_pegawai",
        "nomor pegawai",
        "nik_karyawan",
        "nip",
    ],
    # Nama pegawai **tidak** menentukan barisnya mendarat di siapa —
    # pencocokan tetap murni lewat `employee_code`, sama seperti sync
    # absensi. Ia dipetakan supaya bisa dibandingkan dan diperingatkan;
    # kolom template yang tidak dikenal importer akan diisi orang lalu
    # diabaikan tanpa satu pun tanda, dan itu justru kolom yang paling
    # dipercaya pembaca filenya.
    "employee_name": [
        "employee_name",
        "employee name",
        "nama_pegawai",
        "nama pegawai",
        "nama_karyawan",
        "nama karyawan",
        "nama",
    ],
    "leave_type": [
        "leave_type",
        "leave type",
        "leave_type_code",
        "leave type code",
        "jenis_cuti",
        "jenis cuti",
        "tipe_cuti",
    ],
    "opening_date": [
        "opening_date",
        "opening date",
        "effective_date",
        "effective date",
        "tanggal_berlaku",
        "tanggal berlaku",
        "tanggal",
    ],
    "days": [
        "opening_balance",
        "opening balance",
        "days",
        "balance",
        "saldo_awal",
        "saldo awal",
        "saldo",
    ],
    "remark": [
        "remark",
        "remarks",
        "keterangan",
        "catatan",
        "note",
        "notes",
    ],
    # Dua kolom opsional, untuk klien yang memang sudah memegang
    # angkanya. Dikosongkan = diturunkan service dari tanggal berlaku
    # dan Leave Policy.
    "year": [
        "year",
        "balance_year",
        "balance year",
        "tahun",
    ],
    "expires_at": [
        "expires_at",
        "expires at",
        "expiry_date",
        "expiry date",
        "expired_date",
        "tanggal_hangus",
        "tanggal hangus",
    ],
}


@register_importer
class LeaveOpeningBalanceImporter(BaseImporter):
    module = "hr/leave-opening-balances"
    label = "Leave Opening Balance"

    source_types = ("csv",)

    mapping = LEAVE_OPENING_IMPORT_MAPPING

    # `opening_date` **tidak** wajib: kalau perusahaan pegawainya sudah
    # punya tanggal go-live, itulah tanggalnya, dan mengetik ulang
    # tanggal yang sama di tiga ratus baris cuma menambah tiga ratus
    # kesempatan salah ketik. Baris yang perusahaannya belum punya
    # go-live tetap ditolak di `resolve()` dengan pesan yang menyebut
    # jalan keluarnya.
    required_fields = (
        "employee_code",
        "leave_type",
        "days",
    )

    identity_field = "employee_code"

    date_fields = (
        "opening_date",
        "expires_at",
    )

    # Urutannya urutan orang mengisinya: siapa, cuti apa, per kapan,
    # berapa, kenapa. `employee_name` duduk tepat di sebelah kodenya
    # supaya salah nomor terlihat saat filenya masih disunting — bukan
    # setelah tujuh hari cuti menempel di kartu orang lain.
    #
    # Tidak ada kolom penanda apa pun, dan itu inti bentuk ini:
    # `opening_balance` **selalu** berarti saldo aktual pegawai pada
    # tanggal go-live. Yang mengisi file tidak perlu memutuskan arti
    # angkanya per orang, dan jatah tahun go-live memang tidak
    # diterbitkan sistem ini — jadi tidak ada apa pun untuk ditumpuki.
    template_columns = (
        "employee_code",
        "employee_name",
        "leave_type",
        "opening_date",
        "opening_balance",
        "remark",
    )

    # Dua baris contoh, dan bedanya bukan hiasan: yang pertama memakai
    # kode jenis cuti, yang kedua namanya — keduanya diterima, dan yang
    # mengisi file perlu tahu itu sebelum menerjemahkan 300 baris.
    template_sample_rows = (
        {
            "employee_code": "EMP001",
            "employee_name": "Budi Santoso",
            "leave_type": "ANNUAL",
            "opening_date": "2026-08-19",
            "opening_balance": "7",
            "remark": "Sisa cuti tahunan per tanggal go-live",
        },
        {
            "employee_code": "EMP002",
            "employee_name": "Siti Rahayu",
            "leave_type": "Cuti Tahunan",
            "opening_date": "",
            "opening_balance": "10",
            "remark": "Tanggal dikosongkan = ikut go-live perusahaannya",
        },
    )

    # Join Date dan Eligible Date ada di sini karena **itu** yang
    # dipakai HR memeriksa saldo dari sistem lama. Angkanya sendiri tidak
    # bisa diperiksa sistem ini — histori pemakaiannya tidak pernah ikut
    # pindah — jadi satu-satunya pemeriksaan yang mungkin adalah
    # kelayakannya: orang yang baru masuk November 2025 tidak mungkin
    # punya sisa cuti pada Agustus 2026. Tanpa dua kolom itu, kolom
    # Validation berbunyi REVIEW tanpa ada bahan untuk menilainya, dan
    # yang membacanya harus membuka kartu pegawai satu per satu.
    preview_columns = (
        {"key": "row_number", "label": "Row"},
        {"key": "employee_code", "label": "Employee Code"},
        {"key": "employee_name", "label": "Employee"},
        {"key": "leave_type", "label": "Leave Type"},
        {"key": "join_date", "label": "Join Date"},
        {"key": "eligible_date", "label": "Eligible Date"},
        {"key": "opening_date", "label": "Opening Date"},
        {"key": "days", "label": "Opening Balance"},
        {"key": "validation", "label": "Validation"},
        {"key": "remark", "label": "Remark"},
        {"key": "reason", "label": "Reason"},
    )

    # ------------------------------------------------------------------
    # Resolusi
    # ------------------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        normalized: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        resolved: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}
        warnings: list[str] = []

        def fail(field_name: str, message: str) -> None:
            errors.setdefault(field_name, []).append(message)

        employee = cls._find_employee(normalized.get("employee_code"))

        if employee is None:
            fail(
                "employee_code",
                f"Pegawai '{normalized.get('employee_code')}' tidak "
                f"ditemukan.",
            )
        else:
            resolved["employee"] = employee

        leave_type = cls._find_leave_type(normalized.get("leave_type"))

        if leave_type is None:
            fail(
                "leave_type",
                f"Jenis cuti '{normalized.get('leave_type')}' tidak "
                f"ada di master.",
            )
        else:
            resolved["leave_type"] = leave_type

        # Nama yang jelas orang lain diperingatkan, tidak ditolak:
        # ejaan di file klien memang berbeda-beda (disingkat, tanpa
        # gelar, nama panggilan), dan `names_match` sudah longgar —
        # yang lolos ke sini bukan selisih ejaan. Barisnya pun berhenti
        # di DRAFT, jadi masih ada langkah Review sebelum angkanya
        # menempel di kartu siapa pun. Pola yang sama dengan sync
        # absensi: nama dipakai sebagai alarm, bukan gerbang.
        file_name = str(normalized.get("employee_name") or "").strip()

        if employee is not None and file_name:
            if not AttendanceEmployeeMatcher.names_match(
                file_name,
                employee,
            ):
                warnings.append(
                    f"Nama di file '{file_name}' tidak cocok dengan "
                    f"{employee.employee_number} "
                    f"({employee.full_name}) — periksa nomornya.",
                )

        raw_date = normalized.get("opening_date")

        go_live = (
            LeaveGoLiveResolver.for_employee(employee)
            if employee is not None
            else None
        )

        if raw_date in (None, ""):
            # Dikosongkan = ikut tanggal go-live perusahaannya. Ini
            # jalur yang lazim: satu batch migrasi menyatakan keadaan
            # per satu tanggal, dan tanggal itu sudah ditetapkan di
            # langkah pertama.
            if go_live is not None:
                opening_date = go_live.go_live_date
                resolved["opening_date"] = opening_date
            else:
                opening_date = None

                fail(
                    "opening_date",
                    "Kolom tanggal kosong dan perusahaan pegawai ini "
                    "belum punya tanggal go-live cuti. Isi Leave "
                    "Go-Live dulu, atau tulis tanggalnya di file.",
                )
        else:
            opening_date = cls._to_date(raw_date)

            if opening_date is None:
                fail(
                    "opening_date",
                    f"Tanggal '{raw_date}' tidak bisa dibaca. Pakai "
                    f"format YYYY-MM-DD, atau isi datetime_formats di "
                    f"Import Profile.",
                )
            else:
                resolved["opening_date"] = opening_date

                # Tanggal yang menyimpang dari go-live diterima, tapi
                # disebut — bukan ditolak: perusahaan yang menyerahkan
                # datanya bertahap memang punya baris bertanggal lain,
                # dan menolaknya menghentikan migrasi yang sah. Yang
                # tidak boleh adalah selisih yang lewat tanpa ada yang
                # menyadarinya, karena tanggal inilah yang menentukan
                # kartu tahun mana yang menerima angkanya.
                if (
                    go_live is not None
                    and opening_date != go_live.go_live_date
                ):
                    warnings.append(
                        f"Tanggal {opening_date} berbeda dari go-live "
                        f"perusahaannya ({go_live.go_live_date}).",
                    )

        expires_raw = normalized.get("expires_at")

        if expires_raw not in (None, ""):
            expires_at = cls._to_date(expires_raw)

            if expires_at is None:
                fail(
                    "expires_at",
                    f"Tanggal hangus '{expires_raw}' tidak bisa dibaca.",
                )
            else:
                resolved["expires_at"] = expires_at

        days = cls._to_decimal(normalized.get("days"))

        if days is None:
            fail(
                "days",
                f"Saldo '{normalized.get('days')}' bukan angka.",
            )
        elif days < 0:
            fail(
                "days",
                "Saldo awal tidak boleh negatif. Untuk koreksi "
                "pengurangan, pakai Adjustment di kartu saldo.",
            )
        else:
            resolved["days"] = days

        year_raw = normalized.get("year")

        if year_raw not in (None, ""):
            try:
                resolved["year"] = int(str(year_raw).strip())
            except (TypeError, ValueError):
                fail("year", f"Tahun '{year_raw}' bukan angka.")

        # Saldo awal hanya untuk migrasi: satu kali per pegawai per
        # jenis cuti. Ditolak di preview, bukan ditimpa — menimpanya
        # akan membuat file yang tidak sengaja diimport dua kali
        # mengubah saldo orang tanpa ada yang menyadarinya.
        if employee is not None and leave_type is not None:
            existing = (
                LeaveOpeningBalance.objects
                .filter(
                    employee=employee,
                    leave_type=leave_type,
                    is_deleted=False,
                )
                .first()
            )

            if existing is not None:
                fail(
                    "employee_code",
                    f"Sudah punya saldo awal {existing.days} hari untuk "
                    f"jenis cuti ini (berlaku {existing.opening_date}).",
                )

        # Tanggal berlaku sebelum orangnya masuk kerja selalu salah
        # ketik, dan salahnya tidak terlihat lagi begitu barisnya
        # tersimpan: angkanya benar, tanggalnya yang mustahil.
        if employee is not None and opening_date is not None:
            employment = getattr(employee, "employment", None)
            join_date = getattr(employment, "join_date", None)

            if join_date and opening_date < join_date:
                fail(
                    "opening_date",
                    f"Lebih awal dari Join Date pegawai ({join_date}).",
                )

        # Kelayakan dinilai terakhir: ia butuh keempat nilai di atas
        # sudah selesai dibaca. Hasilnya **tidak pernah** menambah
        # `errors` — baris yang saldonya mendahului tanggal berhaknya
        # tetap boleh masuk, dan itu keputusan desain, bukan kelalaian:
        # yang dipegang klien bisa jadi memang benar (perusahaan lamanya
        # memberi cuti lebih awal), dan satu-satunya yang bisa menjawab
        # itu HR yang memegang berkas migrasinya. Menolaknya berarti
        # migrasi berhenti; mengubahnya jadi nol berarti membuang angka
        # yang cuma dipegang satu pihak.
        #
        # Resolver dibuat per baris, jadi memo di dalamnya tidak terpakai
        # di sini — pipeline memanggil `resolve()` sebagai classmethod
        # tanpa keadaan per file. Satu query policy per baris, sejajar
        # dengan empat query yang sudah dilakukannya (pegawai, jenis
        # cuti, go-live, duplikat). Memonya baru bekerja di serializer
        # daftar, yang memang memegang satu instance per halaman.
        eligibility = LeaveEligibilityResolver().for_employee(
            employee,
            leave_type,
        )

        status, reason = LeaveEligibilityResolver.classify(
            days=resolved.get("days"),
            eligibility=eligibility,
            opening_date=opening_date,
        )

        resolved["_eligibility"] = eligibility

        # Jenis cuti yang aturannya bukan aturan bersaldo tidak punya
        # kartu untuk diisi. Ditolak di sini — di `resolve()` — supaya
        # penolakannya muncul di layar preview lengkap dengan nomor
        # barisnya; yang jatuh belakangan di `write()` baru terbaca
        # setelah job selesai, dan saat itu orangnya sudah menekan
        # Confirm.
        #
        # Policy-nya dibaca dari hasil kelayakan di atas, bukan
        # di-resolve lagi: dua pencarian untuk aturan yang sama adalah
        # satu query per baris yang tidak menambah apa-apa.
        if (
            eligibility.policy is not None
            and not eligibility.policy.uses_balance
        ):
            fail(
                "leave_type",
                f"{leave_type.name} bukan cuti bersaldo menurut "
                f"{eligibility.policy.code} — haknya diperiksa saat "
                f"pengajuan, jadi tidak ada saldo awal yang bisa "
                f"dimasukkan.",
            )

        # Baris yang ditolak pipeline tidak diberi status kelayakan:
        # "VALID" di sebelah baris yang tidak bisa diimport adalah dua
        # pesan yang saling membatalkan, dan yang membacanya akan
        # menyimpulkan salah satunya bohong.
        resolved["_validation"] = (
            OpeningValidation.ERROR if errors else status
        )

        resolved["_validation_reason"] = "" if errors else reason

        if warnings:
            resolved["_warnings"] = warnings

        return resolved, errors

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    @classmethod
    def build_preview_row(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
    ) -> dict[str, Any]:
        employee = resolved.get("employee")
        eligibility = resolved.get("_eligibility")

        return {
            "employee_code": normalized.get("employee_code"),
            # Nama dari master kalau pegawainya ketemu — itu yang harus
            # dibaca pemeriksa preview, bukan nama yang diketik di file.
            # Untuk baris yang ditolak karena nomornya tidak ada,
            # nama di file yang dipakai: baris tanpa nama sama sekali
            # tidak bisa dicari lagi di file aslinya.
            "employee_name": (
                employee.full_name
                if employee is not None
                else (normalized.get("employee_name") or "")
            ),
            "leave_type": normalized.get("leave_type"),
            # Yang ditampilkan hasil resolusi, bukan isi selnya: baris
            # yang tanggalnya dikosongkan mengambil tanggal go-live, dan
            # kolom preview yang kosong akan terbaca seperti data yang
            # gagal dibaca.
            "opening_date": (
                resolved.get("opening_date")
                or normalized.get("opening_date")
            ),
            "days": normalized.get("days"),
            "join_date": getattr(eligibility, "join_date", None),
            "eligible_date": getattr(eligibility, "eligible_date", None),
            "validation": OpeningValidation.label(
                resolved.get("_validation", OpeningValidation.ERROR),
            ),
            "remark": normalized.get("remark"),
            # Satu kolom prosa untuk semuanya — alasan status
            # kelayakan **dan** peringatan (nama tidak cocok, tanggal
            # berbeda dari go-live). Dua kolom keterangan yang harus
            # dibaca bergantian membuat yang kedua tidak pernah dibaca.
            # Pipeline import tidak punya kanal warning tersendiri: yang
            # tidak tampil di layar preview sama saja dengan tidak ada.
            "reason": "; ".join(
                message
                for message in [
                    resolved.get("_validation_reason", ""),
                    *resolved.get("_warnings", []),
                ]
                if message
            ),
        }

    # ------------------------------------------------------------------
    # Penulisan
    # ------------------------------------------------------------------

    @classmethod
    def write(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ) -> tuple[Any, bool]:
        employee = resolved["employee"]
        leave_type = resolved["leave_type"]

        # Dua baris untuk pasangan yang sama di dalam **satu file**
        # lolos `resolve()` — saat preview dijalankan, belum satu pun
        # tertulis. Ditangkap di sini supaya pesannya tetap menyebut
        # sebabnya, bukan nama constraint database.
        duplicate = (
            LeaveOpeningBalance.objects
            .filter(
                employee=employee,
                leave_type=leave_type,
                is_deleted=False,
            )
            .exists()
        )

        if duplicate:
            raise ValueError(
                f"{employee.employee_number} sudah punya saldo awal "
                f"untuk {leave_type.code} — baris ini duplikat di "
                f"dalam file yang sama.",
            )

        data = {
            "employee": employee,
            "leave_type": leave_type,
            "opening_date": resolved["opening_date"],
            "days": resolved["days"],
            "remark": normalized.get("remark") or "",
            "source": LeaveOpeningSource.IMPORT,
            # Import berhenti di draft, selalu. Ratusan baris yang
            # angkanya datang dari luar sistem ini tidak boleh langsung
            # menempel di kartu cuti orang sebelum ada satu pun yang
            # membacanya — itu langkah Review, dan langkah itu cuma
            # punya arti kalau barisnya memang belum berlaku.
            "status": LeaveOpeningStatus.DRAFT,
        }

        if resolved.get("year"):
            data["year"] = resolved["year"]

        if resolved.get("expires_at"):
            data["expires_at"] = resolved["expires_at"]

        # Lewat service, bukan `objects.create`: penurunan tahun,
        # pembekuan tanggal hangus, sinkronisasi kartu saldo, dan jejak
        # audit semuanya ada di sana.
        instance = LeaveOpeningBalanceService.create(
            data=data,
            user=user,
        )

        return instance, True

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _find_employee(code: Any):
        code = str(code or "").strip()

        if not code:
            return None

        return (
            Employee.objects
            # `organization` ikut karena `LeavePolicyResolver` membaca
            # company-nya untuk memilih aturan yang berlaku. Tanpa itu,
            # tiap baris menambah satu query yang tidak terlihat di kode
            # importer ini sama sekali.
            .select_related("employment", "organization")
            .filter(
                employee_number__iexact=code,
                is_deleted=False,
            )
            .first()
        )

    @staticmethod
    def _find_leave_type(value: Any):
        value = str(value or "").strip()

        if not value:
            return None

        queryset = LeaveType.objects.filter(is_deleted=False)

        # Kode lebih dulu: itu yang stabil. Nama ikut diterima karena
        # file klien lazim menulis "Cuti Tahunan", bukan "ANNUAL".
        return (
            queryset.filter(code__iexact=value).first()
            or queryset.filter(name__iexact=value).first()
        )

    @staticmethod
    def _to_date(value: Any) -> date | None:
        if isinstance(value, date):
            return value

        value = str(value or "").strip()

        if not value:
            return None

        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value in (None, ""):
            return None

        text = str(value).strip().replace(",", ".")

        try:
            return Decimal(text)
        except (InvalidOperation, TypeError, ValueError):
            return None
