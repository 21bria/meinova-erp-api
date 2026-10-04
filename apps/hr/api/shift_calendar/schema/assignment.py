"""
Schema layar Shift Assignment **Records** — layar admin, bukan alur.

Layar ini yang menjawab pertanyaan kedua kalender — "kalau bekerja,
shift apa" — dan sengaja **tidak** menjawab yang pertama. Tidak ada
kolom WORK/OFF di sini: itu milik Roster Schedule, dan menaruh dua
jawaban di satu form membuat orang mengubah rosternya hanya karena mau
menggeser shift.

Kenapa ia bukan lagi layar utama
--------------------------------
Alur normal HR cuma tiga langkah, dan tidak satu pun melewati layar
ini: **Roster** menetapkan hari kerja beserta shift normalnya (tombol
Set Shift Pattern), **Shift Calendar** memperlihatkan hasilnya, dan
penyesuaian dibuat dari kalender itu. Lapis `baseline`/`override`
ditentukan oleh alurnya — bukan oleh dropdown.

Yang tinggal di sini justru gunanya yang lain: melihat baris mentahnya,
menelusuri kenapa sebuah tanggal berbunyi begitu, dan membetulkan satu
baris tanpa menyusun ulang seluruh pola. Karena itu `layer` **tetap**
sebuah kolom di sini — layar audit yang menyembunyikan lapisnya justru
tidak bisa dipakai mengaudit.
"""

from apps.framework.builders import field, ui


# Sengaja **sama persis** dengan label pilihan di model. Kolom tabelnya
# dirender dari `layer_label` yang berasal dari `get_layer_display()`,
# jadi dropdown yang memakai sebutan lain akan menampilkan dua nama
# untuk satu nilai di layar yang sama. Istilah lapis boleh muncul di
# sini — ini layar audit; yang tidak boleh menampilkannya alur normal,
# dan alur normal tidak pernah membuka layar ini.
LAYER_OPTIONS = [
    {"label": "Roster Baseline", "value": "baseline"},
    {"label": "Adjustment", "value": "override"},
]


# Alasan yang sama dengan `LAYER_OPTIONS`: label di sini harus sama
# persis dengan `get_kind_display()`, karena kolom tabelnya dirender
# dari `kind_label`.
KIND_OPTIONS = [
    {"label": "Working Shift", "value": "work"},
    {"label": "Recovery / Rest", "value": "rest"},
]


SHIFT_ASSIGNMENT_FIELDS = {
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

    # Baris Recovery / Rest justru menyatakan **tidak ada** shift, jadi
    # kolom ini tidak bisa lagi wajib di layar. Yang menegakkan
    # pasangannya `clean()` model — dua arah sekaligus, dan itu jalur
    # yang sama untuk seed, perintah, dan layar ini.
    "kind": field.select(
        label="Kind",
        options=KIND_OPTIONS,
        display_key="kind_label",
        required=True,
        default="work",
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text=(
            "Recovery / Rest = hari pemulihan: tidak menunjuk shift, "
            "dan tanggalnya tidak menerbitkan kewajiban presensi. "
            "Disisipkan generator saat jeda antar pergantian shift "
            "kurang dari Minimum Rest di Roster Policy."
        ),
        order=15,
    ),

    "shift": field.lookup(
        label="Shift",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/shifts/"
        ),
        display_key="shift_name",
        required=False,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        visible_when={"field": "kind", "op": "eq", "value": "work"},
        help_text=(
            "Jam kerjanya milik master Shift. Mengubah jam di sana "
            "mengubah jadwal seluruh pegawai yang memakainya. "
            "Dikosongkan untuk baris Recovery / Rest."
        ),
        order=20,
    ),

    "layer": field.select(
        label="Layer",
        options=LAYER_OPTIONS,
        display_key="layer_label",
        required=True,
        default="baseline",
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text=(
            "Adjustment menang pada rentangnya; tanggal di luar "
            "rentang kembali ke rencana dari Roster. Di alur normal "
            "kolom ini tidak pernah ditanyakan — Roster yang menulis "
            "rencananya, kalender yang membuat penyesuaiannya."
        ),
        order=30,
    ),

    "start_date": field.date(
        label="Start Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        order=40,
    ),

    "end_date": field.date(
        label="End Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text=(
            "Inklusif. Rentang terbuka tidak diizinkan — dua rentang "
            "terbuka pada satu lapis tidak punya jawaban yang bisa "
            "ditebak."
        ),
        order=50,
    ),

    "reason": field.text(
        label="Reason",
        required=False,
        table=True,
        search=True,
        max_length=200,
        help_text="Wajib untuk Adjustment.",
        order=60,
    ),

    "notes": field.textarea(
        label="Notes",
        required=False,
        rows=3,
        order=70,
    ),
}


SHIFT_ASSIGNMENT_DISPLAY_FIELDS = {
    "employee_number": field.text(
        column_after="employee",
        label="Employee No.",
        read_only=True,
        display=True,
        table=True,
        search=True,
        sortable=True,
        order=5,
    ),

    "shift_start_time": field.text(
        label="Start",
        read_only=True,
        display=True,
        table=True,
        order=22,
    ),

    "shift_end_time": field.text(
        label="End",
        read_only=True,
        display=True,
        table=True,
        order=24,
    ),

    "day_count": field.number(
        label="Days",
        read_only=True,
        display=True,
        table=True,
        order=55,
    ),
}


HIDDEN_COLUMNS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "is_active",
        "employee_name",
        "shift_code",
        "shift_name",
        "layer_label",
        "kind_label",
        "crosses_midnight",
    )
}


SHIFT_ASSIGNMENT_SCHEMA = {
    "module": "hr/shift-assignments",
    "name": "EmployeeShiftAssignment",
    "label": "Shift Assignment Record",
    "endpoint": "/api/hr/shift-assignments/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Shift Assignment Record",
            description=(
                "Baris mentah rencana & penyesuaian shift — untuk "
                "audit dan penelusuran. Alur normalnya: shift normal "
                "ditetapkan dari Roster Schedule (Set Shift Pattern), "
                "penyesuaian dibuat dari Shift Calendar."
            ),
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=False,
            export=True,
        ),
    },
    "fields": {
        **SHIFT_ASSIGNMENT_FIELDS,
        **SHIFT_ASSIGNMENT_DISPLAY_FIELDS,
        **HIDDEN_COLUMNS,
    },
}
