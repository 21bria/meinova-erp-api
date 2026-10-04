"""
Schema layar rotation credit.

Bentuknya **daftar transaksi**, bukan form saldo — dan itu inti
desainnya. Saldo adalah hasil penjumlahan; yang bisa dipertanggung-
jawabkan adalah barisnya. Karena itu layar ini tidak punya tombol Edit
maupun Delete: koreksi lewat Adjustment (+/−), pembatalan lewat
Reversal, dua-duanya baris baru yang menunjuk yang lama.
"""

from apps.framework.builders import action, field, ui


CREDIT_ENTRY_OPTIONS = [
    {"label": "Opening Balance", "value": "opening_balance"},
    {"label": "Earned", "value": "earned"},
    {"label": "Used", "value": "used"},
    {"label": "Adjustment (+)", "value": "adjustment_plus"},
    {"label": "Adjustment (−)", "value": "adjustment_minus"},
    {"label": "Expired", "value": "expired"},
    {"label": "Reversal", "value": "reversal"},
]


ROTATION_CREDIT_FIELDS = {
    "employee": field.lookup(
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        order=10,
    ),

    "entry_type": field.select(
        label="Entry Type",
        options=CREDIT_ENTRY_OPTIONS,
        display_key="entry_type_label",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "days": field.decimal(
        label="Days",
        required=True,
        table=True,
        sortable=True,
        decimal_places=2,
        max_digits=6,
        help_text=(
            "Selalu positif. Arahnya ditentukan Entry Type — "
            "pengurangan tidak pernah ditulis sebagai angka negatif."
        ),
        order=30,
    ),

    "effective_date": field.date(
        label="Effective Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text=(
            "Boleh mundur — saldo awal dari sistem lama berlaku sejak "
            "tanggal go-live, bukan sejak diketik."
        ),
        order=40,
    ),

    "transaction_date": field.date(
        label="Recorded On",
        required=False,
        table=True,
        sortable=True,
        read_only=True,
        display=True,
        order=45,
    ),

    "reason": field.textarea(
        label="Reason",
        required=False,
        rows=3,
        table=True,
        search=True,
        help_text=(
            "Wajib untuk penyesuaian, kedaluwarsa, dan pembalikan — "
            "saldo yang berubah tanpa alasan tidak bisa dijelaskan ke "
            "pegawainya."
        ),
        order=50,
    ),
}


ROTATION_CREDIT_DISPLAY_FIELDS = {
    "employee_number": field.text(
        # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
        # kanan tabel — lihat `column_after` di columns.mjs.
        column_after="employee",
        label="Employee No.",
        read_only=True,
        display=True,
        table=True,
        search=True,
        sortable=True,
        order=5,
    ),

    "signed_days": field.decimal(
        label="Effect",
        read_only=True,
        display=True,
        table=True,
        decimal_places=2,
        help_text=(
            "Kontribusi baris ini ke saldo. Pembalikan mengambil arah "
            "berlawanan dari yang dibatalkannya."
        ),
        order=35,
    ),

    "source_label": field.text(
        label="Source",
        read_only=True,
        display=True,
        table=True,
        order=55,
    ),

    "conversion_ratio": field.decimal(
        label="Ratio",
        read_only=True,
        display=True,
        table=True,
        decimal_places=2,
        order=60,
    ),

    "remainder_days": field.decimal(
        label="Carried",
        read_only=True,
        display=True,
        table=True,
        decimal_places=2,
        help_text=(
            "Hari kerja yang belum genap jadi satu kredit, dibawa ke "
            "konversi berikutnya."
        ),
        order=65,
    ),

    "reversed_by_label": field.text(
        label="Reversed By",
        read_only=True,
        display=True,
        table=True,
        order=70,
    ),
}


ROTATION_CREDIT_ACTIONS = [
    action.custom(
        "reverse",
        label="Reverse",
        icon="Undo2",
        variant="destructive",
        placement="secondary",
        modes=["edit", "detail"],
        endpoint="/api/hr/rotation-credits/{id}/reverse/",
        method="post",
        refresh=True,
        # Baris pembalikan tidak bisa dibalikkan lagi, dan yang sudah
        # pernah dibalikkan juga tidak — dua-duanya ditolak service;
        # syarat ini cuma menyembunyikan tombolnya lebih awal.
        visible_when={
            "all": [
                {"field": "entry_type", "op": "ne", "value": "reversal"},
                {"field": "reversed_by_label", "op": "is_null"},
            ],
        },
        fields=[
            {
                "key": "reason",
                "type": "textarea",
                "label": "Alasan Pembalikan",
                "required": True,
            },
        ],
        confirm={
            "title": "Batalkan transaksi ini?",
            "description": (
                "Barisnya tidak dihapus — dicatat baris baru yang "
                "membatalkannya, dan keduanya tetap terbaca."
            ),
        },
    ),
]


# Kolom hasil introspeksi yang tidak dipakai di tabel. `source_type` dan
# `source_id` ditampilkan lewat `source_label` yang sudah dirakit, dan
# `reverses` lewat `reversed_by_label` — dua kolom pk mentah di ledger
# tidak memberi tahu siapa pun dokumen mana yang dimaksud.
HIDDEN_CREDIT_COLUMNS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "is_active",
        "source_type",
        "source_id",
        "plan",
        "segment",
        "reverses",
        "entry_type_label",
        "employee_name",
    )
}


ROTATION_CREDIT_SCHEMA = {
    "module": "hr/rotation-credits",
    "name": "RotationCreditTransaction",
    "label": "Rotation Credit",
    "endpoint": "/api/hr/rotation-credits/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Rotation Credit Ledger",
            description=(
                "Setiap perubahan saldo adalah satu baris. Tidak ada "
                "baris yang bisa disunting atau dihapus — koreksi lewat "
                "penyesuaian, pembatalan lewat pembalikan."
            ),
            size="lg",
            columns=2,
            create=True,
            # Sengaja: transaksi tidak pernah disunting dan tidak pernah
            # dihapus. Service-nya melempar; ini yang membuat tombolnya
            # tidak ada sejak awal.
            edit=False,
            delete=False,
            bulk_delete=False,
            export=True,
        ),
    },
    "actions": ROTATION_CREDIT_ACTIONS,
    "fields": {
        **ROTATION_CREDIT_FIELDS,
        **ROTATION_CREDIT_DISPLAY_FIELDS,
        **HIDDEN_CREDIT_COLUMNS,
    },
}
