"""
Menerjemahkan `LeavePolicy` jadi angka di `LeaveBalance`.

Dipisah dari `EmployeeLeaveService` karena arahnya berlawanan: service
itu menghitung **pemakaian** dari catatan cuti, yang di sini menghitung
**jatah** dari aturan. Keduanya bertemu di satu baris `LeaveBalance`
tanpa saling menimpa — `entitlement` dan `carried_over` milik yang ini,
`used` milik yang itu, dan `adjustment` milik manusia.

Kolom `adjustment` itu yang membuat perhitungan ulang aman dijalankan
kapan saja: koreksi manual ("Ahmad dapat tambahan 3 hari karena lembur
Lebaran") tidak pernah ikut tertimpa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.administration.models import LeavePolicy
from apps.administration.models.references.leave_policy import (
    LeaveAccrual,
    LeavePeriodBasis,
)
from apps.hr.api.leave.go_live import LeaveGoLiveResolver
from apps.hr.models import LeaveBalance


def add_months(value: date, months: int) -> date:
    """
    Menambah bulan tanpa dependensi luar.

    Tanggal yang tidak ada di bulan tujuan (31 Januari + 1 bulan)
    dipotong ke hari terakhir bulan itu — perilaku yang sama dengan
    hampir semua sistem HR, dan satu-satunya yang tidak melompati
    bulan.
    """
    month_index = value.month - 1 + months

    year = value.year + month_index // 12
    month = month_index % 12 + 1

    day = min(value.day, _days_in_month(year, month))

    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31

    return (date(year, month + 1, 1) - date(year, month, 1)).days


@dataclass(frozen=True)
class Entitlement:
    """Hasil perhitungan untuk satu pegawai, satu jenis cuti, satu tahun."""

    days: Decimal
    policy: LeavePolicy | None
    reason: str

    # Nol karena tahun itu memang dipegang sistem lama, bukan karena
    # masa tunggunya belum lewat. Dibawa sebagai penanda, bukan
    # disimpulkan dari teks `reason` — pesan itu ditulis untuk dibaca
    # orang dan akan diubah kalimatnya cepat atau lambat, dan kode yang
    # mencocokkan substring di dalamnya akan diam-diam berhenti bekerja.
    from_opening: bool = False

    # Aturannya memang ada, tapi ia bukan aturan bersaldo — cuti
    # menikah, melahirkan, duka. Tidak ada baris `LeaveBalance` yang
    # boleh terbit dari sini.
    #
    # Penanda tersendiri, bukan disimpulkan dari `days == 0`: nol yang
    # benar-benar nol (masa tunggu belum lewat) tetap harus menerbitkan
    # kartunya, karena tahun depan angkanya berubah dan kartu itu yang
    # menampung perubahannya. Menyamakan keduanya berarti pegawai baru
    # kehilangan kartu cuti tahunannya sampai ada yang menjalankan
    # generate lagi.
    issues_balance: bool = True

    @property
    def has_policy(self) -> bool:
        return self.policy is not None


class LeavePolicyResolver:
    """
    Mencari aturan yang berlaku untuk satu pegawai.

    Berjenjang dari yang paling khusus: aturan bercompany mengalahkan
    yang global, yang menyebut Employee Group mengalahkan yang tidak.
    Dipilih lewat skor `specificity`, bukan urutan baris — jatah cuti
    seseorang tidak boleh bergantung pada nomor id di database.
    """

    @staticmethod
    def resolve(*, employee, leave_type) -> LeavePolicy | None:
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        company_id = getattr(organization, "company_id", None)
        group_id = getattr(employment, "employee_group_id", None)
        type_id = getattr(employment, "employment_type_id", None)

        candidates = (
            LeavePolicy.objects
            .filter(
                leave_type=leave_type,
                is_deleted=False,
                is_active=True,
            )
            .select_related("leave_type")
        )

        matched = []

        for policy in candidates:
            # Aturan yang menyebut sasaran tertentu hanya berlaku kalau
            # pegawainya memang sasaran itu. Yang mengosongkannya
            # berlaku untuk semua — itu arti "kosong = semua", bukan
            # "kosong = tidak berlaku".
            if policy.company_id and policy.company_id != company_id:
                continue

            if (
                policy.employee_group_id
                and policy.employee_group_id != group_id
            ):
                continue

            if (
                policy.employment_type_id
                and policy.employment_type_id != type_id
            ):
                continue

            matched.append(policy)

        if not matched:
            return None

        matched.sort(
            key=lambda policy: (policy.specificity, policy.pk),
            reverse=True,
        )

        return matched[0]


class LeaveEntitlementCalculator:
    @classmethod
    def for_employee(
        cls,
        *,
        employee,
        leave_type,
        year: int,
        opening_balances: dict | None = None,
        go_live_map: dict | None = None,
    ) -> Entitlement:
        """
        Jatah pegawai ini untuk satu jenis cuti pada satu tahun.

        Nol yang dikembalikan selalu punya alasan yang bisa dibaca —
        belum genap masa tunggu, belum masuk kerja, aturannya memang
        belum dibuat, atau jatahnya sudah termasuk di saldo awal
        migrasi. Saldo nol tanpa penjelasan adalah keluhan yang paling
        sering sampai ke HR.

        `opening_balances` adalah peta
        `{(employee_id, leave_type_id): LeaveOpeningBalance}` hasil
        **satu** query di pemanggil, dipakai `LeaveBalanceGenerator`
        yang memutar ribuan pasangan. Dikosongkan = di-resolve sendiri,
        satu query per pemanggilan — benar untuk pemakaian satuan,
        mahal untuk perulangan.
        """
        policy = LeavePolicyResolver.resolve(
            employee=employee,
            leave_type=leave_type,
        )

        employment = getattr(employee, "employment", None)

        # Gerbang pertama, dan ia di atas segalanya termasuk go-live:
        # aturan yang tidak bersaldo tidak pernah menerbitkan angka ke
        # kartu siapa pun, tahun berapa pun, di tenant yang bermigrasi
        # maupun yang mulai dari nol.
        #
        # Batasnya dibaca dari policy, **bukan** dari kode jenis
        # cutinya. `if leave_type.code == "MARRIAGE"` akan salah di
        # tenant yang memberi cuti menikah berbentuk saldo, dan
        # salahnya tidak bisa diperbaiki dari layar mana pun — yang
        # mengubah aturannya harus menunggu rilis kode.
        if policy is not None and not policy.uses_balance:
            return Entitlement(
                days=Decimal("0"),
                policy=policy,
                reason=(
                    f"{policy.code} bukan cuti bersaldo — haknya "
                    f"diperiksa saat pengajuan, bukan diterbitkan "
                    f"sebagai jatah tahunan."
                ),
                issues_balance=False,
            )

        # Gerbang go-live, dan ia diperiksa **paling awal** — sebelum
        # masa tunggu, sebelum prorata, bahkan sebelum penanda per
        # dokumen di bawahnya.
        #
        # Untuk perusahaan yang sudah berjalan sebelum sistem ini
        # dipakai, jatah tahun go-live BUKAN milik sistem ini untuk
        # diterbitkan: sebagian sudah dipakai di sistem lama, dan yang
        # tersisa persis angka yang diserahkan HR lewat Leave Opening
        # Balance. Menerbitkannya di sini lalu menambahkan saldo awal
        # di atasnya menghasilkan kartu berbunyi 19 untuk orang yang
        # sisanya 7 — dan tidak ada satu pun baris di layar yang
        # memberi tahu bahwa lima hari yang sudah dipakai tahun ini
        # tidak pernah ikut masuk.
        #
        # Perusahaan tanpa baris go-live tidak lewat sini sama sekali,
        # jadi tenant yang memang mulai dari nol tidak berubah
        # perilakunya.
        go_live = LeaveGoLiveResolver.for_employee(
            employee,
            go_live_map=go_live_map,
        )

        if LeaveGoLiveResolver.owns_year(
            go_live,
            year=year,
            join_date=getattr(employment, "join_date", None),
        ):
            return Entitlement(
                days=Decimal("0"),
                policy=policy,
                reason=(
                    f"Cuti {year} dipegang sistem lama — go-live "
                    f"{go_live.go_live_date}. Saldonya masuk lewat "
                    f"Leave Opening Balance, bukan dihitung dari policy."
                ),
                from_opening=True,
            )

        # Diperiksa **sebelum** masa tunggu dan prorata: kalau tahun itu
        # sudah punya saldo awal yang di-post, seluruh perhitungan di
        # bawah tidak berlaku lagi untuknya. Tetap sesudah policy,
        # supaya kartunya tetap menyebut aturan mana yang dipakainya
        # tahun depan.
        #
        # Gerbang kedua di samping `LeaveGoLive` di atas, dan keduanya
        # memang perlu: yang di atas menjawab "perusahaan ini bermigrasi
        # per tanggal X" untuk **semua** pegawainya termasuk yang tidak
        # punya baris saldo awal, yang di sini menjawab "orang ini sudah
        # punya titik awal yang di-post" walau perusahaannya belum
        # sempat mengisi tanggal go-live-nya. Tanpa yang kedua, tenant
        # yang mengimpor saldo awal tanpa menyetel Leave Go-Live lebih
        # dulu mendapat kartu berbunyi 19 untuk orang yang sisanya 7 —
        # dan tidak ada satu pun baris di layar yang menyebutkannya.
        replaced = cls.replaced_by_opening(
            employee=employee,
            leave_type=leave_type,
            year=year,
            opening_balances=opening_balances,
        )

        if replaced is not None:
            return Entitlement(
                days=Decimal("0"),
                policy=policy,
                reason=(
                    f"Cuti {year} datang dari saldo awal go-live "
                    f"({replaced.days} hari per {replaced.opening_date}), "
                    f"bukan dihitung dari policy."
                ),
                from_opening=True,
            )

        if policy is None:
            return Entitlement(
                days=Decimal("0"),
                policy=None,
                reason=(
                    f"Belum ada Leave Policy untuk {leave_type.code}."
                ),
            )

        join_date = getattr(employment, "join_date", None)

        if join_date is None:
            return Entitlement(
                days=Decimal("0"),
                policy=policy,
                reason=(
                    "Join Date pegawai belum diisi, jadi masa tunggu "
                    "tidak bisa dihitung."
                ),
            )

        eligible_from = add_months(
            join_date,
            policy.eligible_after_months,
        )

        period_start, period_end = cls.period_bounds(
            policy=policy,
            join_date=join_date,
            year=year,
        )

        # Masa tunggu belum lewat sepanjang periode ini.
        if eligible_from > period_end:
            return Entitlement(
                days=Decimal("0"),
                policy=policy,
                reason=(
                    f"Baru berhak {eligible_from} — "
                    f"{policy.eligible_after_months} bulan sejak masuk "
                    f"{join_date}."
                ),
            )

        full = Decimal(policy.entitlement_days)

        # Sudah berhak sejak sebelum periode ini dimulai: penuh.
        if eligible_from <= period_start:
            months_available = 12
        else:
            months_available = cls.months_between(
                eligible_from,
                period_end,
            )

        if months_available >= 12 or not policy.prorate_first_period:
            days = full
            reason = f"Jatah penuh menurut {policy.code}."
        else:
            days = (
                full * Decimal(months_available) / Decimal(12)
            ).quantize(Decimal("0.01"))

            reason = (
                f"Prorata {months_available}/12 — baru berhak "
                f"{eligible_from}."
            )

        # Akrual bulanan: yang sudah terkumpul sampai akhir periode
        # tetap sebesar jatahnya; yang membedakan cuma kapan bisa
        # dipakai. Pembatasan per bulan berjalan belum dibuat —
        # sengaja, karena butuh aturan "boleh minus atau tidak" yang
        # juga belum ada.
        if policy.accrual == LeaveAccrual.MONTHLY:
            reason = f"{reason} Terkumpul bulanan."

        return Entitlement(days=days, policy=policy, reason=reason)

    @staticmethod
    def replaced_by_opening(
        *,
        employee,
        leave_type,
        year: int,
        opening_balances: dict | None = None,
    ):
        """
        Dokumen saldo awal yang memegang tahun ini, kalau ada.

        **Setiap** baris yang sudah di-post memegang tahunnya, tanpa
        syarat apa pun. Dulu ini bergantung penanda `replaces_entitlement`
        per baris, dan penanda itu dibuang: saldo awal cuma punya satu
        arti — saldo aktual pegawai pada tanggal go-live — jadi tidak ada
        jatah tahun itu yang masih perlu diterbitkan sistem ini untuk
        ditumpuk di atasnya.

        Nol hari pun memegang tahunnya, dan itu bukan kelalaian: "saldo
        saya nol saat go-live" adalah pernyataan tentang tahun itu, sama
        tegasnya dengan tujuh. Yang jatahnya habis terpakai di sistem
        lama tidak boleh mendapat dua belas hari lagi di sini.

        Hanya berlaku untuk tahun dokumennya sendiri. Tahun sesudahnya
        jatahnya terbit normal — kalau tidak, satu dokumen migrasi akan
        mematikan jatah cuti seseorang selamanya.
        """
        key = (employee.pk, leave_type.pk)

        if opening_balances is not None:
            row = opening_balances.get(key)

            return row if row is not None and row.year == year else None

        from apps.hr.models import LeaveOpeningBalance, LeaveOpeningStatus

        return (
            LeaveOpeningBalance.objects
            .filter(
                employee=employee,
                leave_type=leave_type,
                year=year,
                # Yang masih draft belum berlaku apa-apa — termasuk
                # tidak boleh mematikan jatah tahun berjalan. Kalau
                # ikut dihitung, sebuah file yang baru diimport dan
                # belum diperiksa siapa pun sudah mengosongkan jatah
                # cuti orang.
                status=LeaveOpeningStatus.POSTED,
                is_deleted=False,
            )
            .first()
        )

    @staticmethod
    def opening_balance_map(*, employees=None, leave_types=None) -> dict:
        """
        Satu query untuk seluruh saldo awal yang sudah di-post.

        Tanpa ini, generator yang memutar 400 pegawai x 3 jenis cuti
        menembak 1.200 query tambahan — dan lambatnya baru terasa di
        tenant yang datanya banyak, bukan di tenant peragaan.
        """
        from apps.hr.models import LeaveOpeningBalance, LeaveOpeningStatus

        queryset = LeaveOpeningBalance.objects.filter(
            status=LeaveOpeningStatus.POSTED,
            is_deleted=False,
        )

        if employees is not None:
            queryset = queryset.filter(employee__in=employees)

        if leave_types is not None:
            queryset = queryset.filter(leave_type__in=leave_types)

        return {
            (row.employee_id, row.leave_type_id): row
            for row in queryset
        }

    @staticmethod
    def period_bounds(*, policy, join_date: date, year: int):
        """Awal dan akhir periode cuti untuk tahun yang diminta."""
        if policy.period_basis == LeavePeriodBasis.JOIN_DATE:
            start = date(year, join_date.month, join_date.day)

            return start, add_months(start, 12) - _one_day()

        return date(year, 1, 1), date(year, 12, 31)

    @staticmethod
    def months_between(start: date, end: date) -> int:
        """
        Jumlah bulan penuh dari `start` sampai `end`, minimal 0.

        Dibulatkan ke atas: pegawai yang berhak pada 20 Agustus tetap
        dihitung mendapat bagian Agustus. Membulatkan ke bawah membuat
        orang kehilangan sebulan hanya karena tanggal masuknya lewat
        tanggal 1.
        """
        months = (
            (end.year - start.year) * 12
            + (end.month - start.month)
            + 1
        )

        return max(0, months)


def _one_day():
    from datetime import timedelta

    return timedelta(days=1)


class LeaveBalanceGenerator:
    """
    Menerbitkan atau memperbarui `LeaveBalance` dari kebijakan.

    Aman diulang. Yang ditulis ulang hanya `entitlement` dan
    `carried_over`; `used` dijumlahkan ulang dari catatan cuti oleh
    `LeaveBalanceService`, dan `adjustment` tidak pernah disentuh.
    """

    @classmethod
    @transaction.atomic
    def sync_employee(
        cls,
        *,
        employee,
        years: list[int] | None = None,
        user=None,
    ) -> dict:
        """
        Menerbitkan ulang saldo satu pegawai.

        Dipanggil dari `EmploymentService.save()`: begitu Join Date,
        Employee Group, atau Employment Type diisi/diubah, jatahnya
        berubah — dan saldo yang masih nol karena Join Date-nya kosong
        harus langsung terisi tanpa menunggu ada yang ingat menjalankan
        perintah generate.

        Tahun yang disentuh: tahun berjalan dan tahun depan. Tahun
        depan ikut karena pegawai yang masuk pertengahan tahun ini
        biasanya baru berhak tahun depan, dan HR ingin melihat angkanya
        sekarang. Tahun-tahun lampau sengaja tidak disentuh — saldo
        yang sudah terpakai dan sudah ditutup tidak boleh berubah
        gara-gara seseorang mengoreksi data induk hari ini.
        """
        from django.utils import timezone

        if years is None:
            current = timezone.localdate().year
            years = [current, current + 1]

        totals = {"created": 0, "updated": 0}

        for year in years:
            result = cls.run(
                year=year,
                employees=[employee],
                user=user,
            )

            totals["created"] += result["created"]
            totals["updated"] += result["updated"]

        return totals

    @classmethod
    @transaction.atomic
    def run(
        cls,
        *,
        year: int,
        employees=None,
        leave_types=None,
        user=None,
        dry_run: bool = False,
    ) -> dict:
        from apps.administration.models import LeaveType
        from apps.hr.models import Employee

        if employees is None:
            employees = (
                Employee.objects
                .filter(is_deleted=False, is_active=True)
                .select_related(
                    "employment",
                    "employment__employee_group",
                    "employment__employment_type",
                    "organization",
                )
            )

        if leave_types is None:
            # Hanya jenis cuti yang benar-benar punya aturan
            # **bersaldo**. Membuat baris saldo nol untuk semua jenis
            # cuti akan memenuhi kartu pegawai dengan angka yang tidak
            # berarti apa-apa — dan untuk cuti per kejadian, angka nol
            # di kartunya justru terbaca sebagai jatah yang habis.
            #
            # Penyaringan di sini cuma menghemat perulangan; yang
            # benar-benar menjaga adalah `issues_balance` di bawah,
            # karena pemanggil boleh mengoper `leave_types` sendiri.
            leave_types = LeaveType.objects.filter(
                is_deleted=False,
                is_active=True,
                policies__is_deleted=False,
                policies__is_active=True,
                policies__uses_balance=True,
            ).distinct()

        created = 0
        updated = 0
        skipped = 0

        # Pasangan yang aturannya memang ada tapi tidak bersaldo.
        # Dihitung terpisah dari `skipped` (yang berarti "belum ada
        # aturannya sama sekali") — keduanya sama-sama tidak
        # menerbitkan baris, tapi yang satu keadaan yang benar dan yang
        # satu master yang belum diisi.
        non_balance = 0

        # Berapa pasangan yang jatahnya sengaja nol karena tahunnya
        # dipegang sistem lama. Dilaporkan, tidak didiamkan: perintah
        # generate yang membalas "0 dibuat, 0 diperbarui" tanpa
        # keterangan terbaca seperti perintah yang gagal jalan.
        from_opening = 0

        details: list[dict] = []

        # Satu query untuk seluruh dokumen migrasi yang menggantikan
        # jatah, bukan satu per pasangan di dalam perulangan.
        opening_balances = (
            LeaveEntitlementCalculator.opening_balance_map(
                employees=employees,
                leave_types=leave_types,
            )
        )

        # Idem untuk tanggal go-live: satu query untuk seluruh company
        # yang sudah bermigrasi, bukan satu per pegawai.
        go_live_map = LeaveGoLiveResolver.map_all()

        for employee in employees:
            for leave_type in leave_types:
                entitlement = (
                    LeaveEntitlementCalculator.for_employee(
                        employee=employee,
                        leave_type=leave_type,
                        year=year,
                        opening_balances=opening_balances,
                        go_live_map=go_live_map,
                    )
                )

                if not entitlement.has_policy:
                    skipped += 1

                    continue

                if not entitlement.issues_balance:
                    non_balance += 1

                    continue

                if entitlement.from_opening:
                    from_opening += 1

                details.append(
                    {
                        "employee": employee.employee_number,
                        "leave_type": leave_type.code,
                        "days": entitlement.days,
                        "reason": entitlement.reason,
                    },
                )

                if dry_run:
                    continue

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
                    LeaveBalance.objects.create(
                        employee=employee,
                        leave_type=leave_type,
                        year=year,
                        entitlement=entitlement.days,
                        created_by=user,
                    )

                    created += 1

                    continue

                if balance.entitlement == entitlement.days:
                    continue

                balance.entitlement = entitlement.days
                balance.updated_by = user

                balance.save(
                    update_fields=[
                        "entitlement",
                        "updated_by",
                        "updated_at",
                    ],
                )

                updated += 1

        return {
            "year": year,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "non_balance": non_balance,
            "from_opening": from_opening,
            "details": details,
        }
