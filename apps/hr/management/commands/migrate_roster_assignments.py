"""
Memetakan pegawai roster lama ke Roster Policy.

Kenapa perintah, bukan data migration
-------------------------------------
Karena pemetaannya bisa **gagal dengan benar**. Sejak satu site boleh
punya beberapa policy, "policy dengan pola 42/14 di Gebe" tidak lagi
punya jawaban tunggal — dan menebak salah satunya berarti sebagian
pegawai mendapat jadwal dari aturan yang tidak pernah dipilih siapa pun.

Perintah ini melaporkan per pegawai policy mana yang dipilih dan
kenapa, lalu **melewati** yang tidak bisa dipastikan. Yang dilewati
tetap terbaca sebagai pegawai non-roster sampai ada yang memilihkan
policy-nya dari layar — keadaan yang jujur, bukan tebakan yang terlihat
seperti kepastian.

Aman diulang: pegawai yang sudah punya policy tidak disentuh.

    python manage.py tenant_command migrate_roster_assignments \\
        --schema=demo [--dry-run]
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.administration.models import RosterPolicy
from apps.hr.models import EmploymentAssignment


class Command(BaseCommand):
    help = (
        "Memetakan pegawai ber-Roster Crew ke Roster Policy yang polanya "
        "cocok. Aman diulang."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tampilkan hasilnya tanpa menyimpan.",
        )

        parser.add_argument(
            "--verbose-rows",
            action="store_true",
            help="Cetak satu baris per pegawai.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        verbose = options["verbose_rows"]

        assignments = (
            EmploymentAssignment.objects
            .filter(
                is_deleted=False,
                roster_crew__isnull=False,
                roster_policy__isnull=True,
            )
            .select_related(
                "employee",
                "employee__organization",
                "roster_crew",
                "roster_crew__work_schedule",
            )
            .order_by("employee__employee_number")
        )

        policies = list(
            RosterPolicy.objects
            .filter(
                is_deleted=False,
                is_active=True,
                cycle_work_days__isnull=False,
                cycle_off_days__isnull=False,
            )
            .select_related("company", "location")
        )

        if not policies:
            self.stdout.write(
                self.style.ERROR(
                    "Belum ada Roster Policy yang punya pola siklus. "
                    "Jalankan seed_roster_policy dulu."
                )
            )

            return

        matched = 0
        skipped = 0
        ambiguous = 0

        with transaction.atomic():
            for assignment in assignments:
                employee = assignment.employee
                schedule = assignment.roster_crew.work_schedule

                pattern = (
                    schedule.cycle_work_days,
                    schedule.cycle_off_days,
                )

                organization = getattr(employee, "organization", None)

                company_id = getattr(organization, "company_id", None)
                location_id = getattr(organization, "location_id", None)

                candidates = [
                    policy
                    for policy in policies
                    if (policy.cycle_work_days, policy.cycle_off_days)
                    == pattern
                    and (
                        not policy.company_id
                        or policy.company_id == company_id
                    )
                    and (
                        not policy.location_id
                        or policy.location_id == location_id
                    )
                ]

                if not candidates:
                    skipped += 1

                    self.stdout.write(
                        self.style.WARNING(
                            f"  {employee.employee_number}: tidak ada "
                            f"policy berpola {pattern[0]}/{pattern[1]} "
                            "untuk penempatannya — dilewati."
                        )
                    )

                    continue

                # Lebih dari satu yang cocok: yang paling khusus menang,
                # dan kalau masih seri, yang bertanda bawaan. Kalau dua
                # duanya seri juga, itu ambigu sungguhan — dan menebak
                # berarti sebagian pegawai memakai aturan yang tidak
                # pernah dipilih siapa pun.
                candidates.sort(
                    key=lambda policy: (
                        policy.specificity,
                        policy.is_default,
                    ),
                    reverse=True,
                )

                best = candidates[0]

                if len(candidates) > 1:
                    runner_up = candidates[1]

                    tied = (
                        best.specificity == runner_up.specificity
                        and best.is_default == runner_up.is_default
                    )

                    if tied:
                        ambiguous += 1

                        self.stdout.write(
                            self.style.WARNING(
                                f"  {employee.employee_number}: "
                                f"{best.code} dan {runner_up.code} "
                                "sama-sama cocok dan sama khususnya — "
                                "dilewati, pilih manual dari form "
                                "pegawai."
                            )
                        )

                        continue

                anchor = (
                    assignment.roster_start_override
                    or assignment.roster_crew.cycle_start_date
                )

                if verbose:
                    self.stdout.write(
                        f"  {employee.employee_number}: {best.code} "
                        f"({pattern[0]}/{pattern[1]}), jangkar {anchor}"
                    )

                if not dry_run:
                    assignment.roster_policy = best

                    if assignment.roster_cycle_start is None:
                        assignment.roster_cycle_start = anchor

                    assignment.save(
                        update_fields=[
                            "roster_policy",
                            "roster_cycle_start",
                            "updated_at",
                        ],
                    )

                matched += 1

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                f"{matched} pegawai dipetakan"
                + (" (dry-run, tidak disimpan)" if dry_run else "")
                + f", {skipped} tanpa policy yang cocok, "
                f"{ambiguous} ambigu."
            )
        )

        if skipped or ambiguous:
            self.stdout.write(
                "Pegawai yang dilewati tetap terbaca sebagai non-roster "
                "sampai policy-nya dipilih dari form Employee."
            )
