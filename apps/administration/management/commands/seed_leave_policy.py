from django.core.management.base import BaseCommand

from apps.administration.seeds.reference.leave_policy import seed


class Command(BaseCommand):
    help = "Seed kebijakan cuti bawaan. Aman diulang."

    def handle(self, *args, **options):
        result = seed()

        message = (
            f"Leave policy seed selesai: {result['policies']} aturan "
            f"({result['balance_policies']} bersaldo, "
            f"{result['non_balance_policies']} per kejadian)."
        )

        if result["missing_leave_types"]:
            message += (
                " Leave Type belum ada: "
                + ", ".join(result["missing_leave_types"])
                + " — jalankan seed_administration --only=hr-reference."
            )

        self.stdout.write(self.style.SUCCESS(message))
