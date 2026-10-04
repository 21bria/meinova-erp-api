"""
Layar setting aturan roster per site.

Enam kelompok yang dibaca bersamaan: siapa yang diatur, pola siklusnya,
hari perjalanannya, aturan rotation credit-nya, tenggat pengajuannya,
dan tabel pemetaan Point of Hire. Tabel POH jadi tab tersendiri karena
barisnya bertambah seiring bertambahnya kota asal pegawai — bukan
sesuatu yang diisi sekali lalu selesai.

Sejak roster dikerjakan penuh, layar inilah yang memegang pola 4:2 /
5:2 / 6:2 / 8:2. Tidak ada satu pun rumus di backend yang membaca nama
atau kode policy; semuanya angka di layar ini.
"""

from rest_framework import serializers

from apps.administration.models import (
    RosterPolicy,
    RosterShiftRotation,
    RosterTravelDay,
)
from apps.core.services.master import BaseMasterService
from apps.framework.builders import action, field, tabs, ui
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.services.company_copy import (
    CompanyCopyMixin,
    CompanyCopyViewSetMixin,
)
from apps.framework.views.mixins import ServiceWriteMixin


class RosterPolicyService(CompanyCopyMixin, BaseMasterService):
    model = RosterPolicy

    copy_scope_fields = [
        "company",
        "location",
    ]

    copy_rule_fields = [
        "description",
        "cycle_work_days",
        "cycle_off_days",
        "roster_start_basis",
        "rolling_horizon_months",
        "min_rest_hours",
        "default_travel_out_days",
        "default_travel_in_days",
        "travel_day_mode",
        "travel_creates_segment",
        "travel_out_counts_as_roster_day",
        "travel_in_counts_as_roster_day",
        "count_transit_overnight",
        "travel_variance_credit_eligible",
        "travel_variance_credit_max_days",
        "credit_enabled",
        "conversion_ratio",
        "credit_rounding",
        "credit_carry_remainder",
        "credit_max_balance_days",
        "credit_expiry_months",
        "credit_allow_negative",
        "request_lead_days",
        "notify_lead_days",
        "is_active",
    ]

    # Tabel POH ikut, dan ini bukan pelengkap: hari perjalanan ditentukan
    # jarak, jadi policy tanpa barisnya menghasilkan jadwal tanpa satu
    # pun segmen travel — tanpa satu pesan pun. `point_of_hire` menunjuk
    # `City` yang master global, jadi barisnya tidak perlu dipetakan.
    copy_children = [
        {
            "relation": "travel_days",
            "parent_field": "policy",
            "fields": [
                "point_of_hire",
                "travel_out_days",
                "travel_in_days",
                "notes",
            ],
        },
    ]



class RosterTravelDayService(BaseMasterService):
    model = RosterTravelDay


class RosterPolicySerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )
    location_name = serializers.CharField(
        source="location.name", read_only=True, default=None,
    )
    travel_day_count = serializers.SerializerMethodField()

    # Dua angka turunan yang paling sering jadi pertanyaan pertama
    # pengguna: "60 hari itu dari mana" dan "rasio 3 itu dari mana".
    # Dikirim read-only supaya jawabannya ada di layar yang sama dengan
    # angkanya, bukan di dokumen terpisah.
    cycle_length = serializers.IntegerField(read_only=True)
    derived_ratio = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True, default=None,
    )
    has_cycle_pattern = serializers.BooleanField(read_only=True)

    class Meta:
        model = RosterPolicy
        fields = "__all__"
        read_only_fields = [
            "company_name",
            "location_name",
            "travel_day_count",
            "cycle_length",
            "derived_ratio",
            "has_cycle_pattern",
        ]

    def get_travel_day_count(self, obj) -> int:
        return obj.travel_days.filter(is_deleted=False).count()


class RosterTravelDaySerializer(serializers.ModelSerializer):
    point_of_hire_name = serializers.CharField(
        source="point_of_hire.name", read_only=True, default=None,
    )
    total_days = serializers.IntegerField(read_only=True)

    class Meta:
        model = RosterTravelDay
        fields = "__all__"
        read_only_fields = ["point_of_hire_name", "total_days"]


TRAVEL_DAY_FIELDS = {
    "point_of_hire": field.lookup(
        tab="general",
        label="Point Of Hire",
        lookup_endpoint=(
            "/api/administration/references/geography/lookup/cities/"
        ),
        display_key="point_of_hire_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=10,
    ),
    "travel_out_days": field.integer(
        tab="general",
        label="Travel Out (days)",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text="Site → Point of Hire (pulang).",
        order=20,
    ),
    "travel_in_days": field.integer(
        tab="general",
        label="Travel In (days)",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text="Point of Hire → site (berangkat).",
        order=30,
    ),
    "notes": field.text(
        tab="general",
        label="Notes",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=40,
    ),
}


ROSTER_TRAVEL_DAY_SCHEMA = {
    "module": "hr/roster-travel-days",
    "name": "RosterTravelDay",
    "label": "Travel Days by POH",
    "endpoint": "/api/administration/references/hr/roster-travel-days/",
    "schema_type": "crud",
    "ui": {**ui.dialog(title="Hari Perjalanan", size="md", columns=1)},
    "tabs": [
        tabs.form(
            key="general",
            label="Travel Days",
            fields=list(TRAVEL_DAY_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
    ],
    "fields": {
        **TRAVEL_DAY_FIELDS,
        "policy": {
            "table": False, "filter": True,
            "search": False, "sortable": False,
        },
        **{
            name: {
                "table": False, "filter": False,
                "search": False, "sortable": False,
            }
            for name in ("point_of_hire_name", "total_days")
        },
    },
}


class RosterShiftRotationService(BaseMasterService):
    model = RosterShiftRotation


class RosterShiftRotationSerializer(serializers.ModelSerializer):
    shift_code = serializers.CharField(
        source="shift.code", read_only=True, default=None,
    )
    shift_name = serializers.CharField(
        source="shift.name", read_only=True, default=None,
    )
    shift_start_time = serializers.TimeField(
        source="shift.start_time", read_only=True, default=None,
    )
    shift_end_time = serializers.TimeField(
        source="shift.end_time", read_only=True, default=None,
    )
    crosses_midnight = serializers.BooleanField(
        source="shift.crosses_midnight", read_only=True, default=False,
    )

    class Meta:
        model = RosterShiftRotation
        fields = "__all__"
        read_only_fields = [
            "shift_code",
            "shift_name",
            "shift_start_time",
            "shift_end_time",
            "crosses_midnight",
        ]


SHIFT_ROTATION_FIELDS = {
    "sequence": field.integer(
        tab="general",
        label="Step",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Urutan langkah. Sesudah langkah terakhir, perputaran "
            "kembali ke langkah pertama."
        ),
        order=10,
    ),
    "shift": field.lookup(
        tab="general",
        label="Shift",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/shifts/"
        ),
        display_key="shift_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Jamnya milik master Shift; mengubahnya di sana mengubah "
            "jadwal semua yang memakai pola ini."
        ),
        order=20,
    ),
    "block_days": field.integer(
        tab="general",
        label="Days",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Berapa hari shift ini dipakai sebelum berganti. 7 = "
            "mingguan."
        ),
        order=30,
    ),
    "notes": field.text(
        tab="general",
        label="Notes",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=40,
    ),
}


ROSTER_SHIFT_ROTATION_SCHEMA = {
    "module": "hr/roster-shift-rotations",
    "name": "RosterShiftRotation",
    "label": "Shift Rotation",
    "endpoint": (
        "/api/administration/references/hr/roster-shift-rotations/"
    ),
    "schema_type": "crud",
    "ui": {**ui.dialog(title="Langkah Perputaran Shift", size="md", columns=1)},
    "tabs": [
        tabs.form(
            key="general",
            label="Shift Rotation",
            fields=list(SHIFT_ROTATION_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
    ],
    "fields": {
        **SHIFT_ROTATION_FIELDS,
        "policy": {
            "table": False, "filter": True,
            "search": False, "sortable": False,
        },
        **{
            name: {
                "table": False, "filter": False,
                "search": False, "sortable": False,
            }
            for name in (
                "shift_code", "shift_name", "shift_start_time",
                "shift_end_time", "crosses_midnight",
            )
        },
    },
}


TARGET_FIELDS = {
    "code": field.text(
        tab="general", label="Code", required=True, table=True,
        filter=False, search=True, sortable=True, overview=True, order=10,
    ),
    "name": field.text(
        tab="general", label="Name", required=True, table=True,
        filter=False, search=True, sortable=True, overview=True, order=20,
    ),
    "company": field.lookup(
        tab="general", label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        required=False, table=True, filter=True, search=False, sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk semua company yang tidak punya "
            "aturannya sendiri."
        ),
        order=30,
    ),
    "location": field.lookup(
        tab="general", label="Site / Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        lookup_params={"company_id": "$company"},
        required=False, table=True, filter=True, search=False, sortable=True,
        help_text=(
            "Site yang diatur. Dikosongkan = berlaku untuk semua site di "
            "company itu."
        ),
        order=40,
    ),
    # Satu site boleh punya beberapa policy (6:2 dan 8:2 berdampingan),
    # dan yang membedakan mana yang dipakai saat tidak ada yang menyebut
    # adalah penanda ini.
    "is_default": field.switch(
        tab="general", label="Default For This Site",
        required=False, table=True, filter=True, search=False, sortable=True,
        help_text=(
            "Aturan bawaan site: dipakai untuk pegawai yang belum "
            "ditugaskan Roster Policy, dan jadi pilihan awal di form. "
            "Hanya boleh satu per site."
        ),
        order=50,
    ),
    "description": field.textarea(
        tab="general", label="Description", rows=2, required=False,
        table=False, filter=False, search=True, sortable=False, order=60,
    ),
}


CYCLE_FIELDS = {
    "cycle_work_days": field.integer(
        tab="cycle", label="Work Days", required=False,
        table=True, filter=False, search=False, sortable=True, overview=True,
        help_text=(
            "Panjang blok kerja: 42 untuk pola 6:2, 56 untuk 8:2. "
            "Dikosongkan = aturan site saja — policy ini tidak bisa "
            "ditugaskan ke pegawai."
        ),
        order=110,
    ),
    "cycle_off_days": field.integer(
        tab="cycle", label="Field Break Days", required=False,
        table=True, filter=False, search=False, sortable=True, overview=True,
        help_text="Panjang blok off: 14 untuk 2 minggu.",
        order=120,
    ),
    "roster_start_basis": field.select(
        tab="cycle", label="Cycle Start Basis", required=True,
        table=False, filter=True, search=False, sortable=False,
        options=[
            {"value": "work_start", "label": "Work Start Date"},
            {"value": "site_arrival", "label": "Site Arrival Date"},
            {"value": "travel_departure", "label": "Travel Departure Date"},
        ],
        help_text=(
            "Arti tanggal Current Cycle Start pegawai. Work Start = hari "
            "pertama masuk kerja. Site Arrival = hari tiba di site "
            "(perjalanan menuju site sudah dihitung On Site). Travel "
            "Departure = hari berangkat dari Point of Hire."
        ),
        order=130,
    ),
    "rolling_horizon_months": field.integer(
        tab="cycle", label="Rolling Horizon (months)", required=False,
        table=False, filter=False, search=False, sortable=True,
        help_text=(
            "Jadwal digenerate sampai sekian bulan ke depan, lalu "
            "diperpanjang berkala tanpa menyentuh baris lama."
        ),
        order=140,
    ),
    # Dua angka yang dihitung, bukan diketik. "Cycle Length 60 itu dari
    # mana" adalah pertanyaan pertama pengguna, dan jawabannya harus ada
    # di layar yang sama dengan angka yang membentuknya.
    "cycle_length": field.integer(
        tab="cycle", label="Cycle Length (days)", required=False,
        read_only=True, display=True,
        table=True, filter=False, search=False, sortable=False,
        help_text="Work + Field Break + Travel Out + Travel In.",
        order=150,
    ),
    "derived_ratio": field.decimal(
        tab="cycle", label="Work : Off Ratio", required=False,
        read_only=True, display=True,
        table=False, filter=False, search=False, sortable=False,
        help_text=(
            "Dihitung dari pola di atas. Dipakai mengonversi kelebihan "
            "hari kerja jadi rotation credit."
        ),
        order=160,
    ),
    # Ditaruh di tab **Cycle Pattern**, bukan di tab Shift Rotation:
    # tab itu sebuah tabel inline, dan angkanya bukan milik satu
    # langkah perputaran — ia berlaku untuk setiap pergantian, termasuk
    # pergantian antar blok kerja yang tidak diwakili baris mana pun di
    # tabel itu.
    "min_rest_hours": field.integer(
        tab="cycle", label="Minimum Rest (hours)",
        required=False,
        table=True, filter=False, search=False, sortable=True,
        help_text=(
            "Jeda minimum saat shift berganti, diukur dari jam selesai "
            "shift terakhir sampai jam mulai shift berikutnya. Kurang "
            "dari ini, jadwal disela hari Recovery sampai terpenuhi — "
            "roster dan blok kerjanya tidak digeser. 0 = tidak "
            "diperiksa. Contoh: 24 membuat Night 19:00–07:00 tidak bisa "
            "langsung disusul Day 07:00 keesokan harinya."
        ),
        order=170,
    ),
}


TRAVEL_FIELDS = {
    "default_travel_out_days": field.integer(
        tab="travel", label="Default Travel Out (days)", required=True,
        table=True, filter=False, search=False, sortable=True, overview=True,
        help_text=(
            "Site → Point of Hire. Dipakai untuk POH yang belum "
            "didaftarkan di tab Travel Days by POH."
        ),
        order=210,
    ),
    "default_travel_in_days": field.integer(
        tab="travel", label="Default Travel In (days)", required=True,
        table=True, filter=False, search=False, sortable=True, overview=True,
        help_text="Point of Hire → site.",
        order=220,
    ),
    "travel_day_mode": field.select(
        tab="travel", label="Travel Day Mode", required=True,
        table=True, filter=True, search=False, sortable=True,
        options=[
            {"value": "fixed", "label": "Fixed (from policy)"},
            {"value": "actual", "label": "Actual Itinerary"},
        ],
        help_text=(
            "Rencana selalu memakai angka di atas. Actual Itinerary "
            "menyalakan langkah kedua: setelah Travel Request disetujui, "
            "selisihnya dilaporkan sebagai usulan penyesuaian — bukan "
            "diterapkan sendiri."
        ),
        order=230,
    ),
    "travel_creates_segment": field.switch(
        tab="travel", label="Create Travel Segments", required=False,
        table=False, filter=False, search=False, sortable=False,
        help_text=(
            "Membuat baris Travel Out / Travel In di jadwal. Dimatikan = "
            "hari perjalanan cuma jadi celah kalender."
        ),
        order=240,
    ),
    "travel_out_counts_as_roster_day": field.switch(
        tab="travel", label="Travel Out Counts As On-Site", required=False,
        table=False, filter=False, search=False, sortable=False,
        help_text=(
            "Hari perjalanan pulang dihitung sebagai hari on-site di "
            "rekap. TIDAK memendekkan blok kerja — pegawai 45/14 yang dua "
            "hari di kapal tetap menjalani 45 hari di site."
        ),
        order=250,
    ),
    "travel_in_counts_as_roster_day": field.switch(
        tab="travel", label="Travel In Counts As On-Site", required=False,
        table=False, filter=False, search=False, sortable=False,
        help_text=(
            "Menyalakan aturan #4 dokumen Substansi Roster: perjalanan "
            "Sorong/Ternate → site sudah dihitung On Site."
        ),
        order=260,
    ),
    "count_transit_overnight": field.switch(
        tab="travel", label="Count Transit Overnight", required=False,
        table=False, filter=False, search=False, sortable=False,
        help_text=(
            "Malam menginap di kota transit ikut dihitung saat "
            "membandingkan rencana dengan itinerary nyata."
        ),
        order=270,
    ),
    "travel_variance_credit_eligible": field.switch(
        tab="travel", label="Travel Variance Earns Credit", required=False,
        table=False, filter=False, search=False, sortable=False,
        help_text=(
            "Bawaannya MATI: pesawat cancel di luar kendali pegawai, dan "
            "yang di luar kendali tidak menghasilkan hak tambahan. "
            "Nyalakan hanya kalau perusahaan memang memutuskan sebaliknya."
        ),
        order=280,
    ),
    "travel_variance_credit_max_days": field.integer(
        tab="travel", label="Variance Credit Max (days)", required=False,
        table=False, filter=False, search=False, sortable=False,
        visible_when={
            "field": "travel_variance_credit_eligible",
            "op": "is_true",
        },
        help_text="0 = tanpa batas.",
        order=290,
    ),
}


CREDIT_FIELDS = {
    "credit_enabled": field.switch(
        tab="credit", label="Enable Rotation Credit", required=False,
        table=True, filter=True, search=False, sortable=True,
        help_text=(
            "Dimatikan = kelebihan hari kerja tidak menghasilkan saldo "
            "apa pun, dan menu Rotation Credit tidak berlaku untuk site "
            "ini."
        ),
        order=310,
    ),
    "conversion_ratio": field.decimal(
        tab="credit", label="Conversion Ratio (override)", required=False,
        table=False, filter=False, search=False, sortable=True,
        visible_when={"field": "credit_enabled", "op": "is_true"},
        help_text=(
            "Dikosongkan = dihitung sendiri dari pola siklus di tab "
            "Cycle Pattern. Diisi hanya kalau perusahaan memakai angka "
            "yang berbeda dari polanya."
        ),
        order=320,
    ),
    "credit_rounding": field.select(
        tab="credit", label="Rounding", required=False,
        table=False, filter=False, search=False, sortable=False,
        visible_when={"field": "credit_enabled", "op": "is_true"},
        options=[
            {"value": "floor", "label": "Round Down"},
            {"value": "half_up", "label": "Round Half Up"},
            {"value": "ceil", "label": "Round Up"},
            {"value": "exact", "label": "Exact (no rounding)"},
        ],
        help_text=(
            "Round Down + Carry Remainder adalah pilihan yang paling "
            "bisa dijelaskan ke pegawai: 7 hari lebih dengan rasio 3 = "
            "2 kredit, sisa 1 hari dibawa ke perhitungan berikutnya."
        ),
        order=330,
    ),
    "credit_carry_remainder": field.switch(
        tab="credit", label="Carry Remainder", required=False,
        table=False, filter=False, search=False, sortable=False,
        visible_when={
            "all": [
                {"field": "credit_enabled", "op": "is_true"},
                {"field": "credit_rounding", "op": "eq", "value": "floor"},
            ],
        },
        help_text=(
            "Sisa hari yang belum genap jadi satu kredit disimpan, bukan "
            "hangus."
        ),
        order=340,
    ),
    "credit_max_balance_days": field.decimal(
        tab="credit", label="Max Balance (days)", required=False,
        table=False, filter=False, search=False, sortable=False,
        visible_when={"field": "credit_enabled", "op": "is_true"},
        help_text="Dikosongkan = tanpa plafon.",
        order=350,
    ),
    "credit_expiry_months": field.integer(
        tab="credit", label="Expiry (months)", required=False,
        table=False, filter=False, search=False, sortable=False,
        visible_when={"field": "credit_enabled", "op": "is_true"},
        help_text=(
            "Dikosongkan = tidak kedaluwarsa. Penjadwal kedaluwarsanya "
            "belum ada, jadi kolom ini belum berpengaruh."
        ),
        order=360,
    ),
    "credit_allow_negative": field.switch(
        tab="credit", label="Allow Negative Balance", required=False,
        table=False, filter=False, search=False, sortable=False,
        visible_when={"field": "credit_enabled", "op": "is_true"},
        help_text="Saldo boleh menembus nol.",
        order=370,
    ),
}


REQUEST_FIELDS = {
    "request_lead_days": field.integer(
        tab="request", label="Request Lead Time (days)", required=False,
        table=True, filter=False, search=False, sortable=True,
        help_text=(
            "Travel Request diajukan minimal sekian hari sebelum "
            "berangkat. 0 = tanpa tenggat."
        ),
        order=410,
    ),
    "notify_lead_days": field.integer(
        tab="request", label="Notify Lead Time (days)", required=False,
        table=False, filter=False, search=False, sortable=True,
        help_text=(
            "Sistem mengingatkan sekian hari sebelum berangkat kalau "
            "Travel Request-nya belum dibuat. Butuh Celery Beat aktif."
        ),
        order=420,
    ),
    "urgent_purposes": field.lookup(
        tab="request", label="Urgent Purposes",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/rotation-purposes/"
        ),
        multiple=True,
        required=False, table=False, filter=False, search=False,
        sortable=False,
        help_text=(
            "Travel Purpose yang boleh menembus tenggat: duka, sakit, "
            "dinas, penyesuaian roster karena ada pengganti."
        ),
        order=430,
    ),
}


ROSTER_POLICY_SCHEMA = {
    "module": "hr/roster-policies",
    "name": "RosterPolicy",
    "label": "Roster Policy",
    "endpoint": "/api/administration/references/hr/roster-policies/",
    "schema_type": "crud",
    "ui": {
        **ui.workspace(
            title="Roster Policy",
            description=(
                "Aturan roster per site: pola siklus, hari perjalanan "
                "menurut Point of Hire, konversi rotation credit, dan "
                "tenggat pengajuan Travel Request."
            ),
            size="full", columns=2,
            create=True, edit=True, delete=True,
            bulk_delete=True, export=True,
        ),
    },
    # Menyalin baris ini ke perusahaan lain, tanpa mengetik
    # ulang. Cakupannya tetap per company — yang ditambahkan
    # cuma cara membuatnya.
    "actions": [
        action.save(),
        action.save_and_close(),
        action.delete(),
        action.export(),
        action.copy_to_companies(
            endpoint="/api/administration/references/hr/roster-policies/",
        ),
    ],

    "tabs": [
        tabs.form(
            key="general", label="Scope",
            fields=list(TARGET_FIELDS.keys()), order=10, show_on_create=True,
        ),
        tabs.form(
            key="cycle", label="Cycle Pattern",
            fields=list(CYCLE_FIELDS.keys()), order=20, show_on_create=True,
        ),
        tabs.form(
            key="travel", label="Travel Rules",
            fields=list(TRAVEL_FIELDS.keys()), order=30, show_on_create=True,
        ),
        tabs.form(
            key="credit", label="Rotation Credit",
            fields=list(CREDIT_FIELDS.keys()), order=40, show_on_create=True,
        ),
        tabs.form(
            key="request", label="Request Rules",
            fields=list(REQUEST_FIELDS.keys()), order=50, show_on_create=True,
        ),
        # Perputaran shift **sebelum** hari perjalanan: yang di sini
        # menentukan jadwal harian seluruh crew, yang di bawah cuma
        # menyesuaikan panjang travel per kota asal. Urutan tab =
        # urutan orang mengisinya saat menyiapkan sebuah site.
        tabs.resource(
            key="shift_rotation",
            label="Shift Rotation",
            endpoint=(
                "/api/administration/references/hr/roster-shift-rotations/"
            ),
            module="hr/roster-shift-rotations",
            foreign_key="policy",
            fields=SHIFT_ROTATION_FIELDS,
            inline=True,
            requires_record=True,
            order=55,
        ),
        tabs.resource(
            key="travel_days",
            label="Travel Days by POH",
            endpoint=(
                "/api/administration/references/hr/roster-travel-days/"
            ),
            module="hr/roster-travel-days",
            foreign_key="policy",
            fields=TRAVEL_DAY_FIELDS,
            inline=True,
            requires_record=True,
            order=60,
        ),
    ],
    "fields": {
        **TARGET_FIELDS,
        **CYCLE_FIELDS,
        **TRAVEL_FIELDS,
        **CREDIT_FIELDS,
        **REQUEST_FIELDS,
        **{
            name: {
                "table": False, "filter": False,
                "search": False, "sortable": False,
            }
            for name in (
                "company_name", "location_name", "travel_day_count",
                "has_cycle_pattern",
            )
        },
    },
}


class RosterPolicyViewSet(
    CompanyCopyViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = RosterPolicySerializer
    service_class = RosterPolicyService

    framework_module = "hr/roster-policies"
    schema = ROSTER_POLICY_SCHEMA

    search_fields = ["code", "name", "description", "location__name"]
    filterset_fields = [
        "company",
        "location",
        "is_default",
        "credit_enabled",
        "travel_day_mode",
    ]
    ordering_fields = [
        "code",
        "name",
        "cycle_work_days",
        "cycle_off_days",
        "created_at",
    ]
    ordering = ["company", "location", "code"]

    def get_queryset(self):
        return (
            RosterPolicy.objects
            .select_related("company", "location")
            .prefetch_related("travel_days")
            .filter(is_deleted=False)
        )


class RosterShiftRotationViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = RosterShiftRotationSerializer
    service_class = RosterShiftRotationService

    framework_module = "hr/roster-shift-rotations"
    schema = ROSTER_SHIFT_ROTATION_SCHEMA

    search_fields = ["shift__code", "shift__name", "notes"]
    filterset_fields = ["policy", "shift"]
    ordering_fields = ["sequence", "block_days"]
    ordering = ["sequence"]

    def get_queryset(self):
        # Queryset konkret, sama seperti `RosterTravelDayViewSet` di
        # bawah: `BaseMasterService` tidak punya `list()`, jadi
        # `super().get_queryset()` justru melempar AssertionError.
        return (
            RosterShiftRotation.objects
            .select_related("policy", "shift")
            .filter(is_deleted=False)
        )


class RosterTravelDayViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = RosterTravelDaySerializer
    service_class = RosterTravelDayService

    framework_module = "hr/roster-travel-days"
    schema = ROSTER_TRAVEL_DAY_SCHEMA

    search_fields = ["point_of_hire__name", "notes"]
    filterset_fields = ["policy", "point_of_hire"]
    ordering_fields = [
        "point_of_hire__name",
        "travel_out_days",
        "travel_in_days",
    ]
    ordering = ["point_of_hire__name"]

    def get_queryset(self):
        return (
            RosterTravelDay.objects
            .select_related("policy", "point_of_hire")
            .filter(is_deleted=False)
        )
