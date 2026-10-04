"""
Pemeriksaan sebelum Finalize.

Dua tingkat, dan pemisahannya yang jadi intinya:

* **ERROR** — Finalize ditolak. Angkanya tidak bisa dipertanggung-
  jawabkan: gaji pokok nol, konfigurasi payroll belum ada, pegawai yang
  sama sudah terbayar di run lain periode itu.
* **WARNING** — boleh dilanjutkan, tapi harus diakui dulu
  (`POST .../acknowledge/`). Keadaan yang **sah** tapi patut dilihat
  orang: absensi belum masuk, lembur tercatat pada orang yang tidak
  eligible, net pay nol.

Daftar temuan yang seluruhnya menghalangi membuat orang berhenti
membacanya, dan yang tidak menghalangi apa pun membuat orang tidak
pernah membukanya. Karena itu keduanya harus ada, dan keduanya harus
sedikit.
"""

from __future__ import annotations

from decimal import Decimal

from apps.payroll.models import (
    PayrollDailyRateMethod,
    PayrollFindingLevel,
    PayrollPayBasis,
    PayrollRunEmployeeStatus,
    PayrollRunStatus,
)

ZERO = Decimal("0.00")


def finding(*, level, code, message, employee=None, employee_name="") -> dict:
    return {
        "level": level,
        "code": code,
        "message": message,
        "employee": employee,
        "employee_name": employee_name,
    }


class PayrollValidationService:
    @classmethod
    def validate(cls, *, run) -> dict:
        """
        Mengembalikan ringkasan temuan seluruh run.

        Bentuknya `{"errors": [...], "warnings": [...], "counts": {...}}`
        dan disimpan apa adanya di `PayrollRun.validation_summary`,
        supaya layar Review menampilkan temuan yang **sama** dengan yang
        dipakai Finalize.
        """
        from apps.payroll.models import PayrollRunEmployee

        findings: list[dict] = []

        lines = list(
            PayrollRunEmployee.objects
            .filter(run=run, is_deleted=False)
            .select_related(
                "employee", "payroll_assignment", "overtime_group",
                "payroll_policy", "payroll_policy__company",
            )
            .prefetch_related("overtime_group__tiers")
        )

        if not lines:
            findings.append(
                finding(
                    level=PayrollFindingLevel.ERROR,
                    code="no_employee",
                    message=(
                        "Run ini belum punya satu pun pegawai. "
                        "Jalankan Generate Employees dulu."
                    ),
                ),
            )

        cls._check_proration_policy(run=run, findings=findings)

        cls._check_attendance_policy(run=run, findings=findings)

        cls._check_payroll_policies(run=run, lines=lines, findings=findings)

        cls._check_overtime_groups(lines=lines, findings=findings)

        cls._check_duplicate_across_runs(run=run, lines=lines, findings=findings)

        for line in lines:
            if line.is_excluded:
                continue

            cls._check_line(line=line, findings=findings)

        errors = [
            item for item in findings
            if item["level"] == PayrollFindingLevel.ERROR
        ]
        warnings = [
            item for item in findings
            if item["level"] == PayrollFindingLevel.WARNING
        ]

        return {
            "errors": errors,
            "warnings": warnings,
            "counts": {
                "employees": len(lines),
                "excluded": sum(1 for line in lines if line.is_excluded),
                "errors": len(errors),
                "warnings": len(warnings),
            },
        }

    # ------------------------------------------------------------------

    @classmethod
    def _check_proration_policy(cls, *, run, findings: list[dict]) -> None:
        """
        Perusahaan yang belum memilih metode prorata disebut namanya.

        Angkanya tetap terbit — metodenya sama persis dengan perilaku
        sebelum kebijakan ini ada, jadi tidak ada payroll berjalan yang
        berubah. Yang tidak boleh adalah diamnya: "belum dipilih" dan
        "sudah dipilih, kebetulan Kalender" menghasilkan angka yang
        sama, dan tanpa temuan ini keduanya tidak bisa dibedakan siapa
        pun.
        """
        from apps.payroll.services.setting import PayrollSettingService

        policy = PayrollSettingService.resolve_policy(company=run.company)

        if not policy.is_default:
            return

        findings.append(
            finding(
                level=PayrollFindingLevel.WARNING,
                code="proration_policy_missing",
                message=(
                    "Perusahaan ini belum punya Payroll Setting, jadi "
                    "prorata gaji pokok memakai bawaan "
                    f"\"{policy.method_label}\". Tentukan kebijakannya "
                    "di Payroll → Payroll Settings."
                ),
            ),
        )

    @classmethod
    def _check_attendance_policy(cls, *, run, findings: list[dict]) -> None:
        """
        Perusahaan yang belum memilih cara memotong ketidakhadiran.

        Sama seperti kebijakan prorata: angkanya tetap terbit dengan
        pembagi hari periode — perilaku lama, tidak ada payroll berjalan
        yang berubah — tapi diamnya yang tidak boleh. "Belum dipilih"
        dan "sudah dipilih, kebetulan sama" menghasilkan angka yang
        sama, dan tanpa temuan ini tidak ada yang bisa membedakannya.

        Diperiksa terpisah dari prorata, bukan digabung jadi satu
        temuan: keduanya keputusan yang berbeda, dan perusahaan yang
        sudah menutup yang satu tidak boleh terus ditagih untuk yang
        lain.
        """
        from apps.payroll.services.setting import PayrollSettingService

        policy = PayrollSettingService.resolve_attendance_policy(
            company=run.company,
        )

        if not policy.is_default:
            return

        findings.append(
            finding(
                level=PayrollFindingLevel.WARNING,
                code="attendance_deduction_policy_missing",
                message=(
                    "Perusahaan ini belum memilih cara menghitung "
                    "potongan absen dan cuti tidak dibayar, jadi "
                    "pembaginya diambil dari kolom hari kerja periode "
                    "payroll. Tentukan kebijakannya di Payroll → "
                    "Payroll Settings."
                ),
            ),
        )

    @classmethod
    def _check_payroll_policies(cls, *, run, lines, findings: list[dict]) -> None:
        """
        Konfigurasi Payroll Policy yang dipakai run ini.

        Diperiksa **sekali per kebijakan**, bukan per pegawai:
        kebijakan yang belum lengkap salah untuk semua orang yang
        memakainya, dan mencetak temuan yang sama lima ratus kali
        membuat daftar temuan berhenti dibaca.

        Yang tidak diperbaiki diam-diam: kebijakan harian yang belum
        menyatakan cara upah sehariannya, dan yang belum menyatakan
        perlakuan cuti dibayarnya. Keduanya menentukan berapa orang
        dibayar, dan bawaan apa pun di situ berarti sistem yang
        memutuskan, bukan perusahaan.
        """
        policies = {
            line.payroll_policy_id: line.payroll_policy
            for line in lines
            if line.payroll_policy_id is not None and not line.is_excluded
        }

        for policy in policies.values():
            label = f"Payroll Policy {policy.code}"

            def add(code, message, level=PayrollFindingLevel.ERROR):
                findings.append(
                    finding(level=level, code=code, message=message),
                )

            if policy.company_id != run.company_id:
                add(
                    "policy_company_mismatch",
                    f"{label} milik perusahaan lain, jadi tidak boleh "
                    "dipakai di run ini.",
                )

            if not policy.is_active:
                # Bukan ERROR: angkanya tetap terbit dengan default
                # perusahaan, sama seperti pegawai yang memang belum
                # punya kebijakan. Yang tidak boleh adalah diamnya.
                add(
                    "policy_inactive",
                    f"{label} sudah dinonaktifkan, jadi pegawai yang "
                    "memakainya dihitung dengan default perusahaan.",
                    level=PayrollFindingLevel.WARNING,
                )
                continue

            if not policy.is_daily:
                continue

            if not policy.daily_rate_method:
                add(
                    "daily_rate_method_missing",
                    f"{label} berdasar Harian tapi belum menyatakan "
                    "upah seharinya diambil dari mana. Tarif di "
                    "Payroll Assignment dan gaji sebulan dibagi "
                    "pembagi menghasilkan angka yang berbeda.",
                )

            if not policy.daily_rate_divisor and policy.daily_rate_method == (
                PayrollDailyRateMethod.FROM_MONTHLY
            ):
                add(
                    "daily_rate_divisor_missing",
                    f"{label} menurunkan upah sehari dari gaji sebulan "
                    "tapi pembaginya belum diisi.",
                )

            # BUSINESS SUB-DECISION — DAILY PAID LEAVE.
            #
            # Tidak ada aturan authoritative di sistem ini tentang
            # pekerja harian pada hari cuti yang disetujui.
            # `PayrollLeaveRule` menjawab pertanyaan yang berbeda:
            # jenis cuti mana yang **memotong** gaji bulanan.
            if policy.pays_paid_leave is None:
                add(
                    "daily_paid_leave_undecided",
                    f"{label} belum menyatakan apakah hari cuti yang "
                    "disetujui tetap dibayar untuk pegawai harian. "
                    "Sistem tidak memilihkan — keduanya lazim dan "
                    "hasilnya berbeda.",
                )

    @classmethod
    def _check_overtime_groups(cls, *, lines, findings: list[dict]) -> None:
        """
        Konfigurasi Overtime Group yang dipakai run ini.

        Diperiksa **sekali per kelompok**, bukan per pegawai: kelompok
        yang rentangnya bolong salah untuk semua orang yang memakainya,
        dan mencetak temuan yang sama lima ratus kali membuat daftar
        temuan berhenti dibaca.

        Mesin hitung juga menolak konfigurasi ini masing-masing, dan
        pengulangan itu disengaja: yang di sini menyebut nama
        kelompoknya sebelum orang menekan Calculate, yang di sana
        menjamin tidak ada jalan memutarinya.
        """
        groups = {
            line.overtime_group_id: line.overtime_group
            for line in lines
            if line.overtime_group_id is not None
        }

        for group in groups.values():
            label = f"Overtime Group {group.code}"

            def add(code, message):
                findings.append(
                    finding(
                        level=PayrollFindingLevel.ERROR,
                        code=code,
                        message=message,
                    ),
                )

            if not group.hourly_divisor or group.hourly_divisor <= ZERO:
                add(
                    "overtime_divisor_invalid",
                    f"{label} belum punya Hourly Divisor yang sah.",
                )

            tiers = list(group.active_tiers)

            if not tiers:
                # Tanpa tingkat, pengali tunggalnya yang dipakai — dan
                # itu harus sah.
                if not group.hourly_multiplier or group.hourly_multiplier <= ZERO:
                    add(
                        "overtime_multiplier_invalid",
                        f"{label} belum punya pengali yang sah dan "
                        "belum punya tingkat.",
                    )
                continue

            if not group.tier_basis:
                add(
                    "overtime_tier_basis_missing",
                    f"{label} punya tingkat pengali tapi belum "
                    "menyatakan tingkatnya disusun per hari lembur "
                    "atau dari total jam sebulan. Keduanya "
                    "menghasilkan angka yang berbeda.",
                )

            cls._check_tier_ranges(group=group, tiers=tiers, add=add, label=label)

    @staticmethod
    def _check_tier_ranges(*, group, tiers, add, label) -> None:
        """
        Rentang tingkat harus **menutup jamnya sekali, tanpa celah**.

        Tiga cacat yang dicari, dan ketiganya menghasilkan uang yang
        salah tanpa satu pun tanda di layar: mulai bukan dari nol
        (jam-jam pertama tidak punya tarif), bertumpang tindih (satu
        jam dibayar dua kali), dan berlubang (jam di tengah tidak
        punya tarif).
        """
        previous = None

        for tier in tiers:
            if tier.multiplier is None or tier.multiplier <= ZERO:
                add(
                    "overtime_tier_multiplier_invalid",
                    f"{label}: tingkat urutan {tier.sequence} punya "
                    "pengali nol atau negatif.",
                )

            if (
                tier.hour_to is not None
                and tier.hour_from is not None
                and tier.hour_to <= tier.hour_from
            ):
                add(
                    "overtime_tier_range_invalid",
                    f"{label}: tingkat urutan {tier.sequence} punya "
                    "batas atas yang tidak lebih besar dari batas "
                    "bawahnya.",
                )

            if previous is None:
                if tier.hour_from and tier.hour_from > ZERO:
                    add(
                        "overtime_tier_gap",
                        f"{label}: tingkat pertama mulai dari jam "
                        f"{tier.hour_from}, jadi jam lembur di "
                        "bawahnya tidak punya tarif.",
                    )
            else:
                if previous.hour_to is None:
                    add(
                        "overtime_tier_overlap",
                        f"{label}: tingkat urutan {previous.sequence} "
                        "tidak berbatas atas, jadi tingkat sesudahnya "
                        "tidak akan pernah terpakai.",
                    )
                elif tier.hour_from < previous.hour_to:
                    add(
                        "overtime_tier_overlap",
                        f"{label}: tingkat urutan {tier.sequence} "
                        "bertumpang tindih dengan tingkat sebelumnya.",
                    )
                elif tier.hour_from > previous.hour_to:
                    add(
                        "overtime_tier_gap",
                        f"{label}: ada celah antara jam "
                        f"{previous.hour_to} dan {tier.hour_from} yang "
                        "tidak punya tarif.",
                    )

            previous = tier

        if previous is not None and previous.hour_to is not None:
            add(
                "overtime_tier_gap",
                f"{label}: tingkat teratas berhenti di jam "
                f"{previous.hour_to}. Kosongkan batas atasnya supaya "
                "jam di atas itu tetap punya tarif.",
            )

    @classmethod
    def _check_line(cls, *, line, findings: list[dict]) -> None:
        name = getattr(line.employee, "full_name", "") or str(line.employee_id)
        number = getattr(line.employee, "employee_number", "")
        label = f"{number} {name}".strip()

        def add(level, code, message):
            findings.append(
                finding(
                    level=level,
                    code=code,
                    message=message,
                    employee=line.employee_id,
                    employee_name=label,
                ),
            )

        if line.payroll_assignment_id is None:
            add(
                PayrollFindingLevel.ERROR,
                "assignment_missing",
                (
                    f"{label} belum punya Payroll Assignment yang berlaku "
                    "pada periode ini."
                ),
            )

        # Pegawai **harian** yang gaji sebulannya nol bukan konfigurasi
        # yang belum selesai: upahnya memang tidak dibentuk dari angka
        # sebulan. Yang wajib ada untuknya tarif hariannya, dan itu
        # sudah ditagih mesin hitung lewat `daily_rate_missing` —
        # menagih Basic Salary di sini berarti setiap pegawai harian
        # gagal Finalize karena kolom yang tidak pernah dipakai
        # menghitung apa pun.
        if line.pay_basis == PayrollPayBasis.DAILY:
            if not line.daily_rate:
                add(
                    PayrollFindingLevel.ERROR,
                    "daily_rate_missing",
                    f"{label} belum punya upah sehari yang sah.",
                )

        elif not line.basic_salary:
            add(
                PayrollFindingLevel.ERROR,
                "basic_salary_missing",
                f"{label} belum punya Basic Salary.",
            )

        if line.payroll_assignment_id and not line.currency_id:
            add(
                PayrollFindingLevel.WARNING,
                "currency_missing",
                f"{label} belum punya mata uang pada payroll assignment.",
            )

        if line.join_date is None:
            add(
                PayrollFindingLevel.WARNING,
                "join_date_missing",
                (
                    f"{label} belum punya Join Date, jadi prorata tidak "
                    "bisa diperiksa."
                ),
            )

        if line.status == PayrollRunEmployeeStatus.PENDING:
            add(
                PayrollFindingLevel.ERROR,
                "not_calculated",
                f"{label} belum dihitung.",
            )

        if line.status == PayrollRunEmployeeStatus.ERROR:
            add(
                PayrollFindingLevel.ERROR,
                "calculation_error",
                f"{label} gagal dihitung. Periksa rincian barisnya.",
            )

        if line.net_pay < ZERO:
            add(
                PayrollFindingLevel.ERROR,
                "negative_net_pay",
                (
                    f"{label} bernilai Net Pay negatif ({line.net_pay}). "
                    "Potongannya melebihi penghasilan."
                ),
            )

        elif (
            line.status == PayrollRunEmployeeStatus.CALCULATED
            and line.net_pay == ZERO
        ):
            add(
                PayrollFindingLevel.WARNING,
                "zero_net_pay",
                f"{label} bernilai Net Pay nol.",
            )

        # Temuan yang lahir saat perhitungan (lembur tanpa eligibility,
        # bracket pajak kosong, basis tak dikenal) ikut dinaikkan ke
        # ringkasan run — kalau tidak, ia cuma terbaca oleh yang membuka
        # baris satu per satu.
        for item in line.findings or []:
            findings.append(
                finding(
                    level=item.get("level", PayrollFindingLevel.WARNING),
                    code=item.get("code", "calculation"),
                    message=f"{label}: {item.get('message', '')}",
                    employee=line.employee_id,
                    employee_name=label,
                ),
            )

    @classmethod
    def _check_duplicate_across_runs(cls, *, run, lines, findings: list[dict]) -> None:
        """
        Pegawai yang sudah difinalisasi di run lain pada periode yang
        sama.

        Diperiksa lintas run, bukan hanya di dalam run ini: duplikat di
        dalam satu run sudah dijaga constraint unik, sementara "sudah
        dibayar lewat run reguler lalu ikut lagi di run off-cycle"
        justru yang tidak berbunyi sendiri.

        Pengecualiannya satu, dan sempit (PF-0G): rantai run yang
        **digantikan** run ini. Koreksi memuat hasil periode itu
        seutuhnya, jadi pegawai yang sama pasti muncul lagi di run yang
        dikoreksinya — itu bukan pembayaran kedua, itu pengganti yang
        pertama. Run lain di periode yang sama, termasuk koreksi atas run
        lain, tetap berbunyi.
        """
        from apps.payroll.models import PayrollRunEmployee

        if not lines:
            return

        employee_ids = [line.employee_id for line in lines]

        clashes = (
            PayrollRunEmployee.objects
            .filter(
                run__period_id=run.period_id,
                run__status=PayrollRunStatus.FINALIZED,
                run__is_deleted=False,
                employee_id__in=employee_ids,
                is_deleted=False,
                is_excluded=False,
            )
            .exclude(run_id__in={run.pk, *run.corrected_run_ids()})
            .select_related("employee", "run")
        )

        for clash in clashes:
            name = getattr(clash.employee, "full_name", "")
            number = getattr(clash.employee, "employee_number", "")

            findings.append(
                finding(
                    level=PayrollFindingLevel.ERROR,
                    code="duplicate_finalized",
                    message=(
                        f"{number} {name} sudah difinalisasi di run "
                        f"{clash.run.document_number or clash.run_id} "
                        "untuk periode yang sama."
                    ),
                    employee=clash.employee_id,
                    employee_name=f"{number} {name}".strip(),
                ),
            )
