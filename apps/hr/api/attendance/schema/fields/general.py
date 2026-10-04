from apps.framework import list_period
from apps.framework.builders import field


GENERAL_FIELDS = {
    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        # Hanya pegawai yang Attendance-nya memang berlaku (Employee
        # Group → Feature Applicability). Konstanta, bukan `$field`,
        # jadi tidak ada induk yang harus diisi lebih dulu.
        lookup_params={"feature": "attendance"},
        autofill={
            "company": "company",
            "branch": "branch",
            "location": "location",
        },
        display_key="employee_name",
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        order=10,
    ),

    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        required=True,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        order=20,
    ),

    "branch": field.lookup(
        tab="general",
        label="Branch",
        lookup_endpoint="/api/administration/organization/lookup/branches/",
        display_key="branch_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        order=30,
    ),

    "location": field.lookup(
        tab="general",
        label="Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        order=40,
    ),

    "work_date": field.date(
        tab="general",
        label="Work Date",
        required=True,
        table=True,
        # Penyaring utama layar ini, dan satu-satunya yang wajib.
        #
        # `type: "dateRange"` membuat generator memancarkan pemilih
        # rentang, bukan kotak tanggal tunggal — yang terakhir menuntut
        # orang menebak **satu** tanggal persis, dan daftar presensi
        # tidak pernah dibaca begitu.
        #
        # `order: 1` menaruhnya di depan seluruh penyaring lain. Itu
        # bukan selera tata letak: rentang adalah cakupan yang berlaku
        # lebih dulu, dan filter yang tampil sebelum periodenya terbaca
        # seperti berlaku atas seluruh sejarah.
        #
        # `params` menyebut nama query string-nya supaya frontend tidak
        # menurunkannya sendiri; yang membacanya di backend
        # `apps.framework.list_period`, dan dua sisi yang mengeja
        # parameter yang sama sendiri-sendiri cepat atau lambat
        # berbeda.
        filter={
            "group": "quick",
            "order": 1,
            "type": "dateRange",
            "required": True,
            "params": {
                "from": list_period.FROM_PARAM,
                "to": list_period.TO_PARAM,
            },
            "default": list_period.DEFAULT_RANGE,
            "max_days": list_period.MAX_RANGE_DAYS,
            "presets": list(list_period.DEFAULT_PRESETS),
        },
        search=False,
        sortable=True,
        order=50,
    ),

    "shift": field.lookup(
        tab="general",
        label="Shift",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/shifts/"
        ),
        display_key="shift_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=60,
    ),

    "status": field.select(
        tab="general",
        label="Attendance Status",
        display_key="status_label",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        options=[
            {"label": "Present", "value": "present"},
            {"label": "Late", "value": "late"},
            {"label": "Absent", "value": "absent"},
            {"label": "Leave", "value": "leave"},
            {"label": "Sick", "value": "sick"},
            {"label": "Permit", "value": "permit"},
            # Ditulis sistem (penutup hari dari Business Trip yang
            # disetujui), bukan dipilih tangan — BT-5. `disabled`, bukan
            # dibuang: baris lama tetap terbaca di form, dan filter daftar
            # (yang hanya menyalin label/value) tetap bisa mencarinya.
            {
                "label": "Business Trip",
                "value": "business_trip",
                "disabled": True,
            },
            {"label": "Remote Work", "value": "remote"},
            {"label": "Holiday", "value": "holiday"},
            {"label": "Day Off", "value": "day_off"},
            {"label": "Incomplete", "value": "incomplete"},
        ],
        order=70,
    ),

    "source": field.select(
        tab="general",
        label="Source",
        display_key="source_label",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        options=[
            {"label": "Manual", "value": "manual"},
            {"label": "Attendance Device", "value": "device"},
            {"label": "Mobile", "value": "mobile"},
            {"label": "Web", "value": "web"},
            {"label": "Import", "value": "import"},
            {"label": "API", "value": "api"},
            {"label": "System", "value": "system"},
        ],
        order=80,
    ),
}