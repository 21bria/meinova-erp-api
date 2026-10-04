"""
Pemeriksaan kebersihan kewenangan per tenant. **Read-only, permanen.**

Menggantikan `audit_legacy_retirement` — bukan sebagai penerus namanya
melainkan sebagai bagiannya yang tidak kedaluwarsa. Yang lama menjawab
"apakah tenant ini sudah dipindahkan dari skema cakupan lama?", dan
pertanyaan itu berhenti berarti begitu skemanya dihapus. Yang di sini
menjawab pertanyaan yang tidak punya tanggal kedaluwarsa: **apakah ada
penugasan di tenant ini yang kewenangannya tidak menyatakan apa pun?**

Keadaan yang dicarinya bisa lahir besok dari kode baru; lihat
`apps.accounts.services.authority_hygiene` untuk daftarnya dan alasan
tiap butirnya.

Keluar dengan status bukan-nol kalau ada temuan, jadi ia bisa dipasang
sebagai gerbang CI atau dijalankan berkala. Ia **tidak memperbaiki
apa pun**: memperbaiki berarti menebak WHERE seseorang.
"""

from django.core.management.base import BaseCommand
from django_tenants.utils import get_tenant_model, schema_context

from apps.accounts.services.authority_hygiene import (
    authority_hygiene,
    is_clean,
)


# Judul tiap temuan, dan kenapa ia jadi temuan — dicetak apa adanya
# supaya yang membaca keluarannya tidak perlu membuka kode dulu.
FINDINGS = (
    ("blank_authority",
     "kewenangan kosong (pemegangnya tidak melihat apa pun)"),
    ("explicit_without_rows",
     "EXPLICIT tanpa satu pun baris (tanpa kewenangan — pastikan disengaja)"),
    ("placement_without_level",
     "PLACEMENT tanpa tingkat organisasi"),
    ("malformed_rows",
     "baris kewenangan cacat (tipe tak dikenal, atau id kosong)"),
    ("rows_on_non_explicit_mode",
     "baris kewenangan pada mode yang tidak membacanya"),
)


class Command(BaseCommand):
    help = (
        "Pemeriksaan read-only kebersihan kewenangan RoleAssignment di "
        "tiap tenant."
    )

    def add_arguments(self, parser):
        parser.add_argument("--schema", default=None)

        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help="Jumlah contoh yang dicetak per temuan.",
        )

    def handle(self, *args, **options):
        tenants = get_tenant_model().objects.exclude(schema_name="public")

        if options["schema"]:
            tenants = tenants.filter(schema_name=options["schema"])

        tenants = list(tenants.order_by("schema_name"))

        if not tenants:
            self.stderr.write(self.style.ERROR("Tidak ada tenant."))

            raise SystemExit(1)

        dirty: list[str] = []

        for tenant in tenants:
            with schema_context(tenant.schema_name):
                if not self._one(tenant.schema_name, options["limit"]):
                    dirty.append(tenant.schema_name)

        self.stdout.write(f"\n{'=' * 78}\nRINGKASAN\n{'=' * 78}")

        for tenant in tenants:
            style = (
                self.style.WARNING if tenant.schema_name in dirty
                else self.style.SUCCESS
            )

            verdict = "ADA TEMUAN" if tenant.schema_name in dirty else "BERSIH"

            self.stdout.write(style(f"  {tenant.schema_name:24} {verdict}"))

        if dirty:
            self.stderr.write(
                self.style.ERROR(
                    f"\n{len(dirty)} tenant punya temuan: "
                    + ", ".join(dirty)
                )
            )

            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSeluruh {len(tenants)} tenant bersih."
            )
        )

    # ------------------------------------------------------------------

    def _one(self, schema: str, limit: int) -> bool:
        report = authority_hygiene()

        self.stdout.write(f"\n{'-' * 78}\n{schema}\n{'-' * 78}")

        self.stdout.write(
            f"  penugasan          : {report['assignments']}\n"
            f"  baris kewenangan   : {report['authority_rows']}"
        )

        for key, label in FINDINGS:
            rows = report[key]

            if not rows:
                continue

            self.stdout.write(
                self.style.WARNING(f"\n  {len(rows)} {label}:"))

            for row in rows[:limit]:
                self.stdout.write(f"    - {self._describe(row)}")

            if len(rows) > limit:
                self.stdout.write(f"    ... dan {len(rows) - limit} lagi")

        clean = is_clean(report)

        if clean:
            self.stdout.write(self.style.SUCCESS("\n  Bersih."))

        return clean

    @staticmethod
    def _describe(row) -> str:
        """Satu baris, dua bentuk objek: penugasan atau baris kewenangan."""
        assignment = getattr(row, "assignment", row)

        who = f"{assignment.user} / {assignment.role}"

        if assignment is row:
            return (
                f"{who} [{assignment.authority_mode or 'kosong'}"
                f"{'/' + assignment.authority_level if assignment.authority_level else ''}]"
            )

        return f"{who} -> {row.resource_type}:{row.resource_id}"
