"""
Menjalankan urutan go-live cuti dari baris perintah.

Satu perintah untuk tiga langkah yang memang selalu berurutan — set
tanggal, periksa kesiapan, posting — karena memisahkannya jadi tiga
perintah membuat langkah kedua gampang dilewati, dan langkah kedua itu
justru satu-satunya yang bisa menangkap kolom yang tertukar sebelum
angkanya menempel di kartu cuti orang.

    # 1. tetapkan tanggalnya
    tenant_command leave_go_live --company=MMR --date=2026-09-01

    # 2. (import lewat layar / pipeline import) lalu periksa
    tenant_command leave_go_live --status

    # 3. jadikan saldo pegawai
    tenant_command leave_go_live --company=MMR --post
"""

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from apps.administration.models import Company
from apps.hr.api.leave_opening.services import LeaveOpeningBalanceService
from apps.hr.models import LeaveGoLive, LeaveOpeningBalance, LeaveOpeningStatus


class Command(BaseCommand):
    help = (
        "Set tanggal go-live cuti per company, periksa kesiapan saldo "
        "awalnya, lalu posting. Aman diulang."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            help=(
                "Kode company. Wajib untuk --date dan --post; "
                "dikosongkan pada --status berarti seluruh company."
            ),
        )

        parser.add_argument(
            "--date",
            help=(
                "Tanggal go-live (YYYY-MM-DD). Hari pertama cuti "
                "dikelola di sistem ini."
            ),
        )

        parser.add_argument(
            "--deactivate",
            action="store_true",
            help=(
                "Matikan go-live company itu — jatah kembali dihitung "
                "dari Leave Policy seperti biasa."
            ),
        )

        parser.add_argument(
            "--status",
            action="store_true",
            help="Cetak kesiapan tiap company. Tidak menulis apa pun.",
        )

        parser.add_argument(
            "--post",
            action="store_true",
            help=(
                "Post seluruh saldo awal yang masih draft, jadikan "
                "saldo pegawai."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tampilkan yang akan dikerjakan tanpa menulis apa pun.",
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        if not any(
            (
                options["date"],
                options["status"],
                options["post"],
                options["deactivate"],
            )
        ):
            raise CommandError(
                "Sebutkan salah satu: --date, --status, --post, atau "
                "--deactivate.",
            )

        company = None

        if options["company"]:
            company = (
                Company.objects
                .filter(code__iexact=options["company"], is_deleted=False)
                .first()
            )

            if company is None:
                raise CommandError(
                    f"Company '{options['company']}' tidak ada.",
                )

        if options["date"]:
            self._set_date(company, options)

        if options["deactivate"]:
            self._deactivate(company, options)

        if options["status"]:
            self._status(company)

        if options["post"]:
            self._post(company, options)

    # ------------------------------------------------------------------

    def _set_date(self, company, options):
        if company is None:
            raise CommandError("--date butuh --company.")

        go_live_date = self._parse_date(options["date"])

        row = LeaveGoLive.objects.filter(
            company=company,
            is_deleted=False,
        ).first()

        if options["dry_run"]:
            action = "diperbarui" if row else "dibuat"

            self.stdout.write(
                f"[dry-run] Go-live {company.code} akan {action} jadi "
                f"{go_live_date} (cut-off "
                f"{self._cutoff(go_live_date)}).",
            )

            return

        if row is None:
            row = LeaveGoLive(company=company)

        row.go_live_date = go_live_date
        row.is_active = True

        row.full_clean()
        row.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Go-live {company.code} = {go_live_date} "
                f"(cut-off {row.cutoff_date}).",
            ),
        )

        # Disebut sekali di sini supaya tidak perlu dicari di dokumen:
        # inilah akibat yang paling mudah tidak disadari, dan yang
        # paling mahal kalau salah paham.
        self.stdout.write(
            f"  Jatah {go_live_date.year} tidak lagi diterbitkan untuk "
            f"pegawai yang masuk sebelum {go_live_date}.",
        )
        self.stdout.write(
            "  Saldonya masuk lewat Leave Opening Balance.",
        )

    def _deactivate(self, company, options):
        if company is None:
            raise CommandError("--deactivate butuh --company.")

        row = LeaveGoLive.objects.filter(
            company=company,
            is_deleted=False,
        ).first()

        if row is None:
            self.stdout.write(f"{company.code} belum punya go-live.")

            return

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] Go-live {company.code} akan dimatikan.",
            )

            return

        row.is_active = False
        row.save(update_fields=["is_active", "updated_at"])

        self.stdout.write(
            self.style.WARNING(
                f"Go-live {company.code} dimatikan. Jatah kembali "
                f"dihitung dari Leave Policy.",
            ),
        )

    # ------------------------------------------------------------------

    def _status(self, company):
        queryset = LeaveGoLive.objects.filter(
            is_deleted=False,
        ).select_related("company")

        if company is not None:
            queryset = queryset.filter(company=company)

        rows = list(queryset)

        if not rows:
            self.stdout.write(
                "Belum ada company yang punya tanggal go-live cuti.",
            )

            return

        # Satu query untuk seluruh company, bukan dua per baris.
        counts = {
            item["employee__organization__company"]: item
            for item in (
                LeaveOpeningBalance.objects
                .filter(is_deleted=False)
                .values("employee__organization__company")
                .annotate(
                    draft=Count(
                        "id",
                        filter=Q(status=LeaveOpeningStatus.DRAFT),
                    ),
                    posted=Count(
                        "id",
                        filter=Q(status=LeaveOpeningStatus.POSTED),
                    ),
                )
            )
        }

        self.stdout.write("")
        self.stdout.write(
            "%-10s %-12s %-12s %7s %7s %8s  %s" % (
                "COMPANY",
                "GO-LIVE",
                "CUT-OFF",
                "DRAFT",
                "POSTED",
                "BELUM",
                "KEADAAN",
            ),
        )
        self.stdout.write("-" * 84)

        uncovered_detail: list[tuple[str, list]] = []

        for row in rows:
            stat = counts.get(row.company_id, {})

            draft = stat.get("draft", 0)
            posted = stat.get("posted", 0)

            uncovered = self._uncovered(row)

            if not row.is_active:
                state = "nonaktif"
            elif draft:
                state = f"{draft} baris menunggu Post"
            elif uncovered:
                state = f"{len(uncovered)} pegawai belum punya saldo awal"
            elif posted:
                state = "siap"
            else:
                state = "belum ada saldo awal"

            self.stdout.write(
                "%-10s %-12s %-12s %7d %7d %8d  %s" % (
                    row.company.code,
                    row.go_live_date,
                    row.cutoff_date,
                    draft,
                    posted,
                    len(uncovered),
                    state,
                ),
            )

            if uncovered:
                uncovered_detail.append((row.company.code, uncovered))

        self.stdout.write("")

        # Kolom BELUM adalah satu-satunya yang menangkap pegawai yang
        # **tidak ada di file sama sekali**, dan itu kelalaian yang
        # paling tidak berbunyi: barisnya tidak ditolak, tidak muncul di
        # laporan error, dan kartunya cuma berbunyi nol — tidak bisa
        # dibedakan dari orang yang saldonya memang habis. Nomornya
        # dicetak supaya bisa langsung dicocokkan dengan file klien.
        for code, employees in uncovered_detail:
            self.stdout.write(
                self.style.WARNING(
                    f"{code} — {len(employees)} pegawai sudah bekerja "
                    f"sebelum go-live tapi belum punya saldo awal:",
                ),
            )

            for number, name in employees[:20]:
                self.stdout.write(f"    {number:<10} {name}")

            if len(employees) > 20:
                self.stdout.write(
                    f"    ... dan {len(employees) - 20} lainnya.",
                )

            self.stdout.write(
                "  Nol hari pun harus diimport: \"habis terpakai di "
                "sistem lama\" dan \"belum diimport\" terlihat sama "
                "persis di kartu saldo.",
            )
            self.stdout.write("")

    @staticmethod
    def _uncovered(go_live) -> list[tuple[str, str]]:
        """
        Pegawai yang sudah bekerja sebelum go-live tapi tidak punya satu
        pun baris saldo awal.

        Batasnya sama persis dengan `LeaveGoLiveResolver.owns_year`:
        `join_date < go_live_date`. Yang masuk sesudahnya memang tidak
        perlu saldo awal — jatahnya dihitung dari policy seperti biasa,
        dan mendaftarnya di sini cuma membuat daftar ini berisik lalu
        berhenti dibaca orang.
        """
        from apps.hr.models import Employee

        queryset = (
            Employee.objects
            .filter(
                is_deleted=False,
                is_active=True,
                organization__company_id=go_live.company_id,
                employment__join_date__lt=go_live.go_live_date,
            )
            .exclude(
                leave_opening_balances__is_deleted=False,
            )
            .order_by("employee_number")
            .values_list("employee_number", "first_name", "last_name")
        )

        return [
            (number, f"{first} {last}".strip())
            for number, first, last in queryset
        ]

    # ------------------------------------------------------------------

    def _post(self, company, options):
        queryset = (
            LeaveOpeningBalance.objects
            .filter(
                status=LeaveOpeningStatus.DRAFT,
                is_deleted=False,
            )
            .select_related("employee", "leave_type")
        )

        if company is not None:
            queryset = queryset.filter(
                employee__organization__company=company,
            )

        total = queryset.count()

        if not total:
            self.stdout.write("Tidak ada saldo awal berstatus draft.")

            return

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] {total} saldo awal akan di-post.",
            )

            for row in queryset[:20]:
                self.stdout.write(
                    "  %-10s %-8s %6s hari" % (
                        row.employee.employee_number,
                        row.leave_type.code,
                        row.days,
                    ),
                )

            if total > 20:
                self.stdout.write(f"  ... dan {total - 20} lainnya.")

            return

        # `user=None`: perintah manajemen tidak punya pengguna
        # terautentikasi, dan jejak audit memang sengaja tidak mencatat
        # mutasi tanpa pengguna — lihat catatan di `BaseService._audit`.
        result = LeaveOpeningBalanceService.post_many(
            queryset=queryset,
            user=None,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{result['posted']} saldo awal di-post.",
            ),
        )

        for failure in result["failures"]:
            self.stdout.write(
                self.style.ERROR(
                    f"  {failure['employee']}: {failure['message']}",
                ),
            )

    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(value: str) -> date:
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise CommandError(
                f"Tanggal '{value}' tidak bisa dibaca. Pakai "
                f"YYYY-MM-DD.",
            ) from None

    @staticmethod
    def _cutoff(value: date) -> date:
        from datetime import timedelta

        return value - timedelta(days=1)
