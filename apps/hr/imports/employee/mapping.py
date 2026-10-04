from __future__ import annotations


# target -> alias header yang diterima (lowercase).
# Alias Indonesia disertakan karena file klien umumnya berbahasa Indonesia.
# Klien dengan header lain cukup menambah mapping di ImportProfile,
# tanpa mengubah file ini.
EMPLOYEE_IMPORT_MAPPING: dict[str, list[str]] = {
    # ------------------------------------------------------------------
    # Identitas
    # ------------------------------------------------------------------
    "employee_number": [
        "employee_number",
        "employee_code",
        "employee_id",
        "emp_no",
        "nip",
        "no_induk",
        "nomor_induk",
    ],

    "nik": [
        "nik",
        "national_id",
        "ktp",
        "no_ktp",
        "nomor_ktp",
    ],

    "passport_number": [
        "passport_number",
        "passport",
        "paspor",
        "no_paspor",
    ],

    "tax_number": [
        "tax_number",
        "npwp",
        "no_npwp",
    ],

    # ------------------------------------------------------------------
    # Nama
    # ------------------------------------------------------------------
    "full_name": [
        "full_name",
        "nama_lengkap",
        "nama",
        "name",
    ],

    "first_name": [
        "first_name",
        "nama_depan",
        "given_name",
    ],

    "last_name": [
        "last_name",
        "nama_belakang",
        "surname",
        "family_name",
    ],

    # ------------------------------------------------------------------
    # Data pribadi (referensi)
    # ------------------------------------------------------------------
    "gender": [
        "gender",
        "jenis_kelamin",
        "sex",
    ],

    "religion": [
        "religion",
        "agama",
    ],

    "nationality": [
        "nationality",
        "kewarganegaraan",
        "warga_negara",
    ],

    "blood_type": [
        "blood_type",
        "golongan_darah",
        "gol_darah",
    ],

    "marital_status": [
        "marital_status",
        "status_pernikahan",
        "status_kawin",
        "status_perkawinan",
    ],

    "birth_place": [
        "birth_place",
        "tempat_lahir",
        "pob",
    ],

    "birth_date": [
        "birth_date",
        "tanggal_lahir",
        "tgl_lahir",
        "dob",
    ],

    # ------------------------------------------------------------------
    # Kontak
    # ------------------------------------------------------------------
    "personal_email": [
        "personal_email",
        "email_pribadi",
        "email",
    ],

    "work_email": [
        "work_email",
        "email_kantor",
        "company_email",
    ],

    "phone": [
        "phone",
        "telepon",
        "telp",
        "no_telepon",
    ],

    "mobile": [
        "mobile",
        "mobile_phone",
        "handphone",
        "hp",
        "no_hp",
    ],

    "emergency_contact_name": [
        "emergency_contact_name",
        "nama_kontak_darurat",
        "kontak_darurat",
    ],

    "emergency_contact_phone": [
        "emergency_contact_phone",
        "telepon_darurat",
        "hp_darurat",
    ],

    "notes": [
        "notes",
        "catatan",
        "keterangan",
    ],

    "is_active": [
        "is_active",
        "active",
        "aktif",
        "status_aktif",
    ],

    # ------------------------------------------------------------------
    # Penempatan organisasi
    # ------------------------------------------------------------------
    # `company_code` sengaja diletakkan sebelum `company_name`: kalau
    # file memuat keduanya, kode yang dipakai karena lebih tegas.
    "company": [
        "company",
        "company_code",
        "perusahaan",
        "kode_perusahaan",
        "company_name",
        "nama_perusahaan",
    ],

    "branch": [
        "branch",
        "branch_code",
        "cabang",
    ],

    # `site` dan `site_code` sengaja dipertahankan: nama master-nya
    # berubah jadi Location, tapi file klien lama masih berjudul "site".
    "location": [
        "location",
        "location_code",
        "lokasi",
        "site",
        "site_code",
    ],

    "division": [
        "division",
        "divisi",
    ],

    "department": [
        "department",
        "departemen",
        "bagian",
    ],

    "section": [
        "section",
        "seksi",
        "sub_bagian",
    ],

    "position": [
        "position",
        "jabatan",
        "posisi",
    ],

    "job_level": [
        "job_level",
        "level_jabatan",
        "level",
    ],

    "job_grade": [
        "job_grade",
        "grade",
        "golongan",
    ],

    "cost_center": [
        "cost_center",
        "pusat_biaya",
    ],

    "organization_effective_date": [
        "organization_effective_date",
        "effective_date",
        "tanggal_efektif",
        "join_date",
        "hire_date",
        "tanggal_masuk",
        "tgl_masuk",
    ],

    # ------------------------------------------------------------------
    # Kepegawaian
    # ------------------------------------------------------------------
    # `join_date` sengaja berbagi alias dengan
    # `organization_effective_date`: satu kolom "hire_date" mengisi dua
    # target — tanggal berlaku penempatan organisasi dan tanggal
    # bergabung di data kepegawaian.
    "join_date": [
        "join_date",
        "hire_date",
        "tanggal_masuk",
        "tgl_masuk",
        "tanggal_bergabung",
    ],

    "contract_start": [
        "contract_start",
        "start_contract",
        "mulai_kontrak",
        "tanggal_mulai_kontrak",
    ],

    "contract_end": [
        "contract_end",
        "end_contract",
        "akhir_kontrak",
        "tanggal_akhir_kontrak",
        "berakhir_kontrak",
    ],

    "contract_type": [
        "contract_type",
        "jenis_kontrak",
        "tipe_kontrak",
    ],

    "employment_status": [
        "employment_status",
        "status_kepegawaian",
        "status_karyawan",
    ],

    "employment_type": [
        "employment_type",
        "tipe_kepegawaian",
        "jenis_kepegawaian",
    ],

    # Teks bebas, bukan relasi ke master Location.
    "job_location": [
        "job_location",
        "lokasi_kerja",
        "penempatan",
        "work_location",
    ],

    # ------------------------------------------------------------------
    # Payroll
    # ------------------------------------------------------------------
    # Status PTKP (TK/0, K/1, ...) adalah master `payroll.TaxStatus`,
    # bukan Marital Status (S/M/D/W). File klien sering menaruhnya di
    # kolom bernama "status"; kalau begitu, arahkan lewat `mapping`
    # pada ImportProfile.
    "tax_status": [
        "tax_status",
        "tax_status_code",
        "ptkp",
        "ptkp_status",
        "status_ptkp",
        "status_pajak",
    ],

    "payroll_group": [
        "payroll_group",
        "grup_payroll",
        "kelompok_payroll",
    ],

    "payroll_currency": [
        "payroll_currency",
        "mata_uang_payroll",
    ],

    # ------------------------------------------------------------------
    # Rekening bank
    # ------------------------------------------------------------------
    "bank": [
        "bank",
        "bank_code",
        "kode_bank",
        "bank_name",
        "nama_bank",
    ],

    "bank_account_number": [
        "bank_account_number",
        "account_number",
        "no_rekening",
        "nomor_rekening",
        "rekening",
    ],

    "bank_account_name": [
        "bank_account_name",
        "account_name",
        "nama_rekening",
        "atas_nama",
    ],

    "bank_branch_name": [
        "bank_branch_name",
        "bank_branch",
        "cabang_bank",
    ],

    "bank_currency": [
        "bank_currency",
        "currency",
        "mata_uang",
    ],

    # ------------------------------------------------------------------
    # Pendidikan
    # ------------------------------------------------------------------
    "education": [
        "education",
        "education_level",
        "pendidikan",
        "jenjang",
        "tingkat_pendidikan",
    ],

    "degree": [
        "degree",
        "gelar",
    ],

    "study_field": [
        "study_field",
        "jurusan",
        "bidang_studi",
        "major",
    ],

    "institution_name": [
        "institution_name",
        "institution",
        "nama_institusi",
        "universitas",
        "sekolah",
    ],

    "graduation_year": [
        "graduation_year",
        "tahun_lulus",
        "year_graduated",
    ],

    "gpa": [
        "gpa",
        "ipk",
    ],
}
