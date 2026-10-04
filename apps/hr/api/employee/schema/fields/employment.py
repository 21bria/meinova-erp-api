"""
Field tab Employment, dipecah jadi tiga kelompok.

Dulu delapan belas kolom duduk di satu tab, dan akibatnya keadaan
sekarang, riwayat kontrak, masa percobaan, dan pola kerja terlihat
seperti satu tumpukan yang sama-sama boleh diketik ulang kapan saja.
Padahal isinya tiga hal berbeda:

* ``employment``      — **keadaan sekarang**. Boleh dikoreksi HR.
* ``contract``        — **kontrak & probation**. Keadaan awal boleh
  diisi saat pegawainya dibuat; perubahan sesudahnya lewat Employee
  Action, dan penjagaannya ada di `EmploymentService.PROTECTED_FIELDS`,
  bukan cuma di tampilan.
* ``work_arrangement`` — **pola kerja**. Bukan kontrak, bukan riwayat;
  dipisah supaya tidak ikut terkunci.

Dua kolom kontrak hanya tampil kalau jenis kepegawaiannya memang
berkontrak (`visible_when`), dan tanggal probation hanya tampil kalau
Probation Type dipilih. Syaratnya ditulis di schema, bukan ditanam di
komponen — layar mana pun yang memakai field ini ikut benar.
"""

from apps.framework.builders import field


# Syarat tampil kolom kontrak. Dibaca dari nilai form
# `employment_type_requires_contract`, yang diisi dua jalur: serializer
# saat form dimuat, dan `autofill` pada Employment Type begitu jenisnya
# diganti. Bukan dari kode master — tenant yang menamai jenis
# kepegawaiannya sendiri tidak boleh kehilangan kolom kontraknya.
WHEN_CONTRACT_BASED = {
    "field": "employment_type_requires_contract",
    "op": "is_true",
}


# Tanggal probation hanya masuk akal kalau masa percobaannya memang
# dipakai. Probation Type kosong adalah jawaban yang sah.
WHEN_PROBATION = {
    "field": "probation_type",
    "op": "is_not_null",
}


def _when_applicable(feature: str) -> dict:
    """
    Syarat tampil kolom yang tergantung Feature Applicability.

    Bentuknya **`not is_false`**, bukan `is_true`, dan bedanya menentukan
    di layar create: sebelum Employee Group dipilih nilainya belum ada,
    dan `is_true` atas nilai yang belum ada berarti **sembunyi** —
    kolom Shift dan Roster Policy hilang dari form pegawai baru sampai
    seseorang menebak bahwa group-lah yang memunculkannya. `not is_false`
    membuat "belum dikonfigurasi" sama dengan "seperti kemarin", aturan
    yang sama dengan `default=True` pada masternya.

    Nilainya cermin dari master, diisi dua jalur seperti
    `employment_type_requires_contract`: serializer saat form dimuat,
    dan `autofill` pada field Employee Group begitu group-nya diganti.
    """
    return {
        "not": {
            "field": f"employee_group_{feature}_applicable",
            "op": "is_false",
        },
    }


WHEN_SHIFT_APPLICABLE = _when_applicable("shift")
WHEN_ROSTER_APPLICABLE = _when_applicable("roster")


EMPLOYMENT_FIELDS = {
    "employment_status": field.lookup(
        tab="employment",
        label="Employment Status",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/employment-statuses/"
        ),
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=10,
    ),

    "employment_type": field.lookup(
        tab="employment",
        label="Employment Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/employment-types/"
        ),
        required=True,
        # Menyalin `requires_contract` milik jenis yang dipilih ke field
        # tersembunyi di bawah, yang jadi syarat tampil kolom kontrak.
        # `EmploymentTypeLookup.serialize()` yang mengirim kuncinya —
        # kalau dicabut dari sana, kolom kontraknya berhenti muncul saat
        # jenisnya diganti dan tidak ada error apa pun.
        autofill={
            "employment_type_requires_contract": "requires_contract",
        },
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=20,
    ),

    # Bukan kolom model — cermin dari master, dipakai sebagai syarat
    # tampil kolom kontrak. Tersembunyi: yang menentukannya Employment
    # Type di atas, dan dua kenop untuk satu keputusan cuma bikin
    # keduanya bisa berbeda.
    "employment_type_requires_contract": field.switch(
        tab="contract",
        label="Contract Based",
        hidden=True,
        read_only=True,
        display=True,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=1,
    ),

    "employee_group": field.lookup(
        tab="employment",
        label="Employee Group",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/employee-groups/"
        ),
        # Menyalin Feature Applicability milik group yang dipilih ke dua
        # field tersembunyi di tab Work Arrangement, yang jadi syarat
        # tampil kolom Shift dan Roster. `EmployeeGroup` lookup
        # (`serialize()`) yang mengirim kuncinya — kalau dicabut dari
        # sana, kolomnya berhenti bereaksi saat group-nya diganti dan
        # tidak ada error apa pun.
        autofill={
            "employee_group_shift_applicable": "shift_applicable",
            "employee_group_roster_applicable": "roster_applicable",
        },
        table=False,
        filter=True,
        search=False,
        sortable=False,
        help_text=(
            "Klasifikasi pegawai — dan sumber Feature Applicability: "
            "proses HR mana yang berlaku untuknya. Diatur di master "
            "Employee Group, bukan di sini."
        ),
        order=30,
    ),

    "employment_effective_date": field.date(
        tab="employment",
        label="Employment Effective Date",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=40,
    ),

    # ------------------------------------------------------------------
    # Contract & Probation
    # ------------------------------------------------------------------
    #
    # Boleh diisi saat pegawainya dibuat — itu keadaan awal, belum ada
    # sejarah yang bisa hilang. Perubahan sesudahnya ditolak
    # `EmploymentService.assert_not_protected()` dengan pesan yang
    # menyebut Employee Action mana yang harus dipakai. Menyembunyikan
    # kolomnya saja tidak cukup: pemanggil API langsung tidak lewat
    # form.

    "contract_type": field.lookup(
        tab="contract",
        label="Contract Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/contract-types/"
        ),
        visible_when=WHEN_CONTRACT_BASED,
        help_text=(
            "Hanya untuk jenis kepegawaian berkontrak. Perpanjangan "
            "dan perubahan kontrak pegawai yang sudah ada lewat "
            "Employee Action."
        ),
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=50,
    ),

    "probation_type": field.lookup(
        tab="contract",
        label="Probation Type",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/probation-types/"
        ),
        help_text=(
            "Kosongkan kalau pegawai ini tidak menjalani masa "
            "percobaan — tanggalnya ikut tersembunyi."
        ),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=60,
    ),

    "join_date": field.date(
        tab="employment",
        label="Join Date",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=70,
    ),

    # Teks bebas, bukan lookup: file klien memuat nilai seperti
    # "Gebe/Bacan/Ternate" yang tidak bisa dipetakan ke satu Location.
    "job_location": field.text(
        tab="employment",
        label="Job Location",
        placeholder="mis. Jakarta / Gebe",
        table=False,
        filter=True,
        search=True,
        sortable=True,
        order=75,
    ),

    # Kota rekrut, penentu tujuan tiket pulang tiap blok off — "Point Of
    # Hire" di form Travel Request. Ini lookup ke master kota, beda dengan
    # `job_location` di atas yang sengaja teks bebas.
    "point_of_hire": field.lookup(
        tab="employment",
        label="Point of Hire",
        lookup_endpoint=(
            "/api/administration/references/geography/lookup/cities/"
        ),
        display_key="point_of_hire_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Kota tempat pegawai direkrut. Ke sinilah tiket pulang "
            "ditanggung saat blok off, bukan ke alamat domisili."
        ),
        order=76,
    ),

    "confirmation_date": field.date(
        tab="employment",
        label="Confirmation Date",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=80,
    ),

    "probation_start": field.date(
        tab="contract",
        label="Probation Start",
        visible_when=WHEN_PROBATION,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=90,
    ),

    "probation_end": field.date(
        tab="contract",
        label="Probation End",
        visible_when=WHEN_PROBATION,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=100,
    ),

    "contract_start": field.date(
        tab="contract",
        label="Contract Start",
        visible_when=WHEN_CONTRACT_BASED,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=110,
    ),

    "contract_end": field.date(
        tab="contract",
        label="Contract End",
        visible_when=WHEN_CONTRACT_BASED,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=120,
    ),

    # Dua field ini paling sering ketuker, dan urutannya di form
    # sengaja dibalik: Roster Crew lebih dulu, Work Schedule
    # mengikutinya. Pegawai HO tidak punya crew dan memilih pola
    # kerjanya langsung; pegawai site memilih crew, dan polanya sudah
    # ditentukan gelombang itu — `EmploymentAssignment.clean()` menolak
    # kalau keduanya berbeda.
    # ------------------------------------------------------------------
    # Roster
    # ------------------------------------------------------------------
    #
    # Dua kolom ini yang menentukan apakah pegawai diproses Roster
    # Generator. Ditaruh **sebelum** Roster Crew karena sejak pola
    # pindah ke policy, Roster Policy-lah yang menentukan dan crew
    # mengikutinya — `EmploymentAssignment.clean()` menolak kalau
    # polanya berbeda.
    "roster_policy": field.lookup(
        tab="work_arrangement",
        label="Roster Policy",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/roster-policies/"
        ),
        display_key="roster_policy_name",
        depends_on=["company"],
        lookup_params={
            "company_id": "$company",
            "location_id": "$location",
        },
        # Memilih policy langsung memperlihatkan pola dan panjang
        # siklusnya, jadi yang mengisi Current Cycle Start tahu tanggal
        # apa yang sedang dimintanya. Tanpa ini, angka yang menentukan
        # seluruh jadwal seseorang baru terbaca setelah dokumennya jadi.
        autofill={
            "roster_policy_cycle_length": "cycle_length",
            "work_schedule": "work_schedule",
        },
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        visible_when=WHEN_ROSTER_APPLICABLE,
        help_text=(
            "Pola roster pegawai site (6:2, 8:2, …). Kosongkan untuk "
            "pegawai kantor — tanpa policy, jadwal roster tidak pernah "
            "dibuatkan."
        ),
        order=126,
    ),
    "roster_cycle_start": field.date(
        tab="work_arrangement",
        label="Current Cycle Start",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        # Kolom ini tidak punya arti tanpa policy: yang menentukan apa
        # arti tanggalnya adalah Cycle Start Basis milik policy.
        visible_when={"field": "roster_policy", "op": "is_not_null"},
        help_text=(
            "Titik jangkar siklus pegawai INI — boleh berbeda dari "
            "rekan satu policy. Artinya mengikuti Cycle Start Basis "
            "pada policy: hari pertama kerja, hari tiba di site, atau "
            "hari berangkat dari Point of Hire. Boleh tanggal lampau."
        ),
        order=127,
    ),
    "roster_crew": field.lookup(
        tab="work_arrangement",
        label="Roster Crew",
        lookup_endpoint=(
            "/api/administration/calendar/"
            "lookup/roster-crews/"
        ),
        display_key="roster_crew_name",
        depends_on=["company"],
        lookup_params={
            "company_id": "$company",
            "location_id": "$location",
        },
        # Memilih crew langsung mengisi Work Schedule dengan pola milik
        # crew itu. Tanpa ini pengguna harus menebak pola mana yang
        # cocok, dan tebakan yang salah baru ditolak saat Simpan.
        autofill={"work_schedule": "work_schedule"},
        table=False,
        filter=True,
        search=False,
        sortable=False,
        visible_when=WHEN_ROSTER_APPLICABLE,
        help_text=(
            "Gelombang rotasi pegawai site — ini yang menentukan pola "
            "kerjanya. Kosongkan untuk pegawai HO/kantor, lalu pilih "
            "Work Schedule sendiri."
        ),
        order=128,
    ),

    "work_schedule": field.lookup(
        tab="work_arrangement",
        label="Work Schedule",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/work-schedules/"
        ),
        display_key="work_schedule_name",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        help_text=(
            "Pegawai HO/kantor: pilih pola non-roster, mis. Regular 5 "
            "Days. Pegawai site: terisi sendiri dari Roster Crew dan "
            "harus sama dengan pola milik crew itu."
        ),
        order=130,
    ),

    "working_calendar": field.lookup(
        tab="work_arrangement",
        label="Working Calendar",
        lookup_endpoint=(
            "/api/administration/calendar/"
            "lookup/work-calendars/"
        ),
        depends_on=["company"],
        lookup_params={
            "company_id": "$company",
            "location_id": "$location",
        },
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=140,
    ),

    # Dua cermin di bawah bukan kolom model — salinan Feature
    # Applicability milik group yang dipilih, dipakai sebagai syarat
    # tampil. Tersembunyi karena yang menentukannya master Employee
    # Group; dua kenop untuk satu keputusan cuma membuat keduanya bisa
    # berbeda.
    "employee_group_shift_applicable": field.switch(
        tab="work_arrangement",
        label="Shift Applicable",
        hidden=True,
        read_only=True,
        display=True,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=1,
    ),

    "employee_group_roster_applicable": field.switch(
        tab="work_arrangement",
        label="Roster Applicable",
        hidden=True,
        read_only=True,
        display=True,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=2,
    ),

    "shift": field.lookup(
        tab="work_arrangement",
        label="Shift",
        lookup_endpoint=(
            "/api/administration/references/hr/"
            "lookup/shifts/"
        ),
        table=False,
        filter=True,
        search=False,
        sortable=False,
        visible_when=WHEN_SHIFT_APPLICABLE,
        order=150,
    ),

    "roster_start_override": field.date(
        tab="work_arrangement",
        label="Roster Start Override",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        help_text=(
            "Kosongkan untuk ikut tanggal mulai siklus milik crew. "
            "Isi hanya kalau swing pegawai ini digeser sendiri."
        ),
        order=154,
    ),

    "back_to_back_partner": field.lookup(
        tab="work_arrangement",
        label="Back-to-Back Partner",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="back_to_back_partner_name",
        depends_on=["company"],
        lookup_params={
            "company_id": "$company",
            "location_id": "$location",
        },
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        visible_when={"field": "roster_policy", "op": "is_not_null"},
        help_text=(
            "Pegawai yang masuk saat orang ini off. Opsional — tidak "
            "pernah menghalangi jadwal disetujui, cuma dipakai sebagai "
            "pembanding di layar jadwal."
        ),
        order=133,
    ),
    "travel_days_override": field.number(
        tab="work_arrangement",
        label="Travel Days Override",
        min=0,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        help_text=(
            "Hari perjalanan sekali jalan khusus pegawai ini. "
            "Kosongkan untuk ikut Roster Policy (site, Point of Hire)."
        ),
        order=156,
    ),

    "notice_period_days": field.number(
        tab="employment",
        label="Notice Period (Days)",
        min=0,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=160,
    ),

    "employment_notes": field.textarea(
        tab="employment",
        label="Employment Notes",
        rows=4,
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=170,
    ),
}


def employment_tab_fields(tab: str) -> list[str]:
    """
    Nama field milik satu kelompok.

    Diturunkan dari `tab=` pada definisi di atas, bukan didaftar ulang
    di `tabs.py`: dua daftar yang harus tetap sama adalah dua daftar
    yang cepat atau lambat berbeda, dan field yang hilang dari daftar
    tab **tidak muncul di form tanpa satu pun pesan**.
    """
    return [
        name
        for name, config in EMPLOYMENT_FIELDS.items()
        if config.get("tab") == tab
    ]