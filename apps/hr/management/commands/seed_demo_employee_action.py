from django.core.management.base import BaseCommand

from apps.hr.seeds.demo_employee_actions import run


class Command(BaseCommand):
    help = (
        "Seed dokumen Employee Action data uji: perpanjangan kontrak, "
        "pengangkatan karyawan tetap, satu yang menunggu persetujuan, "
        "dan satu draft. Butuh seed_demo_workforce + seed_workflows "
        "lebih dulu. Aman diulang."
    )

    def handle(self, *args, **options):
        result = run(log=self.stdout.write)

        self.stdout.write(
            self.style.SUCCESS(
                f"Employee Action data uji: {result['created']} dibuat "
                f"({result['applied']} diterapkan, "
                f"{result['submitted']} menunggu, "
                f"{result['drafts']} draft), "
                f"{result['removed']} dokumen lama dibuang."
            )
        )

        if result["missing"]:
            self.stdout.write(
                self.style.WARNING(
                    "Pegawai belum ada atau belum punya akun: "
                    + ", ".join(result["missing"])
                    + " — jalankan seed_demo_workforce dulu."
                )
            )

        for note in result["skipped"]:
            self.stdout.write(self.style.WARNING(f"  ! {note}"))
