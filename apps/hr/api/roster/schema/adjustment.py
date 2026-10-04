"""
Schema layar penyesuaian jadwal roster.

Formnya dinamis dari `visible_when` pada Adjustment Kind, bukan delapan
layar berbeda: Schedule Shift memunculkan kolom jangkar baru, Use
Rotation Credit memunculkan saldo, Loyalty tidak memunculkan satu pun
kolom hari karena memang tidak mengubah apa-apa.
"""

from apps.framework.builders import action, field, tabs, ui


ADJUSTMENT_KIND_OPTIONS = [
    {"label": "Work Extension", "value": "work_extension"},
    {"label": "Early Return", "value": "early_return"},
    {"label": "Deferred Leave (KTT approved)", "value": "deferred_leave"},
    {"label": "Late Return (employee fault)", "value": "late_return"},
    {"label": "Deferred Leave (no approval)", "value": "loyalty"},
    {"label": "No Impact (beyond employee control)", "value": "no_impact"},
    {"label": "Schedule Shift", "value": "schedule_shift"},
    {"label": "Use Rotation Credit", "value": "credit_use"},
]


ADJUSTMENT_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Pending Approval", "value": "submitted"},
    {"label": "Approved", "value": "approved"},
    {"label": "Applied", "value": "applied"},
    {"label": "Rejected", "value": "rejected"},
    {"label": "Cancelled", "value": "cancelled"},
]


CREDIT_IMPACT_OPTIONS = [
    {"label": "No Credit Impact", "value": "none"},
    {"label": "Earn Credit", "value": "earn"},
    {"label": "Use Credit", "value": "use"},
]


# Jenis yang benar-benar menggeser tanggal. Dipakai `visible_when` kolom
# hari — Loyalty dan No Impact sengaja tidak memintanya, karena angka
# yang diketik lalu diabaikan lebih buruk daripada kolom yang tidak ada.
SCHEDULE_CHANGING_KINDS = [
    "work_extension",
    "early_return",
    "deferred_leave",
    "late_return",
    "schedule_shift",
    "credit_use",
]


ROSTER_ADJUSTMENT_FIELDS = {
    "document_number": field.text(
        tab="general",
        label="Document No.",
        required=False,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        disabled=True,
        modes=["edit"],
        order=5,
    ),

    "plan": field.lookup(
        tab="general",
        label="Roster Plan",
        lookup_endpoint="/api/hr/lookup/roster-plans/",
        display_key="plan_label",
        autofill={"employee": "employee"},
        required=True,
        table=True,
        filter=True,
        overview=True,
        help_text=(
            "Hanya jadwal yang sudah dibaselinekan. Yang masih draft "
            "cukup disunting langsung — tidak perlu dokumen."
        ),
        order=10,
    ),

    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        required=False,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        read_only=True,
        display=True,
        help_text="Diambil dari rencananya.",
        order=15,
    ),

    "adjustment_kind": field.select(
        tab="general",
        label="Adjustment Type",
        options=ADJUSTMENT_KIND_OPTIONS,
        display_key="adjustment_kind_label",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text=(
            "Yang membedakan bukan berapa harinya, melainkan siapa "
            "penyebabnya — dan itu tidak bisa disimpulkan sistem dari "
            "selisih tanggal."
        ),
        order=20,
    ),

    "effective_date": field.date(
        tab="general",
        label="Effective Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text=(
            "Perubahan berlaku dari tanggal ini ke depan. Jadwal "
            "sebelumnya tidak disentuh sama sekali."
        ),
        order=25,
    ),

    "days": field.integer(
        tab="change",
        label="Days",
        required=False,
        table=True,
        sortable=True,
        min=0,
        visible_when={"field": "adjustment_kind", "op": "in",
                      "value": SCHEDULE_CHANGING_KINDS},
        help_text=(
            "Selalu positif. Arahnya ditentukan jenis penyesuaian — "
            "Work Extension memperpanjang, Early Return memendekkan."
        ),
        order=30,
    ),

    "new_cycle_start": field.date(
        tab="change",
        label="New Cycle Start",
        required=False,
        table=False,
        visible_when={"adjustment_kind": ["schedule_shift"]},
        help_text=(
            "Untuk pegawai yang pindah gelombang, bukan yang jadwalnya "
            "sekadar bergeser. Dikosongkan = jangkar dihitung dari "
            "jadwal yang bertahan."
        ),
        order=35,
    ),

    "credit_impact": field.select(
        tab="change",
        label="Rotation Credit",
        options=CREDIT_IMPACT_OPTIONS,
        display_key="credit_impact_label",
        required=False,
        table=True,
        filter=True,
        visible_when={"field": "adjustment_kind", "op": "in",
                      "value": SCHEDULE_CHANGING_KINDS},
        help_text=(
            "Terisi otomatis dari jenis penyesuaian, tapi boleh diubah: "
            "kapal yang delay pun kadang layak diberi kompensasi, dan "
            "itu keputusan yang tidak bisa disimpulkan dari jenisnya."
        ),
        order=40,
    ),

    "credit_days": field.decimal(
        tab="change",
        label="Credit Days",
        required=False,
        table=True,
        sortable=True,
        decimal_places=2,
        max_digits=6,
        readonly_when={
            "field": "credit_impact", "op": "eq", "value": "earn",
        },
        visible_when={
            "not": {"field": "credit_impact", "op": "eq", "value": "none"},
        },
        help_text=(
            "Untuk Earn dihitung dari rasio pola pegawai (56:14 = 4, "
            "42:14 = 3) dan dibekukan ke dokumen — rasio yang diubah di "
            "master minggu depan tidak mengubah arti yang sudah "
            "disetujui."
        ),
        order=45,
    ),

    "segment": field.lookup(
        tab="change",
        label="Target Segment",
        lookup_endpoint="/api/hr/lookup/rotation-segments/",
        display_key="segment_label",
        lookup_params={"rotation_id": "$plan"},
        depends_on="plan",
        required=False,
        table=False,
        help_text=(
            "Dikosongkan = ditentukan dari Effective Date. Diisi hanya "
            "kalau blok yang dimaksud bukan yang memuat tanggal itu."
        ),
        order=50,
    ),

    "reason": field.textarea(
        tab="general",
        label="Reason",
        required=True,
        rows=3,
        table=True,
        search=True,
        help_text=(
            "Wajib. Jadwal yang bergeser tanpa alasan tidak bisa "
            "dijelaskan ke siapa pun enam bulan lagi."
        ),
        order=55,
    ),

    "reference": field.text(
        tab="general",
        label="Reference",
        required=False,
        table=True,
        search=True,
        help_text="Nomor TR, nomor tiket, atau nomor memo.",
        order=60,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        options=ADJUSTMENT_STATUS_OPTIONS,
        display_key="status_label",
        required=False,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        disabled=True,
        modes=["edit"],
        order=65,
    ),

    "apply_error": field.textarea(
        tab="general",
        label="Apply Error",
        required=False,
        rows=3,
        read_only=True,
        display=True,
        modes=["edit"],
        help_text=(
            "Kegagalan penerapan ditempel di sini, bukan cuma di log "
            "server. Perbaiki datanya lalu tekan Apply lagi."
        ),
        order=70,
    ),
}


ROSTER_ADJUSTMENT_DISPLAY_FIELDS = {
    "employee_number": field.text(
        # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
        # kanan tabel — lihat `column_after` di columns.mjs.
        column_after="employee",
        tab="general",
        label="Employee No.",
        read_only=True,
        display=True,
        table=True,
        search=True,
        sortable=True,
        order=12,
    ),

    "plan_label": field.text(
        tab="general",
        label="Plan",
        read_only=True,
        display=True,
        table=False,
        order=11,
    ),

    "credit_balance": field.decimal(
        tab="change",
        label="Current Credit Balance",
        read_only=True,
        display=True,
        table=False,
        decimal_places=2,
        help_text="Saldo rotation credit pegawai saat ini.",
        order=44,
    ),

    "applied_at": field.datetime(
        tab="general",
        label="Applied At",
        read_only=True,
        display=True,
        table=True,
        sortable=True,
        order=75,
    ),
}


ROSTER_ADJUSTMENT_TABS = [
    tabs.form(
        "general",
        label="Document",
        fields=[
            "document_number",
            "plan",
            "plan_label",
            "employee",
            "employee_number",
            "adjustment_kind",
            "effective_date",
            "reason",
            "reference",
            "status",
            "applied_at",
            "apply_error",
        ],
    ),

    tabs.form(
        "change",
        label="Change Details",
        fields=[
            "days",
            "new_cycle_start",
            "segment",
            "credit_impact",
            "credit_days",
            "credit_balance",
        ],
    ),
]


ROSTER_ADJUSTMENT_ACTIONS = [
    action.custom(
        "preview",
        label="Preview Impact",
        icon="CalendarSearch",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/roster-adjustments/{id}/preview/",
        method="get",
        refresh=False,
    ),

    action.submit(
        endpoint="/api/hr/roster-adjustments/{id}/submit/",
        visible_when={"status": ["draft", "rejected"]},
        confirm={
            "title": "Ajukan penyesuaian?",
            "description": (
                "Dokumen dikirim ke alur persetujuan. Jadwalnya baru "
                "berubah setelah seluruh meja menyetujui."
            ),
        },
    ),

    action.withdraw(
        endpoint="/api/hr/roster-adjustments/{id}/withdraw/",
        visible_when={"status": ["submitted"]},
    ),

    action.custom(
        "apply",
        label="Retry Apply",
        icon="RefreshCw",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/roster-adjustments/{id}/apply/",
        method="post",
        refresh=True,
        # Hanya untuk yang sudah disetujui tapi penerapannya gagal.
        # Approval-nya sendiri tidak diulang.
        visible_when={"status": ["approved"]},
    ),
]


# Kolom hasil introspeksi yang tidak dipakai di tabel.
#
# `company`/`branch`/`location` adalah salinan untuk penyaringan data,
# dan serializer tidak mengirim nama relasinya — kolomnya mencari
# `company_name` yang tidak pernah ada dan tampil "-" di **semua** baris.
# Pola yang sama dengan `apps/workflow/api/instance/schema.py`.
HIDDEN_ADJUSTMENT_COLUMNS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "is_active",
        "company",
        "branch",
        "location",
        "submitted_at",
        "submitted_by",
        "resulting_version",
        "segment",
        "new_cycle_start",
        "workflow",
        "status_label",
        "adjustment_kind_label",
        "credit_impact_label",
        "employee_name",
        "credit_balance",
    )
}


ROSTER_ADJUSTMENT_SCHEMA = {
    "module": "hr/roster-adjustments",
    "name": "RosterAdjustment",
    "label": "Roster Adjustment",
    "endpoint": "/api/hr/roster-adjustments/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Roster Adjustment",
            description=(
                "Perubahan operasional pada jadwal yang sudah berjalan. "
                "Jadwal sebelum tanggal berlaku tidak disentuh."
            ),
            size="full",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
    },
    "tabs": ROSTER_ADJUSTMENT_TABS,
    "actions": ROSTER_ADJUSTMENT_ACTIONS,
    "fields": {
        **ROSTER_ADJUSTMENT_FIELDS,
        **ROSTER_ADJUSTMENT_DISPLAY_FIELDS,
        **HIDDEN_ADJUSTMENT_COLUMNS,
    },
}
