from apps.framework.builders import field


ORGANIZATION_FIELDS = {
    "company": field.lookup(
        tab="organization",
        label="Company",
        lookup_endpoint=(
            "/api/administration/organization/lookup/companies/"
        ),
        required=True,
        # Nomor pegawai mengikuti kode company, jadi memilih company
        # langsung memperlihatkan nomor yang akan terbit di tab General
        # — bukan kotak kosong berlabel "terisi otomatis" yang tidak
        # memberi tahu apa-apa sampai Simpan ditekan.
        autofill={"employee_number": "next_employee_number"},
        # Tampil di tabel: daftar pegawai tanpa kolom Company tidak bisa
        # dibaca di tenant berisi lebih dari satu badan usaha — dua
        # orang bernomor mirip dari perusahaan berbeda terlihat seperti
        # duplikat yang perlu dibersihkan.
        table=True,
        display_key="company_name",
        filter=True,
        order=10,
    ),

    "branch": field.lookup(
        tab="organization",
        label="Branch",
        lookup_endpoint=(
            "/api/administration/organization/lookup/branches/"
        ),
        depends_on="company",
        lookup_params={
            "company_id": "$company",
        },
        table=False,
        filter=True,
        order=20,
    ),

    # Wajib, walau di master organisasi Location boleh kosong.
    #
    # Dua hal menempel ke kolom ini dan dua-duanya gagal diam-diam kalau
    # dibiarkan kosong: cakupan data (`DATA_SCOPE_INCLUDE_NULL=False`
    # membuat pegawai tanpa lokasi **tidak terlihat siapa pun** kecuali
    # superuser — termasuk oleh admin yang baru saja membuatnya), dan
    # kalender kerja yang menentukan potongan hari cuti. Boleh kosong di
    # model tetap dipertahankan untuk importer dan data lama.
    "location": field.lookup(
        tab="organization",
        label="Location",
        lookup_endpoint=(
            "/api/administration/organization/lookup/locations/"
        ),
        depends_on="company",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
        },
        required=True,
        # Penempatan kerja fisik — yang menentukan absensi, shift,
        # kalender libur, dan cakupan data. Kolom yang paling sering
        # ditanyakan setelah nama.
        table=True,
        display_key="location_name",
        filter=True,
        order=30,
    ),

    "division": field.lookup(
        tab="organization",
        label="Division",
        lookup_endpoint=(
            "/api/administration/organization/lookup/divisions/"
        ),
        depends_on="company",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
            "location_id": "$location",
        },
        table=False,
        filter=True,
        order=40,
    ),

    "department": field.lookup(
        tab="organization",
        label="Department",
        lookup_endpoint=(
            "/api/administration/organization/lookup/departments/"
        ),
        depends_on="company",
        lookup_params={
            "company_id": "$company",
            "location_id": "$location",
            "division_id": "$division",
        },
        table=False,
        filter=True,
        order=50,
    ),

    "section": field.lookup(
        tab="organization",
        label="Section",
        lookup_endpoint=(
            "/api/administration/organization/lookup/sections/"
        ),
        depends_on="company",
        lookup_params={
            "company_id": "$company",
            "location_id": "$location",
            "division_id": "$division",
            "department_id": "$department",
        },
        table=False,
        filter=True,
        order=60,
    ),

    "position": field.lookup(
        tab="organization",
        label="Position",
        lookup_endpoint=(
            "/api/administration/organization/lookup/positions/"
        ),
        depends_on="company",
        lookup_params={
            "company_id": "$company",
            "location_id": "$location",
            "division_id": "$division",
            "department_id": "$department",
            "section_id": "$section",
        },
        table=False,
        filter=True,
        order=70,
    ),

    "job_level": field.lookup(
        tab="organization",
        label="Job Level",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/job-levels/"
        ),
        table=False,
        filter=True,
        order=80,
    ),

    "job_grade": field.lookup(
        tab="organization",
        label="Job Grade",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/job-grades/"
        ),
        table=False,
        filter=True,
        order=90,
    ),

    "reports_to": field.lookup(
        tab="organization",
        label="Reports To",
        lookup_endpoint="/api/hr/employees/lookup/",
        # Tanpa `display_key` generator jatuh ke `reports_to_name`, dan
        # kebetulan itu memang nama field yang dikirim serializer — tapi
        # disebut eksplisit supaya kaitannya terbaca dari sini juga.
        display_key="reports_to_name",
        depends_on="company",
        lookup_params={
            "company_id": "$company",
        },
        table=False,
        filter=True,
        order=100,
    ),

    "cost_center": field.lookup(
        tab="organization",
        label="Cost Center",
        lookup_endpoint=(
            "/api/administration/organization/"
            "lookup/cost-centers/"
        ),
        depends_on="company",
        lookup_params={
            "company_id": "$company",
        },
        table=False,
        filter=True,
        order=120,
    ),

    # `project` DIHAPUS dari sini — rusak di tiga tempat sekaligus, dan
    # ketiganya gagal tanpa suara:
    #
    # 1. `OrganizationAssignment` tidak punya kolom `project` sama
    #    sekali;
    # 2. namanya tidak terdaftar di `EmployeeSerializer.fields`, jadi
    #    nilainya dibuang setelah PATCH membalas 200;
    # 3. `lookup_endpoint`-nya `/api/administration/projects/lookup/`
    #    membalas 404 — dropdown kosong tanpa pesan.
    #
    # Kalau penempatan per proyek nanti memang dibutuhkan, yang harus
    # ditambah lebih dulu adalah modelnya, bukan menghidupkan lagi field
    # ini.

    "organization_effective_date": field.date(
        tab="organization",
        label="Effective Date",
        required=True,
        table=False,
        order=140,
    ),

    "organization_notes": field.textarea(
        tab="organization",
        label="Organization Notes",
        rows=4,
        layout="full",
        table=False,
        order=150,
    ),
}