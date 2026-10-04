from apps.framework.builders import field


TIME_FIELDS = {
    "scheduled_check_in": field.datetime(
        tab="time",
        label="Scheduled Check In",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=10,
    ),

    "scheduled_check_out": field.datetime(
        tab="time",
        label="Scheduled Check Out",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=20,
    ),

    "check_in": field.datetime(
        tab="time",
        label="Check In",
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=30,
    ),

    "check_out": field.datetime(
        tab="time",
        label="Check Out",
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=40,
    ),

    "first_check_in": field.datetime(
        tab="time",
        label="First Check In",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=50,
    ),

    "last_check_out": field.datetime(
        tab="time",
        label="Last Check Out",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=60,
    ),

    "worked_minutes": field.number(
        tab="time",
        label="Worked Minutes",
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=70,
    ),

    "break_minutes": field.number(
        tab="time",
        label="Break Minutes",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=80,
    ),

    "late_minutes": field.number(
        tab="time",
        label="Late Minutes",
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=90,
    ),

    "early_leave_minutes": field.number(
        tab="time",
        label="Early Leave Minutes",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=100,
    ),

    "overtime_minutes": field.number(
        tab="time",
        label="Overtime Minutes",
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=110,
    ),

    # Penanda "seharusnya mengambil cuti" dari Attendance Policy.
    #
    # **Angka menurut aturan**, dan tetap ditimpa tiap perhitungan
    # ulang — itu faktanya.
    #
    # Sengaja **tidak** di tabel: yang tampil di daftar kolom
    # `leave_required_effective`, yang sudah menghormati pembebasan dan
    # angka yang ditetapkan atasan. Dua kolom berlabel nyaris sama, dan
    # salah satunya diam-diam mengabaikan pembebasan, adalah cara
    # tercepat membuat daftar ini tidak dipercaya. Angka mentahnya tetap
    # terbaca saat barisnya dibuka.
    "leave_required_days": field.decimal(
        tab="time",
        label="Leave Required (rule)",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        read_only=True,
        display=True,
        help_text=(
            "Diisi sistem saat keterlambatan atau pulang cepatnya "
            "melewati ambang di Attendance Policy. Ini penanda — yang "
            "memotong saldo tetap dokumen cuti yang diajukan dan "
            "disetujui."
        ),
        order=120,
    ),

    "leave_required_reason": field.text(
        tab="time",
        label="Leave Required Reason",
        table=False,
        filter=False,
        search=False,
        read_only=True,
        display=True,
        order=130,
    ),

    # ------------------------------------------------------------------
    # Keputusan atasan
    # ------------------------------------------------------------------
    #
    # Angka di atas tetap **menurut aturan** dan tetap ditimpa tiap
    # perhitungan ulang. Yang di bawah ini keputusan orang, dan karena
    # itu kolomnya terpisah — kalau ditulis ke kolom yang sama,
    # pembebasan tidak bisa dibedakan dari aturan yang memang tidak
    # menyala.
    #
    # Read-only di form: yang mengubahnya tombol Waive / Require Leave,
    # supaya siapa dan kapan ikut tercatat. Kolom yang bisa diketik
    # diam-diam di tengah baris lain tidak meninggalkan jejak itu.

    "leave_required_override": field.decimal(
        tab="time",
        label="Leave Required (override)",
        decimal_places=2,
        max_digits=4,
        table=False,
        filter=False,
        search=False,
        read_only=True,
        display=True,
        help_text=(
            "Angka yang ditetapkan atasan/HR. Kosong = ikut aturan."
        ),
        order=131,
    ),

    "leave_required_waived": field.switch(
        tab="time",
        label="Waived",
        table=False,
        filter=True,
        search=False,
        read_only=True,
        display=True,
        help_text="Dibebaskan — tidak perlu mengajukan cuti hari ini.",
        order=132,
    ),

    "leave_required_waiver_reason": field.textarea(
        tab="time",
        label="Waiver Reason",
        rows=2,
        table=False,
        filter=False,
        search=True,
        read_only=True,
        display=True,
        order=133,
    ),

    "review_decision": field.select(
        tab="time",
        label="Review Decision",
        options=[
            {"label": "Valid exception", "value": "valid"},
            {
                "label": "Must submit leave",
                "value": "require_leave",
            },
        ],
        display_key="review_decision_label",
        table=False,
        filter=True,
        search=False,
        read_only=True,
        display=True,
        help_text="Kosong = belum ditinjau atasan.",
        order=134,
    ),

    "review_notes": field.textarea(
        tab="time",
        label="Review Notes",
        rows=2,
        table=False,
        filter=False,
        search=True,
        read_only=True,
        display=True,
        order=135,
    ),

    "reviewed_at": field.datetime(
        tab="time",
        label="Reviewed At",
        table=False,
        filter=False,
        search=False,
        read_only=True,
        display=True,
        order=136,
    ),

    # Dokumen cuti yang lahir dari baris ini. Tanpa tautannya,
    # "sudah diselesaikan" tidak bisa dibedakan dari "sudah
    # diselesaikan lalu cutinya ditolak".
    #
    # Sengaja **bukan** `field.lookup`: `/api/hr/leaves/lookup/` tidak
    # ada, dan lookup tanpa endpoint menghasilkan dropdown yang bisa
    # dibuka lalu selalu kosong — lebih buruk daripada tidak ada, karena
    # pemakainya menyangka datanya yang belum terisi. Nomornya dibaca
    # dari `leave_document_number` di serializer.
    "leave": {
        "type": "hidden",
        "label": "Leave Document",
        "table": False,
        "filter": False,
        "search": False,
        "read_only": True,
    },
}