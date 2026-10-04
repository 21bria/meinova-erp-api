from apps.framework.builders import field

from .actions import ATTENDANCE_ACTIONS
from .fields import ATTENDANCE_FIELDS
from .importer import ATTENDANCE_IMPORT_SCHEMA
from .tabs import ATTENDANCE_TABS
from .ui import ATTENDANCE_UI


ATTENDANCE_DISPLAY_FIELDS = {
    "employee_name": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },

    # Nomor pegawai jadi kolom tersendiri, bukan ikut tenggelam di
    # kolom Employee: nama kembar lazim di tenant besar, dan nomor
    # inilah yang dipakai orang mencocokkan baris dengan mesin
    # fingerprint maupun file dari klien. Pola yang sama dipakai
    # Roster Setup Line, Roster Adjustment, dan Rotation Credit.
    "employee_number": field.text(
        # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
        # kanan tabel — lihat `column_after` di columns.mjs.
        column_after="employee",
        label="Employee No.",
        read_only=True,
        table=True,
        search=True,
        sortable=True,
        order=5,
    ),
    "company_name": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "branch_name": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "location_name": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "shift_name": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "status_label": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "source_label": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "approval_status_label": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "approved_by_name": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },

    # ------------------------------------------------------------------
    # Kewajiban cuti
    # ------------------------------------------------------------------
    #
    # Dua kolom ini **daftar kerja HR**, jadi keduanya ikut di tabel.
    # Yang ditampilkan angka **efektif**, bukan `leave_required_days`:
    # menampilkan angka menurut aturan pada baris yang sudah dibebaskan
    # membuat daftarnya terbaca seperti pekerjaan yang belum selesai.
    "leave_required_effective": {
        "label": "Leave Required",
        "table": True,
        "filter": False,
        "search": False,
        "sortable": False,
        "overview": True,
        "order": 320,
    },
    "leave_obligation_label": {
        "label": "Obligation",
        "table": True,
        "filter": False,
        "search": False,
        "sortable": False,
        "overview": True,
        "order": 321,
    },
    # Statusnya diturunkan, jadi tidak bisa disaring di level query.
    # Yang bisa disaring keputusan atasannya dan penanda pembebasan —
    # keduanya kolom sungguhan, dan sudah terdaftar di
    # `filterset_fields`.
    "leave_obligation_status": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "leave_required_reason_label": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "review_decision_label": {
        "label": "Review",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "reviewed_by_name": {
        "label": "Reviewed By",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "leave_document_number": {
        "label": "Leave Document",
        "read_only": True,
        "display": True,
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
}


ATTENDANCE_FIELDS_WITH_OVERRIDES = {
    **ATTENDANCE_FIELDS,
    **ATTENDANCE_DISPLAY_FIELDS,
}


ATTENDANCE_SCHEMA = {
    "module": "hr/attendance",
    "name": "Attendance",
    "label": "Attendance",
    "endpoint": "/api/hr/attendance/",
    "schema_type": "crud",

    "ui": ATTENDANCE_UI,
    "tabs": ATTENDANCE_TABS,
    "import": ATTENDANCE_IMPORT_SCHEMA,
    "actions": ATTENDANCE_ACTIONS,
    "fields": ATTENDANCE_FIELDS_WITH_OVERRIDES,
}