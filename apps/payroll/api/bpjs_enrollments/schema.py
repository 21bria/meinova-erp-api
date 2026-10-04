"""
Schema UI kepesertaan BPJS.

**Tidak ada baris = tidak ikut.** Layar ini karena itu bukan pelengkap
administratif: pegawai yang tidak punya baris di sini tidak dipotong
iuran apa pun, dan itu memang perilaku yang diminta — bukan kelalaian
yang perlu diperingatkan.
"""

from apps.framework.builders import field, ui


BPJS_ENROLLMENT_SCHEMA = {
    "module": "payroll/bpjs-enrollments",
    "name": "BpjsEnrollment",
    "label": "BPJS Enrollment",
    "endpoint": "/api/payroll/bpjs-enrollments/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="BPJS Enrollments",
            description=(
                "Kepesertaan pegawai per program. Pegawai tanpa "
                "kepesertaan aktif tidak dipotong iuran program itu."
            ),
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            export=True,
        ),
    },

    "fields": {
        "employee": field.lookup(
            label="Employee",
            lookup_endpoint="/api/hr/employees/lookup/",
            display_key="employee_name",
            required=True,
            table=True,
            filter=True,
            search=True,
            order=10,
        ),
        "program": field.lookup(
            label="Program",
            lookup_endpoint="/api/payroll/bpjs-programs/lookup/",
            display_key="program_name",
            required=True,
            table=True,
            filter=True,
            order=20,
        ),
        "participates": field.boolean(
            label="Participates",
            default=True,
            table=True,
            filter=True,
            order=30,
        ),
        "enrolled_from": field.date(
            label="Enrolled From",
            required=True,
            table=True,
            sortable=True,
            filter=True,
            order=40,
        ),
        "enrolled_to": field.date(
            label="Enrolled To",
            table=True,
            sortable=True,
            order=50,
            help_text="Kosong = masih terdaftar.",
        ),
        "risk_class": field.lookup(
            label="Risk Class",
            lookup_endpoint="/api/payroll/bpjs-risk-classes/lookup/",
            display_key="risk_class_name",
            required=False,
            table=True,
            filter=True,
            order=55,
            help_text=(
                "Wajib untuk program yang memakai kelas risiko. "
                "Perpindahan kelas ditulis sebagai penutupan "
                "kepesertaan lama dan pembukaan yang baru, supaya "
                "riwayatnya tidak tertulis ulang."
            ),
        ),
        "membership_number": field.text(
            label="Membership Number",
            table=True,
            search=True,
            order=60,
            help_text=(
                "Kosong tetap dihitung iurannya, dengan peringatan — "
                "iuran yang hilang karena satu kolom administratif "
                "belum diisi adalah gaji yang salah."
            ),
        ),
        "notes": field.textarea(
            label="Notes", rows=3, layout="full", table=False, order=70,
        ),
        "is_active": field.boolean(
            label="Active", default=True, table=True, filter=True, order=999,
        ),
    },
}
