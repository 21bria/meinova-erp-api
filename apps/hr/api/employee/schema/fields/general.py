from apps.framework.builders import field


# Kode ISO-2 negara yang pembagian administratifnya dipakai blok alamat.
#
# Dipakai sebagai syarat tampil, dan sekaligus alasan blok itu tidak
# muncul untuk warga negara lain: master Geography di sistem ini berisi
# Province/Kabupaten/Kecamatan/Kelurahan **Indonesia** (34 provinsi,
# 514 kabupaten, 7.277 kecamatan, 83.762 kelurahan hasil import
# Kemendagri). Menawarkan dropdown itu untuk pegawai Singapura
# menghasilkan daftar yang tidak ada isinya — dan dropdown yang bisa
# dibuka tapi selalu kosong lebih buruk daripada tidak ada, karena
# pemakainya menyangka datanya yang belum terisi.
#
# Diperiksa terhadap **kode**, bukan nama. `Nationality.code` dan
# `Country.code` dua-duanya diseed ISO-2 dan dua-duanya berconstraint
# unik, sementara namanya ditulis berbeda-beda ("Indonesian",
# "Indonesia", "WNI"). Ini satu-satunya tempat nilainya ditulis; kalau
# sebuah tenant menamai kodenya lain, yang diubah baris ini.
INDONESIA_CODE = "ID"


# Syarat tampil blok alamat wilayah. Dibaca dari nilai form
# `nationality_code`, yang diisi dua jalur: serializer saat form dimuat,
# dan `autofill` pada Nationality begitu kewarganegaraannya diganti.
# Kalau cuma salah satu, bloknya benar saat form dibuka lalu salah
# setelah diubah — atau sebaliknya.
WHEN_INDONESIAN = {
    "field": "nationality_code",
    "op": "eq",
    "value": INDONESIA_CODE,
}


"""
Employee General Field Schema

Catatan:
- `tab="general"` menentukan field tampil pada tab General.
- `table=True` menentukan field tampil pada tabel utama.
- `filter=True` menentukan field tersedia sebagai filter.
- `search=True` menentukan field ikut pencarian global.
- `sortable=True` menentukan field dapat diurutkan.
- `placement="quick"` menempatkan field pada quick filter.
- `overview=True` menampilkan field pada kartu Overview.
- `overview_order` menentukan urutan field pada Overview.
- `overview_format` menentukan format tampilan khusus, misalnya boolean.
- `order` menentukan urutan field pada form.

Overview sengaja hanya menampilkan informasi ringkas agar tidak terlalu penuh:
Employee Number, First Name, Last Name, Work Email, Mobile, dan Active.
"""


GENERAL_FIELDS = {
    "user": field.lookup(
        tab="general",
        label="User Account",
        lookup_endpoint="/api/accounts/lookup/users/",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=10,
    ),

    # Dibuat otomatis oleh backend saat Auto Generate menyala, jadi
    # tidak lagi wajib diketik. Kewajibannya ditegakkan serializer:
    # salah satu dari dua ini harus terisi.
    "auto_generate_employee_number": field.switch(
        tab="general",
        label="Auto Generate Employee Number",
        default=True,
        modes=["create"],
        help_text=(
            "Nomor dibuat dari kode Company + tahun + urutan "
            "(mis. KW260001). Matikan kalau nomornya mau diketik "
            "sendiri. Hanya berlaku saat pegawai dibuat."
        ),
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=15,
    ),

    "employee_number": field.text(
        tab="general",
        label="Employee Number",
        placeholder="Terisi otomatis dari kode Company",
        required=False,
        # **Tidak pernah disembunyikan.** Sempat begitu, dan hasilnya
        # kolom yang paling dicari orang di form pegawai baru tidak ada
        # di layar sama sekali — termasuk di form edit, karena penanda
        # auto itu write-only dan tidak pernah dikirim balik API.
        #
        # Yang berubah cuma boleh-tidaknya diketik: selama Auto menyala
        # kolomnya terisi nomor yang akan terbit dan dikunci, karena
        # apa pun yang diketik di situ diabaikan server.
        readonly_when={
            "field": "auto_generate_employee_number",
            "op": "is_true",
        },
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        overview_order=10,
        order=20,
    ),

    "nik": field.text(
        tab="general",
        label="NIK",
        placeholder="National identity number",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=30,
    ),

    "passport_number": field.text(
        tab="general",
        label="Passport Number",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=40,
    ),

    "tax_number": field.text(
        tab="general",
        label="NPWP",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=50,
    ),

    "first_name": field.text(
        tab="general",
        label="First Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        overview_order=20,
        order=60,
    ),

    "last_name": field.text(
        tab="general",
        label="Last Name",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        overview_order=30,
        order=80,
    ),

    "gender": field.lookup(
        tab="general",
        label="Gender",
        lookup_endpoint="/api/administration/references/hr/lookup/genders/",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=100,
    ),

    "religion": field.lookup(
        tab="general",
        label="Religion",
        lookup_endpoint="/api/administration/references/hr/lookup/religions/",
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=110,
    ),

    "nationality": field.lookup(
        tab="general",
        label="Nationality",
        lookup_endpoint="/api/administration/references/hr/lookup/nationalities/",
        # Menyalin `code` milik kewarganegaraan yang dipilih ke field
        # tersembunyi di bawah, yang jadi syarat tampil blok alamat
        # wilayah. `NationalityLookup.serialize()` yang mengirim kuncinya
        # — kalau dicabut dari sana, blok wilayahnya berhenti muncul saat
        # kewarganegaraannya diganti dan tidak ada error apa pun.
        autofill={
            "nationality_code": "code",
        },
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=120,
    ),

    # Bukan kolom model — cermin dari master, dipakai sebagai syarat
    # tampil blok alamat wilayah. Tersembunyi: yang menentukannya
    # Nationality di atas, dan dua kenop untuk satu keputusan cuma bikin
    # keduanya bisa berbeda.
    "nationality_code": field.text(
        tab="general",
        label="Nationality Code",
        hidden=True,
        read_only=True,
        # Tanpa `display=True`, generator FE membuang field ber-read_only
        # dari `form.ts` dan syarat tampilnya tidak punya nilai untuk
        # dibaca — bloknya hilang tanpa satu pun pesan.
        display=True,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=121,
    ),

    "blood_type": field.lookup(
        tab="general",
        label="Blood Type",
        lookup_endpoint="/api/administration/references/hr/lookup/blood-types/",
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=130,
    ),

    "marital_status": field.lookup(
        tab="general",
        label="Marital Status",
        lookup_endpoint="/api/administration/references/hr/lookup/marital-statuses/",
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=140,
    ),

    "birth_place": field.text(
        tab="general",
        label="Birth Place",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=150,
    ),

    "birth_date": field.date(
        tab="general",
        label="Birth Date",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=160,
    ),

    # ------------------------------------------------------------------
    # Alamat
    #
    # Empat dropdown berantai plus satu kotak teks, dan pembagiannya
    # bukan kosmetik: yang punya master wilayah dipilih dari master
    # (bisa disaring dan dikelompokkan), yang tidak akan pernah punya
    # master diketik bebas.
    #
    # Rantainya: Nationality -> Province -> Kabupaten/Kota -> Kecamatan
    # -> Kelurahan/Desa. Dua kenop yang harus ada **bersamaan** di tiap
    # anak, dan yang lupa salah satunya gagal tanpa suara:
    #
    #   `lookup_params` menyaring isi dropdown-nya ke induk terpilih.
    #   Tanpa itu, memilih satu kelurahan berarti mencari di 83.762 baris.
    #
    #   `depends_on` yang menonaktifkan sampai induknya diisi **dan**
    #   mengosongkannya saat induknya berubah. Field yang dipakai di
    #   `lookup_params` tapi tidak disebut di `depends_on` akan tetap
    #   menempel setelah induknya diganti, dan penolakannya baru muncul
    #   saat Simpan.
    #
    # Pengosongannya berantai lewat rantai `depends_on` itu sendiri:
    # ganti Nationality -> Province kosong -> Kabupaten/Kota kosong ->
    # Kecamatan kosong -> Kelurahan/Desa kosong. Karena itu tiap anak
    # cukup menyebut **induk terdekatnya**, bukan seluruh leluhurnya.
    #
    # Penyaringannya lewat id induk (`province_id`, `city_id`,
    # `district_id`) — FK yang sudah ada di master Geography, **bukan**
    # kecocokan nama. Nama wilayah berulang di seluruh Indonesia dan
    # ejaannya berbeda antar sumber; pencocokan nama tetap menghasilkan
    # baris yang terlihat masuk akal, dan itu yang membuatnya berbahaya.
    # ------------------------------------------------------------------
    "province": field.lookup(
        tab="general",
        label="Province",
        lookup_endpoint=(
            "/api/administration/references/geography/lookup/provinces/"
        ),
        # Disaring ke negara milik kewarganegaraannya lewat kode ISO yang
        # dikirim `NationalityLookup`. Gerbangnya `visible_when` di bawah,
        # jadi keduanya memakai nilai yang sama persis — kalau kodenya
        # tidak cocok, bloknya tersembunyi dan tidak pernah ada dropdown
        # kosong yang perlu ditafsirkan siapa pun.
        lookup_params={
            "country__code": "$nationality_code",
        },
        depends_on=["nationality"],
        visible_when=WHEN_INDONESIAN,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=162,
    ),

    "city": field.lookup(
        tab="general",
        label="Kabupaten/Kota",
        lookup_endpoint=(
            "/api/administration/references/geography/lookup/cities/"
        ),
        lookup_params={
            "province_id": "$province",
        },
        depends_on=["province"],
        visible_when=WHEN_INDONESIAN,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=163,
    ),

    "district": field.lookup(
        tab="general",
        label="Kecamatan",
        lookup_endpoint=(
            "/api/administration/references/geography/lookup/districts/"
        ),
        lookup_params={
            "city_id": "$city",
        },
        depends_on=["city"],
        visible_when=WHEN_INDONESIAN,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=164,
    ),

    "village": field.lookup(
        tab="general",
        label="Kelurahan/Desa",
        lookup_endpoint=(
            "/api/administration/references/geography/lookup/villages/"
        ),
        lookup_params={
            "district_id": "$district",
        },
        depends_on=["district"],
        visible_when=WHEN_INDONESIAN,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=165,
    ),

    # Detail yang tidak punya master dan tidak akan pernah punya.
    # `layout="full"` karena alamat lazimnya dua-tiga baris dan tidak
    # muat di setengah kolom.
    #
    # **Tanpa syarat tampil.** Pegawai asing juga punya alamat — yang
    # tidak berlaku untuknya cuma pembagian administratif Indonesia di
    # atas, dan menyembunyikan kotak alamatnya sekalian berarti alamat
    # mereka tidak bisa dicatat di mana pun.
    "address": field.textarea(
        tab="general",
        label="Address",
        placeholder="Nama jalan, nomor, RT/RW...",
        rows=3,
        layout="full",
        help_text=(
            "Alamat detail saja. Province sampai Kelurahan/Desa "
            "diisi di dropdown terpisah."
        ),
        table=False,
        filter=False,
        # Sengaja di luar pencarian global. `search=True` di sini hanya
        # mendeklarasikannya; yang benar-benar mencari adalah
        # `EmployeeViewSet.search_fields`, dan menyalakan salah satunya
        # saja menghasilkan penyaring yang diterima lalu diabaikan
        # diam-diam.
        search=False,
        sortable=False,
        order=166,
    ),

    "personal_email": field.email(
        tab="general",
        label="Personal Email",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=170,
    ),

    "work_email": field.email(
        tab="general",
        label="Work Email",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        overview_order=40,
        order=180,
    ),

    "phone": field.text(
        tab="general",
        label="Phone",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=190,
    ),

    "mobile": field.text(
        tab="general",
        label="Mobile",
        table=True,
        filter=False,
        search=True,
        sortable=False,
        overview=True,
        overview_order=50,
        order=200,
    ),

    "emergency_contact_name": field.text(
        tab="general",
        label="Emergency Contact Name",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=210,
    ),

    "emergency_contact_phone": field.text(
        tab="general",
        label="Emergency Contact Phone",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=220,
    ),

    # Foto yang berlaku. `category="avatar"` bukan hiasan: nilainya
    # ikut terkirim saat unggah, dan `Employee.clean()` menolak berkas
    # yang kategorinya lain — jadi kalau keduanya tidak sepakat, form
    # ini yang gagal menyimpan, bukan data yang diam-diam salah folder.
    "avatar_file": field.image(
        tab="general",
        label="Photo",
        accept="image/*",
        category="avatar",
        max_size_mb=5,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=230,
    ),

    # Kolom lama. Dibiarkan **terlihat tapi tidak bisa disunting**:
    # menghapusnya dari schema membuat tenant yang kolomnya masih
    # terisi kehilangan satu-satunya cara melihat foto apa yang
    # tersimpan di sana, sementara membiarkannya bisa ditulis berarti
    # foto baru masih bisa mendarat di jalur yang tidak berautentikasi.
    "avatar": field.image(
        tab="general",
        label="Photo (legacy)",
        accept="image/*",
        read_only=True,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=231,
    ),

    "notes": field.textarea(
        tab="general",
        label="Notes",
        placeholder="Write employee notes...",
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=240,
    ),

    "is_active": field.boolean(
        tab="general",
        label="Active",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        overview=True,
        overview_format="boolean",
        overview_order=60,
        order=999,
    ),
}