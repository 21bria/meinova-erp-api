"""
Schema UI tingkat pengali lembur.

Layar tersendiri, **bukan tab di dalam Overtime Group**: halaman master
itu memakai editor dialog, dan mengubahnya jadi workspace bertab
berarti merombak layar master yang sudah berjalan. Pola yang sama
dipakai Allowance Component terhadap Allowance Template.
"""

from apps.framework.builders import field, ui


OVERTIME_GROUP_TIER_SCHEMA = {
    "module": "payroll/overtime-group-tiers",
    "name": "OvertimeGroupTier",
    "label": "Overtime Tier",
    "endpoint": "/api/payroll/overtime-group-tiers/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Overtime Tiers",
            description=(
                "Tingkat pengali di dalam sebuah Overtime Group. "
                "Group-nya sendiri tetap dikelola di layar Overtime "
                "Groups."
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
        "group": field.lookup(
            label="Overtime Group",
            lookup_endpoint="/api/payroll/overtime-groups/lookup/",
            display_key="group_name",
            required=True,
            table=True,
            filter=True,
            search=True,
            sortable=True,
            order=10,
        ),
        "sequence": field.integer(
            label="Order",
            default=1,
            required=True,
            table=True,
            sortable=True,
            order=20,
            help_text=(
                "Urutan tingkat dibaca dari bawah ke atas. Tingkat "
                "pertama harus mulai dari jam 0."
            ),
        ),
        "hour_from": field.decimal(
            label="From Hour",
            min=0,
            decimal_places=2,
            required=True,
            table=True,
            # Kolomnya membaca rentangnya sebagai satu kalimat; dua
            # angka di dua kolom menyuruh orang menyusunnya sendiri.
            display_key="hour_range_label",
            order=30,
            help_text=(
                "Batas bawah jam lembur kumulatif, ikut terhitung. "
                "0 = mulai dari jam lembur pertama."
            ),
        ),
        "hour_to": field.decimal(
            label="To Hour",
            min=0,
            decimal_places=2,
            table=False,
            order=40,
            help_text=(
                "Dikosongkan berarti tingkat teratas — jam berapa pun "
                "di atas batas bawah memakai pengali ini."
            ),
        ),
        "multiplier": field.decimal(
            label="Multiplier",
            min=0,
            decimal_places=2,
            default=1,
            required=True,
            table=True,
            display_key="multiplier_label",
            order=50,
            help_text=(
                "Pengali upah per jam pada rentang ini, mis. 1,5. "
                "Angkanya kebijakan perusahaan — sistem tidak "
                "menentukannya."
            ),
        ),
        "description": field.textarea(
            label="Description",
            rows=2,
            layout="full",
            table=False,
            order=60,
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
