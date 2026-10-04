"""
Schema UI Overtime Group.

Sebelum keputusan #4 layar ini tidak punya schema sama sekali dan
sepenuhnya hasil introspeksi — artinya kolom `tier_basis` akan terbit
sebagai `daily`/`monthly` mentah begitu ia lahir. Schema ini yang
menahannya, sekaligus memberi nama manusia pada kolom yang sudah lama
ada.
"""

from apps.framework.builders import field, ui
from apps.payroll.models import OvertimeTierBasis


# Kalimat, bukan nilai enumnya. Yang membacanya orang HR yang sedang
# memutuskan, bukan yang menulis kodenya.
TIER_BASIS_OPTIONS = [
    {
        "label": "Per overtime day - each day restarts at the first tier",
        "value": OvertimeTierBasis.DAILY,
    },
    {
        "label": "Total hours per month - all hours tiered once",
        "value": OvertimeTierBasis.MONTHLY,
    },
]

TIER_BASIS_PLACEHOLDER = "Not set - required when using tiers"


OVERTIME_GROUP_SCHEMA = {
    "module": "payroll/overtime-groups",
    "name": "OvertimeGroup",
    "label": "Overtime Group",
    "endpoint": "/api/payroll/overtime-groups/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Overtime Groups",
            description=(
                "Aturan upah lembur per kelompok pegawai. Tingkat "
                "pengalinya dikelola di layar Overtime Tiers."
            ),
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            export=True,
        ),
    },

    "fields": {
        "code": field.text(
            label="Code",
            placeholder="e.g. STANDARD",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=10,
        ),
        "name": field.text(
            label="Name",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=20,
        ),
        "hourly_divisor": field.decimal(
            label="Hourly Divisor",
            min=0,
            decimal_places=2,
            default=173,
            required=True,
            table=True,
            order=30,
            help_text=(
                "Pembagi gaji pokok sebulan untuk mendapatkan upah per "
                "jam. Bawaan 173 (Kepmenaker 102/2004). Gaji yang "
                "dipakai selalu gaji sebulan penuh, bukan yang sudah "
                "diprorata."
            ),
        ),
        "hourly_multiplier": field.decimal(
            label="Default Multiplier",
            min=0,
            decimal_places=2,
            default=1,
            required=True,
            table=True,
            order=40,
            help_text=(
                "Dipakai kalau kelompok ini belum punya tingkat. "
                "Diabaikan begitu ada tingkat yang aktif."
            ),
        ),
        "tier_basis": field.select(
            label="Tier Basis",
            options=TIER_BASIS_OPTIONS,
            placeholder=TIER_BASIS_PLACEHOLDER,
            default="",
            required=False,
            table=True,
            display_key="tier_basis_label",
            filter=True,
            layout="full",
            order=50,
            help_text=(
                "Wajib diisi kalau kelompok ini memakai tingkat. "
                "Keduanya lazim dan menghasilkan angka yang berbeda "
                "untuk pegawai yang sama, jadi sistem tidak memilihkan."
            ),
        ),
        "maximum_hours_per_day": field.decimal(
            label="Max Hours / Day",
            min=0,
            decimal_places=2,
            table=False,
            order=60,
        ),
        "maximum_hours_per_month": field.decimal(
            label="Max Hours / Month",
            min=0,
            decimal_places=2,
            table=False,
            order=70,
        ),
        "description": field.textarea(
            label="Description",
            rows=3,
            layout="full",
            table=False,
            order=80,
        ),
        "is_active": field.boolean(
            label="Active",
            default=True,
            table=True,
            filter=True,
            order=999,
        ),
    },
}
