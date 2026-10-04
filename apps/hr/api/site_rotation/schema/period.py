from apps.framework.builders import field, tabs, ui

PERIOD_TYPE_OPTIONS = [
    {"label": "On Site", "value": "work"},
    {"label": "Off", "value": "off"},
]


PERIOD_STATUS_OPTIONS = [
    {"label": "Scheduled", "value": "scheduled"},
    {"label": "Ongoing", "value": "ongoing"},
    {"label": "Completed", "value": "completed"},
    {"label": "Cancelled", "value": "cancelled"},
]


GENERAL_FIELDS = {
    "rotation": field.lookup(
        tab="general",
        label="Rotation",
        lookup_endpoint="/api/hr/lookup/site-rotations/",
        required=True,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=10,
    ),

    "sequence": field.integer(
        tab="general",
        label="No",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Urutan gabungan ON dan OFF: 1 = kerja #1, 2 = off #1, "
            "3 = kerja #2. Dikosongkan = nomor bebas berikutnya, untuk "
            "baris yang disisipkan tangan."
        ),
        order=20,
    ),

    # Filter ON/OFF di tabel periode dipasang lewat `filter=True` di
    # sini — itu yang jadi tab/toggle pemisah blok kerja dan blok off.
    "period_type": field.select(
        tab="general",
        label="Type",
        display_key="period_type_label",
        options=PERIOD_TYPE_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=30,
    ),

    # "Travel Purpose" di form Travel Request. Hanya berlaku untuk blok
    # off — backend menolak kalau dipasang di blok kerja.
    "purpose": field.lookup(
        tab="general",
        label="Travel Purpose",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/rotation-purposes/"
        ),
        display_key="purpose_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Alasan blok off ini: Field Break, Cuti Tahunan, dan "
            "seterusnya. Satu blok off boleh dipecah jadi beberapa "
            "baris dengan alasan berbeda."
        ),
        order=35,
    ),

    "employee_leave": field.lookup(
        tab="general",
        label="Leave Record",
        lookup_endpoint="/api/hr/lookup/employee-leaves/",
        display_key="employee_leave_label",
        lookup_params={"employee_id": "$employee"},
        depends_on="employee",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        help_text=(
            "Catatan cuti yang memotong saldo untuk blok ini. Roster "
            "sendiri tidak memotong saldo — angkanya tetap dihitung di "
            "modul Cuti supaya tidak ada dua sumber. Baru bisa dipilih "
            "setelah barisnya tersimpan, karena pegawainya disalin dari "
            "dokumen induk saat simpan."
        ),
        order=36,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=PERIOD_STATUS_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Tidak berpindah sendiri — Celery Beat belum aktif, jadi "
            "tidak ada yang memajukan status ke Ongoing/Completed."
        ),
        order=40,
    ),
}


PERIOD_FIELDS = {
    "start_date": field.date(
        tab="general",
        label="Start Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=110,
    ),

    "end_date": field.date(
        tab="general",
        label="End Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=120,
    ),

    "total_days": field.integer(
        tab="general",
        label="Days",
        # Dihitung ulang di grid begitu salah satu tanggalnya diubah.
        # Tanpa ini baris tetap membawa angka lama, dan karena service
        # menghormati `total_days` yang dikirim sebagai isian manual,
        # angka lama itu ikut tersimpan — salah tanpa pesan apa pun.
        compute={
            "kind": "date_diff",
            "from": "start_date",
            "to": "end_date",
            "inclusive": True,
        },
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Dikosongkan = dihitung dari selisih tanggal. Isian manual "
            "dihormati untuk blok kerja yang dipotong hari travel."
        ),
        order=130,
    ),

    # Rencana shift normal blok ini — jawaban "kalau bekerja, shift
    # apa" dibacakan **di layar roster**. Read-only: yang menuliskannya
    # tombol Set Shift Pattern di dokumen induk, dan mengetiknya per
    # baris di sini akan mengembalikan pekerjaan ganda yang justru mau
    # dihilangkan.
    "shift_plan": field.text(
        tab="general",
        label="Shift Plan",
        read_only=True,
        display=True,
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        help_text=(
            "Diisi tombol Set Shift Pattern di dokumen roster. Kosong "
            "pada hari off dan hari perjalanan — keduanya memang tidak "
            "punya shift."
        ),
        order=135,
    ),

    "is_manual_override": field.switch(
        tab="general",
        label="Manual Override",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        help_text=(
            "Menyala sendiri begitu tanggalnya digeser tangan. Baris "
            "bertanda ini menolak ditimpa Generate Periods."
        ),
        order=140,
    ),

    "notes": field.textarea(
        tab="general",
        label="Notes",
        rows=2,
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=150,
    ),
}


ROTATION_PERIOD_FIELDS = {
    **GENERAL_FIELDS,
    **PERIOD_FIELDS,
}


# Isi tab "Periods" di dokumen rotasi. `tabs.resource` yang tidak dioper
# `fields` menghasilkan tabel tanpa kolom dan dialog tanpa isian — gagal
# diam-diam, karena schema-nya tetap terkirim dan tab-nya tetap muncul.
#
# `rotation` dibuang: induknya sudah ditentukan `foreign_key` milik tab,
# dan menampilkannya di dialog membuka peluang satu baris dipindahkan ke
# dokumen lain dari dalam dokumen ini.
ROTATION_PERIOD_RESOURCE_FIELDS = {
    key: value
    for key, value in ROTATION_PERIOD_FIELDS.items()
    if key != "rotation"
}


ROTATION_PERIOD_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        # Disalin service dari dokumen induk, jadi tidak ada di form.
        "employee",
        "employee_name",
        "employee_number",
        "period_type_label",
        "status_label",
        "purpose_name",
        "employee_leave_label",
            )
}


ROTATION_PERIOD_TABS = [
    tabs.form(
        key="general",
        label="Period",
        fields=list(ROTATION_PERIOD_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
]


ROTATION_PERIOD_UI = {
    **ui.drawer(
        title="Rotation Period",
        description=(
            "Satu blok kerja atau off, beserta travel dan akomodasinya."
        ),
        side="right",
        size="xl",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),
}


ROTATION_PERIOD_SCHEMA = {
    "module": "hr/rotation-periods",
    "name": "RotationPeriod",
    "label": "Rotation Period",
    "endpoint": "/api/hr/rotation-periods/",
    "schema_type": "crud",

    "ui": ROTATION_PERIOD_UI,
    "tabs": ROTATION_PERIOD_TABS,
    "fields": {
        **ROTATION_PERIOD_FIELDS,
        **ROTATION_PERIOD_DISPLAY_FIELDS,
    },
}
