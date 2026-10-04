"""
Isi tenant peragaan dengan **pegawai saja**.

Dipakai untuk tenant yang transaksinya mau diisi tangan: kartu
pegawainya lengkap sampai rekening bank, keluarga, pendidikan, dan
payroll, tapi cuti, saldo, roster, presensi, dan seluruh dokumen tetap
kosong. Lihat docstring `apps/hr/seeds/demo_employees.py` untuk bedanya
dengan `seed_demo_workforce`.
"""

from django.core.management.base import BaseCommand

from apps.hr.seeds import demo_employees


class Command(BaseCommand):
    help = (
        "Seed pegawai peragaan (HO / site POH / site lokal) lengkap "
        "seluruh tab, tanpa satu pun transaksi. "
        "Contoh: tenant_command seed_demo_employees --schema=demo"
    )

    def handle(self, *args, **options):
        result = demo_employees.seed(log=self.stdout.write)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nPegawai peragaan — {result['company']}"
            )
        )

        for label, value in [
            ("Kantor pusat", result["head_office"]),
            ("Site — Point of Hire", result["site_poh"]),
            ("Site — tenaga lokal", result["site_local"]),
            ("Total pegawai", result["total"]),
            ("Akun pengguna", result["accounts"]),
        ]:
            self.stdout.write(f"  {label:<22}{value:>3}")

        records = result["records"]

        self.stdout.write(
            "\n  Isi tab: "
            + ", ".join(
                f"{label} {value}"
                for label, value in records.items()
                if value
            )
        )

        # --------------------------------------------------------------
        # Susunan site
        # --------------------------------------------------------------
        #
        # Dicetak per department **dan** per section karena dua-duanya
        # menentukan ke meja siapa dokumen site mendarat: step pertama
        # alur site dicari per section, turunan pertamanya per
        # department. Jumlah pegawai saja tidak memberi tahu apa pun
        # tentang itu.

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "\nSusunan site Sagea (POH = didatangkan, LOK = tenaga lokal)"
            )
        )

        for department, bucket in sorted(result["site_breakdown"].items()):
            self.stdout.write(
                self.style.HTTP_INFO(
                    f"  {department:<30} {bucket['total']:>2} orang "
                    f"({bucket['poh']} POH / {bucket['local']} lokal)"
                )
            )

            for section, row in sorted(bucket["sections"].items()):
                self.stdout.write(
                    f"      └ {section:<24} {row['total']:>2} orang "
                    f"({row['poh']} POH / {row['local']} lokal)"
                )

        self.stdout.write(
            f"\n  Kalender kantor: {result['office_calendar']}"
            f"   ·   Kalender site: {result['site_calendar']}"
        )

        for warning in result["warnings"]:
            self.stdout.write(self.style.WARNING(f"  ! {warning}"))

        self.stdout.write(
            self.style.SUCCESS(
                "\nSelesai. Cuti, saldo, roster, dan presensi sengaja "
                "dibiarkan kosong — lihat "
                "docs/09-business-flows/Employee-Onboarding-Flow.md "
                "untuk urutan pengisiannya."
            )
        )
