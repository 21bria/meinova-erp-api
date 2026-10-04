from django.core.management.base import BaseCommand

from apps.helpcenter.seeds.help_center import seed


class Command(BaseCommand):
    help = (
        "Seed isi panduan bawaan Help Center. Aman diulang — artikel "
        "yang sudah disunting orang dilewati, tidak ditimpa."
    )

    def handle(self, *args, **options):
        result = seed()

        message = (
            f"Help Center seed selesai: "
            f"{result['categories']} kategori, "
            f"{result['articles_created']} artikel baru, "
            f"{result['articles_updated']} diperbarui, "
            f"{result['articles_skipped']} dilewati (sudah disunting)."
        )

        self.stdout.write(self.style.SUCCESS(message))

        if result["drafts"]:
            self.stdout.write(
                self.style.WARNING(
                    "Draft (tidak tampil di halaman bantuan sampai "
                    "fiturnya rilis dan statusnya diubah jadi "
                    "Published): "
                    + ", ".join(result["drafts"])
                )
            )

        if result["missing_roles"]:
            self.stdout.write(
                self.style.WARNING(
                    "Role berikut belum ada, artikelnya diterbitkan "
                    "tanpa pembatasan role: "
                    + ", ".join(result["missing_roles"])
                    + " — jalankan seed_security_roles kalau memang "
                    "ingin dibatasi."
                )
            )
