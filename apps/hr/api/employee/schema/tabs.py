from apps.framework.builders import tabs

from .fields import (
    GENERAL_FIELDS,
    ORGANIZATION_FIELDS,
    EMPLOYMENT_FIELDS,
    employment_tab_fields,
    PAYROLL_FIELDS,
    BANK_FIELDS,
    CERTIFICATE_FIELDS,
    DOCUMENT_FIELDS,
    EDUCATION_FIELDS,
    EXPERIENCE_FIELDS,
    FAMILY_FIELDS,
    MEDICAL_FIELDS,
    TRAINING_FIELDS,
)


EMPLOYEE_TABS = [
   tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),

    tabs.form(
        key="organization",
        label="Organization",
        fields=list(ORGANIZATION_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),

    # Employment dipecah tiga, dan pemisahannya bukan kosmetik.
    #
    # "Current Employment" adalah keadaan sekarang dan boleh dikoreksi.
    # "Contract & Probation" memuat kolom yang punya sejarah — isian
    # awalnya boleh diketik saat pegawainya dibuat, perubahan
    # sesudahnya ditolak `EmploymentService.assert_not_protected()` dan
    # diarahkan ke Employee Action. "Work Arrangement" bukan dua-duanya:
    # pola kerja, kalender, dan shift adalah pengaturan operasional yang
    # memang berubah tanpa dokumen, jadi ia tidak boleh ikut terkunci
    # gara-gara duduk di tab yang sama dengan kontrak.
    tabs.form(
        key="employment",
        label="Current Employment",
        fields=employment_tab_fields("employment"),
        order=30,
        show_on_create=True,
    ),

    tabs.form(
        key="contract",
        label="Contract & Probation",
        fields=employment_tab_fields("contract"),
        order=32,
        show_on_create=True,
    ),

    tabs.form(
        key="work_arrangement",
        label="Work Arrangement",
        fields=employment_tab_fields("work_arrangement"),
        order=34,
        show_on_create=True,
    ),

    tabs.resource(
        key="payroll",
        label="Payroll",
        endpoint="/api/hr/payroll-assignments/",
        foreign_key="employee",
        fields=PAYROLL_FIELDS,
        requires_record=True, #Saat mode create, employee belum punya recordId, jadi workspace menganggap tab itu belum boleh dibuka.
        show_on_create=False,
        order=40,
        dialog={
            "title": "Payroll Assignment",
            "size": "xl",
            "columns": 2,
        },
    ),


    tabs.resource(
        key="bank",
        label="Bank Accounts",
        endpoint="/api/hr/employee-bank-accounts/",
        foreign_key="employee",
        fields=BANK_FIELDS,
        requires_record=True,
        show_on_create=False,
        order=50,
        dialog={
            "title": "Bank Account",
            "size": "lg",
            "columns": 2,
            "create_label": "Add Bank Account",
        },
    ),

    tabs.resource(
        key="family",
        label="Family",
        endpoint="/api/hr/employee-families/",
        foreign_key="employee",
        fields=FAMILY_FIELDS,
        requires_record=True,
        show_on_create=False,
        order=60,
    ),

    tabs.resource(
        key="education",
        label="Education",
        endpoint="/api/hr/employee-educations/",
        foreign_key="employee",
        fields=EDUCATION_FIELDS,
        requires_record=True,
        show_on_create=False,
        order=70,
    ),

    tabs.resource(
        key="experience",
        label="Experience",
        endpoint="/api/hr/employee-experiences/",
        foreign_key="employee",
        fields=EXPERIENCE_FIELDS,
        requires_record=True,
        show_on_create=False,
        order=80,
    ),

    tabs.resource(
        key="certificate",
        label="Certificates",
        endpoint="/api/hr/employee-certificates/",
        foreign_key="employee",
        fields=CERTIFICATE_FIELDS,
        requires_record=True,
        show_on_create=False,
        order=90,
    ),

    tabs.resource(
        key="document",
        label="Documents",
        endpoint="/api/hr/employee-documents/",
        foreign_key="employee",
        fields=DOCUMENT_FIELDS,
        requires_record=True,
        show_on_create=False,
        order=100,
    ),

    tabs.resource(
        key="medical",
        label="Medical",
        endpoint="/api/hr/employee-medical-events/",
        foreign_key="employee",
        fields=MEDICAL_FIELDS,
        requires_record=True,
        show_on_create=False,
        order=110,
    ),

    tabs.resource(
        key="training",
        label="Training",
        endpoint="/api/hr/employee-trainings/",
        foreign_key="employee",
        fields=TRAINING_FIELDS,
        requires_record=True,
        show_on_create=False,
        order=120,
    ),

    # Dokumen perubahan kepegawaian **tidak** punya tab di sini, dan itu
    # disengaja: kartu Employee menampilkan keadaan sekarang, sedangkan
    # Employee Action adalah dokumen berjalan dengan status dan alurnya
    # sendiri. Menaruh daftarnya sebagai tab membuat satu layar
    # menjawab dua pertanyaan berbeda, dan yang kedua sudah punya
    # modulnya sendiri (`HR → Employee Actions`) lengkap dengan tombol
    # Submit/Approve.
    #
    # Yang tersisa di kartu pegawai cuma pintu masuknya — tombol
    # "Actions" di kepala layar (`EMPLOYEE_SCHEMA["actions"]`), yang
    # membuka form dokumen yang sama dengan pegawainya sudah terisi.
    # Hasilnya tetap terbaca di tab History begitu dokumennya
    # diterapkan.
    tabs.history(
        key="history",
        label="History",
        component="EmployeesHistory",
        endpoint=(
            "/api/hr/employees/{employee_id}/employment-history/"
        ),
        requires_record=True,
        show_on_create=False,
        order=130,
    ),

    tabs.custom(
        key="activity",
        label="Activity",
        component="EmployeesActivity",
        icon="activity",
        requires_record=True,
        show_on_create=False,
        order=140,
    ),
]