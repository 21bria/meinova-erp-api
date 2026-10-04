"""
Schema layar Workflow Step.

Punya dua bentuk yang sengaja dipisah: `STEP_FIELDS` untuk halaman
step-nya sendiri, dan `STEP_GRID_FIELDS` untuk tabel inline di dalam
Workflow Definition. Grid memilih kolom dari flag `table`, jadi dua
tabel yang membaca endpoint sama **wajib membawa salinan config
sendiri** — mengubah flag di tempat akan ikut mengubah tabel yang
satunya.
"""

from copy import deepcopy

from apps.framework.builders import field, tabs, ui
from apps.workflow.labels import (
    APPROVAL_MODE_LABELS,
    APPROVER_SCOPE_LABELS,
    APPROVER_TYPE_LABELS,
    choices,
)


# Pilihan dropdown diambil dari satu peta label di `apps/workflow/
# labels.py`, bukan ditulis ulang di sini. Dua daftar yang harus tetap
# sama tapi disimpan terpisah pada akhirnya selalu berbeda, dan bedanya
# tidak menghasilkan error — cuma dropdown yang menyebut sesuatu dengan
# nama yang tidak dipakai kolom tampilannya.
#
# **Nilainya tidak berubah satu huruf pun.** `manager` tetap `manager`.
APPROVER_TYPE_OPTIONS = choices(APPROVER_TYPE_LABELS)


APPROVAL_MODE_OPTIONS = choices(APPROVAL_MODE_LABELS)


# Urutannya dari yang paling luas ke paling sempit — itu cara orang
# memikirkannya ("se-tenant, se-perusahaan, se-site"), bukan abjad.
# Urutan peta di `labels.py` yang menentukannya.
APPROVER_SCOPE_OPTIONS = choices(APPROVER_SCOPE_LABELS)


GENERAL_FIELDS = {
    # Wajib `table=True`, dan ini satu-satunya kolom yang membedakan
    # baris di layar ini.
    #
    # `sequence` mulai dari 1 lagi di tiap alur dan nama meja memang
    # berulang — "Approved By (Atasan Langsung)" ada di enam alur.
    # Tanpa kolom induknya, 28 baris milik 8 alur terbaca sebagai satu
    # daftar yang penuh duplikat, dan tidak ada satu pun cara di layar
    # untuk tahu baris mana milik alur mana. Gagalnya ke arah paling
    # buruk: data yang benar terbaca seperti data kotor yang perlu
    # dibersihkan.
    #
    # Grid inline di dalam Workflow Definition mem-`pop` field ini —
    # di sana induknya sudah pasti, jadi kolomnya cuma memakan lebar.
    "definition": field.lookup(
        tab="general",
        label="Workflow",
        lookup_endpoint="/api/workflow/lookup/workflow-definitions/",
        display_key="definition_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=10,
    ),

    "sequence": field.integer(
        tab="general",
        label="Step",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text="Dikosongkan = nomor bebas berikutnya.",
        order=20,
    ),

    "name": field.text(
        tab="general",
        label="Step Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        help_text=(
            "Judul kotak tanda tangan di formulir tercetak, mis. "
            "'Approved By (Atasan Langsung)'."
        ),
        order=30,
    ),

    "description": field.textarea(
        tab="general",
        label="Description",
        rows=2,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=40,
    ),
}


APPROVER_FIELDS = {
    "approver_type": field.select(
        tab="approver",
        label="Approver Type",
        display_key="approver_type_label",
        options=APPROVER_TYPE_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=110,
    ),

    "level": field.integer(
        tab="approver",
        label="Level",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        help_text=(
            "Berapa tingkat naik untuk tipe berbasis hierarki. "
            "1 = atasan langsung."
        ),
        visible_when={"approver_type": ["manager", "position"]},
        order=120,
    ),

    "approver_role": field.lookup(
        tab="approver",
        label="Role",
        lookup_endpoint="/api/accounts/lookup/roles/",
        display_key="approver_role_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text="Wajib diisi kalau tipenya Role Holder.",
        visible_when={"approver_type": "role"},
        order=130,
    ),

    "approver_scope": field.select(
        tab="approver",
        label="Role Scope",
        display_key="approver_scope_label",
        options=APPROVER_SCOPE_OPTIONS,
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=False,
        help_text=(
            "Sejauh mana pemegang role dicari, dibandingkan dengan "
            "penempatan pegawai yang dokumennya diproses. Location "
            "untuk meja yang memang per site (KTT, Admin Site); "
            "Company untuk yang melayani lintas site (HRGA, HR "
            "Manager). Kolom yang dipilih harus terisi di penempatan "
            "pegawainya — kalau kosong, step ini tidak menemukan "
            "siapa pun."
        ),
        visible_when={"approver_type": "role"},
        order=135,
    ),

    "approver_user": field.lookup(
        tab="approver",
        label="User",
        lookup_endpoint="/api/accounts/lookup/users/",
        display_key="approver_user_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        help_text="Wajib diisi kalau tipenya Specific User.",
        visible_when={"approver_type": "user"},
        order=140,
    ),

    "approver_position": field.lookup(
        tab="approver",
        label="Position",
        lookup_endpoint="/api/administration/organization/lookup/positions/",
        display_key="approver_position_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        help_text=(
            "Dikosongkan = berangkat dari jabatan pengaju sendiri, "
            "lalu naik sebanyak Level."
        ),
        visible_when={"approver_type": "position"},
        order=150,
    ),

    "fallback_role": field.lookup(
        tab="approver",
        label="Fallback Role",
        lookup_endpoint="/api/accounts/lookup/roles/",
        display_key="fallback_role_name",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        help_text=(
            "Dipakai kalau penelusuran struktur organisasi tidak "
            "menemukan siapa pun. Kosong = step-nya gagal, kecuali "
            "Required dimatikan."
        ),
        order=160,
    ),
}


BEHAVIOR_FIELDS = {
    "approval_mode": field.select(
        tab="behavior",
        label="Approval Mode",
        display_key="approval_mode_label",
        options=APPROVAL_MODE_OPTIONS,
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        help_text=(
            "Hanya berpengaruh kalau step ini menghasilkan lebih dari "
            "satu approver — praktisnya tipe Role Holder."
        ),
        order=210,
    ),

    "minimum_approvals": field.integer(
        tab="behavior",
        label="Minimum Approvals",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        visible_when={"approval_mode": "any"},
        order=220,
    ),

    "is_required": field.switch(
        tab="behavior",
        label="Required",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=False,
        help_text=(
            "Dimatikan: approver yang tidak ketemu membuat step ini "
            "dilewati, bukan menggagalkan seluruh pengajuan."
        ),
        order=230,
    ),

    "can_reject": field.switch(
        tab="behavior",
        label="Can Reject",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=240,
    ),

    "can_return": field.switch(
        tab="behavior",
        label="Can Return",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        help_text=(
            "Approver boleh mengembalikan dokumen ke pengaju untuk "
            "diperbaiki, tanpa menolaknya."
        ),
        order=250,
    ),

    "condition": field.json(
        tab="behavior",
        label="Condition",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        help_text=(
            "Kosong = step selalu jalan. Contoh: "
            '{"field": "total_days", "op": "gte", "value": 5} — step '
            "ini hanya jalan untuk cuti 5 hari ke atas."
        ),
        order=260,
    ),
}


STEP_FIELDS = {
    **GENERAL_FIELDS,
    **APPROVER_FIELDS,
    **BEHAVIOR_FIELDS,
}


DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "definition_name",
        "approver_type_label",
        "approval_mode_label",
        "approver_scope_label",
        "approver_user_name",
        "approver_role_name",
        "approver_position_name",
        "fallback_role_name",
    )
}


# Salinan sendiri untuk tabel inline di dalam Workflow Definition.
# `deepcopy` bukan kehati-hatian berlebihan: config field adalah dict
# bersarang, dan mengubah flag di salinan dangkal akan ikut mengubah
# schema halaman step-nya.
STEP_GRID_FIELDS = deepcopy(STEP_FIELDS)

# Kolom yang perlu diketik wajib `table=True` — di tabel inline tidak
# ada dialog atau halaman kedua tempat mengisinya.
for _name, _config in STEP_GRID_FIELDS.items():
    _config["table"] = _name in {
        "sequence",
        "name",
        "approver_type",
        "level",
        "approver_role",
        # Cakupan ikut di grid: inilah kolom yang membedakan meja
        # per-site dari meja lintas-site, dan menyembunyikannya membuat
        # dua baris yang perilakunya sangat berbeda terlihat identik.
        "approver_scope",
        "approver_user",
        "is_required",
    }

# Induknya ditanam komponen inline di tiap baris; menampilkannya
# sebagai kolom cuma memakan lebar.
STEP_GRID_FIELDS.pop("definition", None)


STEP_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="approver",
        label="Approver",
        fields=list(APPROVER_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
    tabs.form(
        key="behavior",
        label="Behaviour",
        fields=list(BEHAVIOR_FIELDS.keys()),
        order=30,
        show_on_create=True,
    ),
]


STEP_SCHEMA = {
    # Namespace katalog terjemahan frontend.
    #
    # Dibaca generator (`scripts/meinova/generators/i18n.mjs`): label
    # kolom/form/filter dipancarkan sebagai
    # `resourceLabel("workflow.steps.fields.<field>", "<label Inggris>")`
    # alih-alih literal. Argumen keduanya label yang ada di berkas ini,
    # jadi modul tetap benar walau katalognya belum diisi.
    #
    # **Nama field tidak ikut** — hanya labelnya. `approver_type` tetap
    # `approver_type` di payload, di query string, dan di database.
    "i18n": {"namespace": "workflow.steps"},

    "module": "workflow/steps",
    "name": "Workflow Step",
    "label": "Workflow Step",
    "endpoint": "/api/workflow/steps/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Workflow Step",
            description="Satu tingkat persetujuan di dalam alur.",
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=False,
        ),
    },
    "tabs": STEP_TABS,
    "fields": {
        **STEP_FIELDS,
        **DISPLAY_FIELDS,
    },
}
