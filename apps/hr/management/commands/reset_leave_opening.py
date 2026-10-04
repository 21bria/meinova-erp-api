"""
Membuang dokumen saldo awal cuti supaya import bisa diuji dari nol.

Kenapa perintah tersendiri, bukan bagian `reset_demo_data`: yang itu
membuang **seluruh** data uji termasuk 26 pegawainya, sementara yang
dibutuhkan saat menguji import berkali-kali cuma dokumennya — pegawai,
policy, dan tanggal go-live harus tetap berdiri, kalau tidak setiap
putaran uji dimulai dengan membangun ulang tenant.

Hard delete, dan itu disengaja. Baris bertanda terhapus tidak
menghalangi import berikutnya (constraint uniknya dikondisikan ke
`is_deleted=False`), tapi ia tetap menempel di tabel tanpa pernah
terbaca siapa pun — dan yang sedang diuji justru apakah satu berkas
menghasilkan tepat satu baris per pegawai.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.hr.api.leave_opening.services import LeaveOpeningBalanceService
from apps.hr.models import (
    LeaveBalance,
    LeaveOpeningBalance,
    LeaveOpeningStatus,
)


class Command(BaseCommand):
    help = (
        "Membuang dokumen saldo awal cuti (LeaveOpeningBalance) dan "
        "menyinkronkan ulang kartu saldo yang terpengaruh, supaya import "
        "bisa diuji dari keadaan bersih."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            help=(
                "Kode perusahaan. Dikosongkan = seluruh tenant."
            ),
        )

        parser.add_argument(
            "--employee",
            action="append",
            default=[],
            help=(
                "Nomor pegawai, boleh diulang. Dikosongkan = semua "
                "pegawai yang punya dokumen saldo awal."
            ),
        )

        parser.add_argument(
            "--with-balances",
            action="store_true",
            help=(
                "Buang juga kartu saldo (LeaveBalance) pegawai yang "
                "cocok, supaya layar Leave Balance benar-benar kosong "
                "sebelum import diuji. Kartunya terbit ulang sendiri "
                "lewat `generate_leave_balances` atau saat penempatan "
                "kepegawaian disimpan."
            ),
        )

        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Lanjutkan walau ada kartu yang membawa used / "
                "adjustment / carried_over bukan nol. Tanpa ini kartu "
                "seperti itu menghentikan perintahnya."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Hanya menampilkan yang akan dibuang.",
        )

    def handle(self, *args, **options):
        company = options.get("company")
        employees = options.get("employee") or []

        def scoped(queryset):
            """Penyaring yang sama untuk dokumen dan kartu."""
            if company:
                queryset = queryset.filter(
                    employee__organization__company__code=company,
                )

            if employees:
                queryset = queryset.filter(
                    employee__employee_number__in=employees,
                )

            return queryset

        # Manager bawaan memang memuat baris ber-`is_deleted=True`:
        # penyaringan soft delete di codebase ini selalu ditulis
        # eksplisit. Di sini itu yang dibutuhkan — baris terhapus pun
        # harus ikut hilang.
        documents = scoped(
            LeaveOpeningBalance.objects
            .select_related("employee", "leave_type")
        )

        rows = list(documents.order_by("employee__employee_number"))

        with_balances = options["with_balances"]

        cards = (
            scoped(
                LeaveBalance.objects.select_related("employee", "leave_type")
            )
            if with_balances
            else LeaveBalance.objects.none()
        )

        card_rows = list(cards.order_by("year", "employee__employee_number"))

        if not rows and not card_rows:
            self.stdout.write(
                self.style.WARNING("Tidak ada yang cocok untuk dibuang.")
            )

            return

        if rows:
            self.stdout.write(f"{len(rows)} dokumen saldo awal:")

            for row in rows:
                flag = " (sudah terhapus)" if row.is_deleted else ""

                self.stdout.write(
                    f"  {row.employee.employee_number:<10} "
                    f"{row.leave_type.code if row.leave_type else '-':<10} "
                    f"{row.days} hari  {row.status}  "
                    f"berlaku {row.opening_date}{flag}"
                )
        else:
            self.stdout.write("Tidak ada dokumen saldo awal.")

        # Kartu yang membawa angka yang **tidak bisa diterbitkan ulang**
        # adalah satu-satunya alasan perintah ini boleh berhenti.
        # `entitlement` dan `opening_balance` dua-duanya turunan —
        # yang pertama dari policy, yang kedua dari dokumen — jadi
        # membuangnya tidak menghilangkan apa pun. `adjustment` diketik
        # orang dan tidak punya sumber lain; `used` dan `carried_over`
        # baru pulih setelah ada yang menyentuh catatan cutinya atau
        # menjalankan carry over lagi.
        risky = [
            card for card in card_rows
            if card.used or card.adjustment or card.carried_over
        ]

        if with_balances:
            self.stdout.write(
                f"\n{len(card_rows)} kartu saldo (LeaveBalance):"
            )

            summary = {}

            for card in card_rows:
                key = (card.year, card.leave_type.code)
                summary[key] = summary.get(key, 0) + 1

            for (year, code), count in sorted(summary.items()):
                self.stdout.write(f"  {year} {code:<10} {count} kartu")

            if risky:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n  {len(risky)} kartu membawa angka yang tidak "
                        f"terbit ulang sendiri:"
                    )
                )

                for card in risky[:10]:
                    self.stdout.write(
                        f"    {card.employee.employee_number:<10} "
                        f"{card.leave_type.code:<10} {card.year}  "
                        f"used={card.used} adj={card.adjustment} "
                        f"carried={card.carried_over}"
                    )

                if len(risky) > 10:
                    self.stdout.write(
                        f"    ... dan {len(risky) - 10} lainnya."
                    )

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING("\n--dry-run: tidak ada yang dibuang.")
            )

            return

        if risky and not options["force"]:
            self.stderr.write(
                self.style.ERROR(
                    f"\nDihentikan: {len(risky)} kartu membawa used / "
                    f"adjustment / carried_over bukan nol, dan angka itu "
                    f"tidak bisa diterbitkan ulang perintah mana pun. "
                    f"Pakai --force kalau memang mau dibuang."
                )
            )

            return

        # Pasangan (pegawai, jenis cuti, tahun) dicatat **sebelum**
        # barisnya hilang: sesudah itu tidak ada lagi yang menghubungkan
        # kartu saldonya ke dokumen yang baru dibuang.
        pairs = {
            (row.employee_id, row.leave_type_id, row.year): row
            for row in rows
        }

        with transaction.atomic():
            # Unpost dulu lewat service, bukan langsung delete. Yang
            # POSTED sudah menyumbang angkanya ke kartu saldo dan sudah
            # memegang tahunnya di kalkulator jatah; membuang barisnya
            # tanpa melewati jalur resmi meninggalkan kartu yang masih
            # berbunyi angka lama sampai ada yang kebetulan
            # menyinkronkannya.
            for row in rows:
                if row.status == LeaveOpeningStatus.POSTED:
                    LeaveOpeningBalanceService.unpost(instance=row)

            deleted_documents = documents.delete()[0] if rows else 0

            if with_balances:
                # Kartunya dibuang, jadi tidak ada yang perlu
                # disinkronkan — menyinkronkan lebih dulu cuma
                # menerbitkan baris yang detik berikutnya dihapus.
                deleted_cards = cards.delete()[0]

                synced = 0
            else:
                deleted_cards = 0

                # Disinkronkan ulang walau `unpost` sudah melakukannya:
                # baris DRAFT tidak pernah lewat unpost, dan kartu yang
                # kebetulan sudah benar tidak dirugikan oleh penjumlahan
                # ulang. Penjumlahan ulang tidak bisa hanyut.
                for (_, _, year), row in sorted(
                    pairs.items(), key=lambda item: item[0]
                ):
                    LeaveOpeningBalanceService.sync_balance(
                        employee=row.employee,
                        leave_type=row.leave_type,
                        year=year,
                    )

                    LeaveOpeningBalanceService.sync_entitlement(
                        employee=row.employee,
                        leave_type=row.leave_type,
                        year=year,
                    )

                synced = len(pairs)

        parts = [f"{deleted_documents} dokumen saldo awal dibuang"]

        if with_balances:
            parts.append(f"{deleted_cards} kartu saldo dibuang")
        elif synced:
            parts.append(f"{synced} kartu saldo disinkronkan ulang")

        self.stdout.write(self.style.SUCCESS("\n" + ", ".join(parts) + "."))

        if with_balances:
            self.stdout.write(
                "Kartunya terbit ulang lewat "
                "`generate_leave_balances --year=<tahun>`, atau sendiri "
                "saat Post saldo awal / penyimpanan penempatan "
                "kepegawaian berikutnya."
            )
