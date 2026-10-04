"""
`RosterPolicy` jadi pembawa pola siklus, aturan travel per arah, dan
aturan rotation credit.

Tiga hal yang perlu dijelaskan:

1. **`uniq_active_rosterpolicy_target` dicabut.** Constraint itu
   membatasi satu policy per site, dan itu menghalangi `GBE-6-2` dan
   `GBE-8-2` hidup berdampingan. Penjagaan yang hilang diganti
   `uniq_active_rosterpolicy_default` — banyak policy boleh, satu
   bawaan.

2. **`default_travel_days` (total PP) dipecah jadi out/in.** Pemetaannya
   `out = ceil(t/2)`, `in = floor(t/2)` — persis pembulatan yang selama
   ini dilakukan generator (`RotationPeriod.travel_days`), jadi tidak
   ada satu pun jadwal existing yang bergeser sehari.

3. **Pola siklus TIDAK dikarang.** Baris yang sudah ada dibiarkan tanpa
   `cycle_work_days`/`cycle_off_days`; ia tetap sah sebagai aturan site.
   Mengisinya dengan tebakan 42/14 berarti menaruh angka yang tidak
   pernah divalidasi siapa pun di master yang dibaca orang sebagai
   kebenaran.
"""

from django.db import migrations, models
import django.db.models.deletion


def split_travel_days(apps, schema_editor):
    """
    Memecah total pulang-pergi jadi dua arah, dan menandai baris yang
    sudah ada sebagai bawaan site.

    Constraint lama menjamin cuma ada satu policy per site, jadi
    menandai semuanya `is_default` tidak bisa melanggar constraint baru.
    """
    RosterPolicy = apps.get_model("administration", "RosterPolicy")
    RosterTravelDay = apps.get_model("administration", "RosterTravelDay")

    for policy in RosterPolicy.objects.all():
        total = policy.default_travel_days or 0

        policy.default_travel_out_days = -(-total // 2)
        policy.default_travel_in_days = total // 2
        policy.is_default = True

        policy.save(
            update_fields=[
                "default_travel_out_days",
                "default_travel_in_days",
                "is_default",
            ],
        )

    for row in RosterTravelDay.objects.all():
        total = row.travel_days or 0

        row.travel_out_days = -(-total // 2)
        row.travel_in_days = total // 2

        row.save(update_fields=["travel_out_days", "travel_in_days"])


def merge_travel_days(apps, schema_editor):
    """Balik arah: dua angka digabung lagi jadi total."""
    RosterPolicy = apps.get_model("administration", "RosterPolicy")
    RosterTravelDay = apps.get_model("administration", "RosterTravelDay")

    for policy in RosterPolicy.objects.all():
        policy.default_travel_days = (
            (policy.default_travel_out_days or 0)
            + (policy.default_travel_in_days or 0)
        )

        policy.save(update_fields=["default_travel_days"])

    for row in RosterTravelDay.objects.all():
        row.travel_days = (
            (row.travel_out_days or 0) + (row.travel_in_days or 0)
        )

        row.save(update_fields=["travel_days"])


class Migration(migrations.Migration):

    dependencies = [
        ("administration", "0025_employeeactionpolicy"),
    ]

    operations = [
        # --------------------------------------------------------------
        # Pola siklus
        # --------------------------------------------------------------
        migrations.AddField(
            model_name="rosterpolicy",
            name="is_default",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Aturan bawaan untuk site ini. Hanya boleh satu per site."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="cycle_work_days",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                help_text=(
                    "Jumlah hari blok kerja — 42 untuk pola 6:2, 56 untuk "
                    "8:2. Dikosongkan = aturan site saja, tidak bisa "
                    "ditugaskan ke pegawai."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="cycle_off_days",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                help_text="Jumlah hari blok field break — 14 untuk 2 minggu.",
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="roster_start_basis",
            field=models.CharField(
                default="work_start",
                max_length=20,
                choices=[
                    ("work_start", "Work Start Date"),
                    ("site_arrival", "Site Arrival Date"),
                    ("travel_departure", "Travel Departure Date"),
                ],
                help_text=(
                    "Arti tanggal Current Cycle Start pegawai. Work Start = "
                    "hari pertama masuk kerja. Site Arrival = hari tiba di "
                    "site (perjalanan menuju site sudah dihitung On Site). "
                    "Travel Departure = hari berangkat dari Point of Hire."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="rolling_horizon_months",
            field=models.PositiveSmallIntegerField(
                default=12,
                help_text=(
                    "Jadwal digenerate sampai sekian bulan ke depan, lalu "
                    "diperpanjang berkala. 0 = ikut bawaan sistem."
                ),
            ),
        ),
        # --------------------------------------------------------------
        # Hari perjalanan per arah
        # --------------------------------------------------------------
        migrations.AddField(
            model_name="rosterpolicy",
            name="default_travel_out_days",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text=(
                    "Hari perjalanan site → Point of Hire (pulang), untuk "
                    "POH yang belum didaftarkan di tabel di bawah."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="default_travel_in_days",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text=(
                    "Hari perjalanan Point of Hire → site (berangkat), untuk "
                    "POH yang belum didaftarkan di tabel di bawah."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="travel_day_mode",
            field=models.CharField(
                default="fixed",
                max_length=20,
                choices=[
                    ("fixed", "Fixed (from policy)"),
                    ("actual", "Actual Itinerary"),
                ],
                help_text=(
                    "Fixed = jendela travel dari angka di atas. Actual "
                    "Itinerary = setelah Travel Request disetujui, "
                    "selisihnya dilaporkan sebagai usulan penyesuaian."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="travel_creates_segment",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Membuat baris Travel Out/Travel In di jadwal. "
                    "Dimatikan = hari perjalanan cuma jadi celah kalender."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="travel_out_counts_as_roster_day",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Hari perjalanan pulang dihitung sebagai hari on-site "
                    "di rekap. Tidak memendekkan blok kerja."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="travel_in_counts_as_roster_day",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Hari perjalanan berangkat dihitung sebagai hari on-site "
                    "di rekap. Tidak memendekkan blok kerja."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="count_transit_overnight",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Malam menginap di kota transit ikut dihitung sebagai "
                    "hari perjalanan saat membandingkan rencana dengan "
                    "itinerary."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="travel_variance_credit_eligible",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Selisih hari perjalanan aktual terhadap rencana boleh "
                    "jadi rotation credit. Bawaannya mati."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="travel_variance_credit_max_days",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text=(
                    "Batas hari selisih yang boleh dikonversi. 0 = tanpa "
                    "batas."
                ),
            ),
        ),
        # --------------------------------------------------------------
        # Rotation credit
        # --------------------------------------------------------------
        migrations.AddField(
            model_name="rosterpolicy",
            name="credit_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Site ini memakai rotation credit. Dimatikan = "
                    "kelebihan hari kerja tidak menghasilkan saldo apa pun."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="credit_rounding",
            field=models.CharField(
                default="floor",
                max_length=20,
                choices=[
                    ("floor", "Round Down"),
                    ("half_up", "Round Half Up"),
                    ("ceil", "Round Up"),
                    ("exact", "Exact (no rounding)"),
                ],
                help_text=(
                    "Cara membulatkan hasil konversi. Round Down + Carry "
                    "Remainder adalah pilihan yang paling bisa dijelaskan "
                    "ke pegawai."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="credit_carry_remainder",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Sisa hari yang belum genap jadi satu kredit disimpan "
                    "dan ikut dihitung pada konversi berikutnya, bukan "
                    "hangus. Hanya berlaku untuk Round Down."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="credit_max_balance_days",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=6,
                null=True,
                help_text="Plafon saldo. Dikosongkan = tanpa plafon.",
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="credit_expiry_months",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                help_text=(
                    "Kredit kedaluwarsa setelah sekian bulan. Dikosongkan = "
                    "tidak kedaluwarsa. Eksekusinya belum ada."
                ),
            ),
        ),
        migrations.AddField(
            model_name="rosterpolicy",
            name="credit_allow_negative",
            field=models.BooleanField(
                default=False,
                help_text="Saldo boleh menembus nol.",
            ),
        ),
        # --------------------------------------------------------------
        # Travel day per POH: pecah arah
        # --------------------------------------------------------------
        migrations.AddField(
            model_name="rostertravelday",
            name="travel_out_days",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text="Hari perjalanan site → Point of Hire (pulang).",
            ),
        ),
        migrations.AddField(
            model_name="rostertravelday",
            name="travel_in_days",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text=(
                    "Hari perjalanan Point of Hire → site (berangkat)."
                ),
            ),
        ),
        # --------------------------------------------------------------
        # Pindahkan datanya, baru buang kolom lamanya
        # --------------------------------------------------------------
        migrations.RunPython(split_travel_days, merge_travel_days),
        migrations.RemoveField(
            model_name="rosterpolicy",
            name="default_travel_days",
        ),
        migrations.RemoveField(
            model_name="rostertravelday",
            name="travel_days",
        ),
        # --------------------------------------------------------------
        # Constraint & index
        # --------------------------------------------------------------
        migrations.RemoveConstraint(
            model_name="rosterpolicy",
            name="uniq_active_rosterpolicy_target",
        ),
        migrations.AddConstraint(
            model_name="rosterpolicy",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("is_deleted", False),
                    ("is_default", True),
                ),
                fields=("company", "location"),
                name="uniq_active_rosterpolicy_default",
            ),
        ),
        migrations.AddIndex(
            model_name="rosterpolicy",
            index=models.Index(
                fields=["company", "location", "is_default"],
                name="idx_roster_policy_scope",
            ),
        ),
        migrations.AlterField(
            model_name="rosterpolicy",
            name="conversion_ratio",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=5,
                null=True,
                help_text=(
                    "Perbandingan hari kerja : hari off. Dikosongkan = "
                    "dihitung sendiri dari pola roster (56:14 = 4). Diisi "
                    "hanya kalau perusahaan memakai angka yang berbeda dari "
                    "polanya."
                ),
            ),
        ),
    ]
