from apps.framework.builders import field, tabs, ui


PARTICIPANT_STATUS_OPTIONS = [
    {"label": "Registered", "value": "registered"},
    {"label": "Attended", "value": "attended"},
    {"label": "Absent", "value": "absent"},
    {"label": "Cancelled", "value": "cancelled"},
]


GENERAL_FIELDS = {
    "program": field.lookup(
        tab="general",
        label="Program",
        lookup_endpoint="/api/hr/lookup/training-programs/",
        display_key="program_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=10,
    ),

    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=PARTICIPANT_STATUS_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=30,
    ),
}


RESULT_FIELDS = {
    "score": field.decimal(
        tab="result",
        label="Score",
        decimal_places=2,
        max_digits=6,
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=110,
    ),

    "is_passed": field.switch(
        tab="result",
        label="Passed",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Dibiarkan kosong berarti belum dinilai — bukan tidak lulus."
        ),
        order=120,
    ),

    "certificate_number": field.text(
        tab="result",
        label="Certificate Number",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=130,
    ),

    "notes": field.textarea(
        tab="result",
        label="Notes",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=140,
    ),
}


TRAINING_PARTICIPANT_FIELDS = {
    **GENERAL_FIELDS,
    **RESULT_FIELDS,
}


TRAINING_PARTICIPANT_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "program_code",
        "program_name",
        "employee_name",
        "status_label",
        # Terisi kalau hasil program sudah dicatatkan ke riwayat
        # pegawai; tidak diisi lewat form ini.
        "employee_training",
    )
}

# Nomor pegawai jadi kolom tersendiri, bukan ikut tenggelam di kolom
# Employee: daftar peserta dicocokkan dengan absensi pelatihan dan
# sertifikat, dan yang tercetak di sana nomornya.
TRAINING_PARTICIPANT_DISPLAY_FIELDS["employee_number"] = field.text(
    # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
    # kanan tabel — lihat `column_after` di columns.mjs.
    column_after="employee",
    label="Employee No.",
    read_only=True,
    table=True,
    search=True,
    sortable=True,
    order=25,
)


TRAINING_PARTICIPANT_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="result",
        label="Result",
        fields=list(RESULT_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
]


TRAINING_PARTICIPANT_UI = {
    **ui.dialog(
        title="Training Participant",
        description="Peserta program pelatihan beserta hasilnya.",
        size="lg",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),
}


TRAINING_PARTICIPANT_SCHEMA = {
    "module": "hr/training-participants",
    "name": "TrainingParticipant",
    "label": "Training Participant",
    "endpoint": "/api/hr/training-participants/",
    "schema_type": "crud",

    "ui": TRAINING_PARTICIPANT_UI,
    "tabs": TRAINING_PARTICIPANT_TABS,
    "fields": {
        **TRAINING_PARTICIPANT_FIELDS,
        **TRAINING_PARTICIPANT_DISPLAY_FIELDS,
    },
}
