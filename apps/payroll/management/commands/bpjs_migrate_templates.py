"""
Cutover BPJS: dari baris Deduction Template ke konsep kelas satu.

    python manage.py tenant_command bpjs_migrate_templates \\
        --schema=demo \\
        --map JHT=BPJS-JHT,BPJS-JHT-ER \\
        --map JKN=BPJS-KES,BPJS-KES-ER \\
        --effective-from=2026-01-01 \\
        [--apply]

**Dry-run adalah bawaannya.** Tanpa `--apply` tidak satu baris pun
tersimpan.

**Pemetaannya wajib ditulis orang.** Perintah ini tidak menebak baris
mana yang BPJS dari kodenya — menebak lewat nama persis yang dibuang
keputusan #3A, dan menebak di perintah migrasi lebih berbahaya lagi
karena hasilnya jadi data. Yang tidak dipetakan tidak disentuh.

**Gerbang selisih-nol.** Sesudah aturan dan kepesertaan dibuat, seluruh
run yang masih terbuka dihitung ulang di dalam transaksi dan hasilnya
dibandingkan dengan angka yang tersimpan. Satu rupiah pun berbeda →
`--apply` ditolak dan seluruh transaksi di-rollback. Run yang sudah
difinalisasi tidak pernah ikut dihitung ulang; snapshotnya yang
berlaku.

**Cutover ini satu langkah, dan itu koreksi dari rancangan awal.**
Semula baris Deduction Template lama dimatikan di langkah terpisah
sesudah `--apply`. Menjalankannya di data sungguhan memperlihatkan
kenapa itu tidak bisa: selama baris lama masih aktif, aturan BPJS baru
memotong di sampingnya dan pegawainya kena **dua kali** — gerbang
selisih-nol menolak keadaan itu, selalu, dan benar menolaknya. Tidak
ada keadaan antara yang aman untuk disimpan, jadi aturan terbit dan
baris lama mati **bersama-sama** di dalam satu transaksi.

Yang membuatnya tetap bisa dibatalkan: dry-run adalah bawaannya dan
tidak menyimpan apa pun, dan baris lama di-**soft delete** sehingga
bisa dipulihkan.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.payroll.models import (
    BpjsBaseDefinition,
    BpjsEnrollment,
    BpjsProgram,
    BpjsRule,
    DeductionTemplateLine,
    PayrollRun,
    PayrollRunEmployee,
    PayrollRunStatus,
)


ZERO = Decimal("0.00")

#: Run yang sudah terkunci. Tidak pernah dihitung ulang, tidak pernah
#: ikut gerbang selisih — angkanya sudah dibekukan snapshot.
LOCKED_STATUSES = {PayrollRunStatus.FINALIZED}


class Command(BaseCommand):
    help = (
        "Memindahkan konfigurasi BPJS dari Deduction Template ke "
        "BpjsProgram/BpjsRule/BpjsEnrollment. Dry-run bawaannya."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--map",
            action="append",
            default=[],
            metavar="PROGRAM=KODE[,KODE...]",
            help=(
                "Pemetaan eksplisit kode program ke kode baris "
                "Deduction Template. Boleh diulang."
            ),
        )
        parser.add_argument(
            "--effective-from",
            required=False,
            help="Tanggal mulai berlakunya aturan hasil konversi (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--base-code",
            default="UPAH-POKOK",
            help="Kode komposisi dasar yang dibuat/dipakai.",
        )
        parser.add_argument("--apply", action="store_true")

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        mappings = self._parse_map(options["map"])

        if not mappings:
            raise CommandError(
                "Tidak ada pemetaan. Perintah ini tidak menebak baris "
                "mana yang BPJS — tulis --map PROGRAM=KODE,KODE.",
            )

        effective_from = self._parse_date(options.get("effective_from"))

        if effective_from is None:
            raise CommandError(
                "--effective-from wajib diisi. Tanggal berlakunya "
                "aturan adalah keputusan, bukan sesuatu yang boleh "
                "ditebak dari tanggal hari ini.",
            )

        apply = options["apply"]

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Cutover BPJS" + ("" if apply else " (DRY-RUN)"),
            ),
        )
        self.stdout.write("")

        try:
            with transaction.atomic():
                report = self._run(
                    mappings=mappings,
                    effective_from=effective_from,
                    base_code=options["base_code"],
                )

                if report["blocked"]:
                    transaction.set_rollback(True)

                    self.stdout.write("")
                    self.stdout.write(
                        self.style.ERROR(
                            "DITOLAK: gerbang selisih-nol tidak "
                            "terlampaui. Tidak ada yang disimpan.",
                        ),
                    )

                    return

                if not apply:
                    # Dry-run menjalankan seluruh jalurnya lalu
                    # dibatalkan: yang dilaporkan adalah yang
                    # benar-benar terjadi, bukan simulasi terpisah yang
                    # bisa menyimpang dari kode yang menulis.
                    transaction.set_rollback(True)
        except CommandError:
            raise

        self.stdout.write("")

        if apply and not report["blocked"]:
            self.stdout.write(self.style.SUCCESS("Selesai, tersimpan."))
        elif not apply:
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run. Jalankan ulang dengan --apply untuk "
                    "menyimpan.",
                ),
            )

    # ------------------------------------------------------------------

    def _run(self, *, mappings, effective_from, base_code):
        base = self._ensure_base_definition(base_code)

        self.stdout.write(
            f"  Komposisi dasar : {base.code} v{base.version} "
            f"(gaji pokok saja)",
        )
        self.stdout.write("")

        converted_line_ids: list[int] = []

        for program_code, line_codes in mappings.items():
            program = self._ensure_program(program_code)

            lines = list(
                DeductionTemplateLine.objects
                .filter(code__in=line_codes, is_deleted=False)
                .order_by("code"),
            )

            if not lines:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {program_code}: tidak ada baris "
                        f"{', '.join(line_codes)} — dilewati.",
                    ),
                )
                continue

            employee_line = next(
                (row for row in lines if not row.is_employer_cost), None,
            )
            employer_line = next(
                (row for row in lines if row.is_employer_cost), None,
            )

            rule = BpjsRule(
                program=program,
                company=None,
                base_definition=base,
                effective_from=effective_from,
                employee_rate=(
                    employee_line.rate if employee_line is not None else None
                ),
                employee_minimum_amount=(
                    employee_line.minimum_amount
                    if employee_line is not None
                    else None
                ),
                employee_maximum_amount=(
                    employee_line.maximum_amount
                    if employee_line is not None
                    else None
                ),
                reduces_taxable=(
                    employee_line.reduces_taxable
                    if employee_line is not None
                    else False
                ),
                employer_rate=(
                    employer_line.rate if employer_line is not None else None
                ),
                employer_minimum_amount=(
                    employer_line.minimum_amount
                    if employer_line is not None
                    else None
                ),
                employer_maximum_amount=(
                    employer_line.maximum_amount
                    if employer_line is not None
                    else None
                ),
                base_minimum=self._first(
                    lines, "minimum_base",
                ),
                base_maximum=self._first(
                    lines, "maximum_base",
                ),
                description=(
                    "Hasil konversi dari Deduction Template "
                    f"({', '.join(row.code for row in lines)}). "
                    "Angkanya dibawa apa adanya — masih DATA PERAGAAN "
                    "sampai manajemen menetapkan tarif sebenarnya."
                ),
            )

            rule.full_clean()
            rule.save()

            enrolled = self._backfill_enrollments(
                program=program,
                lines=lines,
                enrolled_from=effective_from,
            )

            converted_line_ids.extend(row.pk for row in lines)

            self.stdout.write(
                f"  {program.code:<8} pegawai="
                f"{self._rate(rule.employee_rate)} "
                f"perusahaan={self._rate(rule.employer_rate)} "
                f"plafon dasar={rule.base_maximum or '-'} "
                f"→ {enrolled} kepesertaan",
            )

        self.stdout.write("")

        # Baris lama dimatikan **sebelum** gerbang, bukan sesudahnya.
        #
        # Ditemukan saat menjalankannya di data sungguhan: selama baris
        # Deduction Template lama masih aktif, aturan BPJS yang baru
        # memotong di sampingnya dan 24 pegawai kena dua kali. Gerbang
        # yang mengukur keadaan itu **selalu** gagal — bukan karena
        # konversinya salah, melainkan karena yang diukurnya keadaan
        # yang tidak pernah boleh terjadi.
        #
        # Karena itu cutover ini **satu langkah**: aturan terbit dan
        # baris lama mati bersama-sama, di dalam satu transaksi. Tidak
        # ada keadaan antara yang aman untuk disimpan.
        if converted_line_ids:
            count = (
                DeductionTemplateLine.objects
                .filter(pk__in=converted_line_ids, is_deleted=False)
                .update(is_deleted=True, is_active=False)
            )

            self.stdout.write(
                f"  Baris lama dinonaktifkan: {count} baris Deduction "
                f"Template (soft delete, bisa dipulihkan).",
            )

        blocked = self._zero_delta_gate()

        return {"blocked": blocked}

    # ------------------------------------------------------------------
    # Gerbang selisih-nol
    # ------------------------------------------------------------------

    def _zero_delta_gate(self) -> bool:
        """
        Hitung ulang run yang masih terbuka, lalu bandingkan.

        Yang dibandingkan angka yang **diterima pegawai** dan totalnya.
        Selisih satu rupiah pun membatalkan cutover: perpindahan
        konfigurasi yang mengubah gaji bukan perpindahan konfigurasi,
        melainkan perubahan kebijakan yang menyamar jadi migrasi.
        """
        from apps.payroll.services import PayrollRunService

        runs = list(
            PayrollRun.objects
            .filter(is_deleted=False)
            .exclude(status__in=LOCKED_STATUSES)
            .order_by("id"),
        )

        if not runs:
            self.stdout.write("  Gerbang selisih-nol: tidak ada run terbuka.")
            return False

        before = {
            row.pk: (
                row.gross_earning,
                row.total_deduction,
                row.tax_amount,
                row.net_pay,
                row.employer_contribution,
            )
            for row in PayrollRunEmployee.objects.filter(
                run__in=runs, is_deleted=False,
            )
        }

        for run in runs:
            PayrollRunService.calculate(run=run)

        differences = []

        for row in PayrollRunEmployee.objects.filter(
            run__in=runs, is_deleted=False,
        ):
            old = before.get(row.pk)

            new = (
                row.gross_earning,
                row.total_deduction,
                row.tax_amount,
                row.net_pay,
                row.employer_contribution,
            )

            if old is not None and old != new:
                differences.append((row, old, new))

        if not differences:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Gerbang selisih-nol: LULUS "
                    f"({len(before)} baris di {len(runs)} run terbuka).",
                ),
            )
            return False

        self.stdout.write(
            self.style.ERROR(
                f"  Gerbang selisih-nol: GAGAL — {len(differences)} "
                f"baris berubah.",
            ),
        )

        for row, old, new in differences[:10]:
            self.stdout.write(
                f"    {row.employee_id}: net {old[3]} → {new[3]}, "
                f"potongan {old[1]} → {new[1]}, "
                f"beban perusahaan {old[4]} → {new[4]}",
            )

        if len(differences) > 10:
            self.stdout.write(f"    ... dan {len(differences) - 10} lagi")

        return True

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------

    def _ensure_program(self, code):
        program = BpjsProgram.objects.filter(
            code=code, is_deleted=False,
        ).first()

        if program is not None:
            return program

        program = BpjsProgram(code=code, name=code)
        program.full_clean()
        program.save()

        return program

    def _ensure_base_definition(self, code):
        existing = (
            BpjsBaseDefinition.objects
            .filter(code=code, is_deleted=False)
            .order_by("-version")
            .first()
        )

        if existing is not None:
            return existing

        # Gaji pokok saja — persis dasar yang dipakai baris
        # `percent_of_basic` hari ini. Komposisi yang lebih luas adalah
        # keputusan bisnis (#3B), bukan sesuatu yang boleh lahir dari
        # perintah migrasi.
        definition = BpjsBaseDefinition(
            code=code,
            version=1,
            name="Upah Pokok",
            include_basic=True,
            description=(
                "Hasil konversi: gaji pokok saja, sama dengan dasar "
                "yang dipakai baris Deduction Template sebelumnya."
            ),
        )
        definition.full_clean()
        definition.save()

        return definition

    def _backfill_enrollments(self, *, program, lines, enrolled_from) -> int:
        """
        Semua yang hari ini memang dipotong didaftarkan.

        Tanpa ini cutover mematikan iuran semua orang diam-diam:
        sesudah #3A, tidak ada kepesertaan berarti tidak ikut.
        """
        template_ids = {row.template_id for row in lines}

        employee_ids = set(
            PayrollRunEmployee.objects
            .filter(
                deduction_template_id__in=template_ids,
                is_deleted=False,
            )
            .values_list("employee_id", flat=True),
        )

        from apps.hr.models import PayrollAssignment

        employee_ids |= set(
            PayrollAssignment.objects
            .filter(
                deduction_template_id__in=template_ids,
                is_deleted=False,
            )
            .values_list("employee_id", flat=True),
        )

        created = 0

        for employee_id in sorted(employee_ids):
            exists = BpjsEnrollment.objects.filter(
                employee_id=employee_id,
                program=program,
                is_deleted=False,
            ).exists()

            if exists:
                continue

            number = self._membership_number(
                employee_id=employee_id, program_code=program.code,
            )

            enrollment = BpjsEnrollment(
                employee_id=employee_id,
                program=program,
                participates=True,
                enrolled_from=enrolled_from,
                membership_number=number,
            )
            enrollment.full_clean()
            enrollment.save()

            created += 1

        return created

    @staticmethod
    def _membership_number(*, employee_id, program_code) -> str:
        """
        Nomor kepesertaan dibawa dari `PayrollAssignment` kalau ada.

        Kolom lamanya tetap ada dan tetap terbaca — yang berubah cuma
        siapa yang berwenang, dan itu sekarang `BpjsEnrollment`.
        """
        from apps.hr.models import PayrollAssignment

        assignment = (
            PayrollAssignment.objects
            .filter(employee_id=employee_id, is_deleted=False)
            .order_by("-effective_from")
            .first()
        )

        if assignment is None:
            return ""

        if program_code.upper() in {"JKN", "KES", "KESEHATAN"}:
            return assignment.bpjs_kesehatan_number or ""

        return assignment.bpjs_ketenagakerjaan_number or ""

    @staticmethod
    def _first(lines, attribute):
        for row in lines:
            value = getattr(row, attribute, None)

            if value is not None:
                return value

        return None

    @staticmethod
    def _rate(value) -> str:
        return "-" if value is None else f"{value}%"

    @staticmethod
    def _parse_map(raw_values) -> dict[str, list[str]]:
        mappings: dict[str, list[str]] = {}

        for raw in raw_values:
            if "=" not in raw:
                raise CommandError(
                    f"Pemetaan '{raw}' tidak berbentuk PROGRAM=KODE.",
                )

            program, _, codes = raw.partition("=")

            entries = [item.strip() for item in codes.split(",") if item.strip()]

            if not entries:
                raise CommandError(
                    f"Pemetaan '{raw}' tidak menyebut satu kode pun.",
                )

            mappings.setdefault(program.strip().upper(), []).extend(entries)

        return mappings

    @staticmethod
    def _parse_date(raw) -> date | None:
        if not raw:
            return None

        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError as error:
            raise CommandError(
                f"Tanggal '{raw}' tidak berbentuk YYYY-MM-DD.",
            ) from error
