"""
Kontrak `GET /api/me/profile/` — profil pegawai yang sedang login.

**Daftar putih eksplisit.** Tidak satu field pun di berkas ini lahir dari
introspeksi model. Itu bukan kerapian melainkan arah kegagalannya: kolom
baru yang ditambahkan HR besok **tidak** muncul di sini sampai ada yang
memutuskan ia boleh. Kebalikannya — menyerialkan semuanya lalu membuang
sebagian — gagal ke arah yang salah, dan yang terlewat tidak berbunyi di
mana pun.

Kenapa bukan `EmployeeSerializer` yang disaring
-----------------------------------------------
Serializer itu mengirim **124 kunci** hari ini, termasuk `notes`,
`basic_salary`, `bpjs_*`, `tax_number`, dan pk akun. Ia melayani layar
administratif dan memang harus selengkap itu. Menjadikannya dasar kontrak
employee-facing berarti setiap perubahan pada layar HR ikut mengubah apa
yang dilihat pegawai tentang dirinya — dua hal yang tidak punya alasan
bergerak bersama.

`SUBJECT_EMPLOYEE_FIELDS` / `EmployeeDataPolicy` juga **bukan** batas
utama di sini. Keduanya menjawab pertanyaan administratif ("siapa boleh
melihat kelompok data ini pada kartu pegawai"), dan bawaannya **terbuka**
— kelompok tanpa baris policy terlihat oleh semua orang. Batas yang
bawaannya tertutup adalah daftar putih ini.

Bentuknya berseksi, bukan datar
-------------------------------
Layar profil menampilkan kelompok, bukan 40 baris berurutan. Seksi
membuat frontend tidak perlu tahu field mana milik kelompok mana — dan
itulah satu-satunya cara kontrak ini tetap berdiri saat HR memindahkan
sebuah kolom antar tab di schema-nya sendiri.
"""

from rest_framework import serializers


class ReferenceSerializer(serializers.Serializer):
    """
    Master yang ditunjuk, dalam bentuk sekecil yang berguna.

    `{id, code, name}` — bukan serializer penuh milik domainnya. Layar
    profil menampilkan namanya; `id` untuk penautan nanti, `code` karena
    itu yang dipakai orang menyebut unitnya ("SITE", "JKT-HO"). Apa pun
    di luar tiga itu adalah data master yang kebetulan ikut terbawa.
    """

    id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


def reference(obj) -> dict | None:
    """Master jadi `{id, code, name}`, atau `None` kalau tidak diisi."""
    if obj is None:
        return None

    return {
        "id": obj.pk,
        "code": getattr(obj, "code", "") or "",
        "name": getattr(obj, "name", "") or "",
    }


def person(employee) -> dict | None:
    """
    Pegawai lain yang disebut di profil ini — hari ini hanya atasannya.

    Sengaja **tidak** memakai `reference()`: pegawai tidak punya `code`,
    dan yang dicari orang saat melihat atasannya adalah nama beserta
    nomor pegawainya, bukan kode master.
    """
    if employee is None:
        return None

    return {
        "id": employee.pk,
        "employee_number": employee.employee_number,
        "full_name": employee.full_name,
    }


class SelfProfileSerializer(serializers.Serializer):
    """
    Profil employee-facing, berseksi.

    Seluruh seksi **selalu ada**, termasuk untuk pegawai yang penempatan
    atau kepegawaiannya belum diisi: nilainya `null` per field, bukan
    seksinya yang hilang. Layar yang menerimanya karena itu tidak perlu
    membedakan "belum diisi" dari "seksinya tidak dikirim" — yang kedua
    terbaca seperti kegagalan memuat.
    """

    identity = serializers.SerializerMethodField()
    photo = serializers.SerializerMethodField()
    personal = serializers.SerializerMethodField()
    contact = serializers.SerializerMethodField()
    employment = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    emergency_contact = serializers.SerializerMethodField()

    # ------------------------------------------------------------------
    # Seksi
    # ------------------------------------------------------------------

    def get_identity(self, employee) -> dict:
        return {
            "id": employee.pk,
            "employee_number": employee.employee_number,
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "full_name": employee.full_name,
            "is_active": employee.is_active,
        }

    def get_photo(self, employee) -> dict:
        """
        Kontrak foto Stage 3, alamat Self Service.

        Menunjuk `/api/me/avatar/` — **bukan** `/api/uploads/.../preview/`
        dan bukan jalur penyimpanan. Yang terakhir dilayani tanpa
        pemeriksaan siapa pun; yang pertama menuntut `hr.view_employee`,
        yang justru dilepas di Stage 2. Lihat `apps/self_service/api/avatar.py`.
        """
        from apps.hr.avatar import employee_initials, employee_photo

        source, _obj = employee_photo(employee)

        url = None

        if source is not None:
            request = self.context.get("request")

            path = "/api/me/avatar/"

            url = request.build_absolute_uri(path) if request else path

        return {
            "url": url,
            "source": source,
            "initials": employee_initials(employee),
        }

    def get_personal(self, employee) -> dict:
        """
        Data diri yang wajar dilihat pemiliknya.

        **Nomor identitas pemerintah sengaja tidak ada di sini** —
        `nik`, `passport_number`, `tax_number`. Bukan karena pegawai
        tidak berhak tahu nomornya sendiri, melainkan karena layar profil
        dibuka di tempat terbuka dan sering terlihat orang yang kebetulan
        lewat. Kalau nanti memang dibutuhkan, ia layak jadi tindakan
        tersendiri yang disadari — bukan sesuatu yang tercetak begitu
        halaman dimuat.
        """
        return {
            "gender": reference(employee.gender),
            "birth_place": employee.birth_place,
            "birth_date": employee.birth_date,
            "marital_status": reference(employee.marital_status),
            "nationality": reference(employee.nationality),
            "blood_type": reference(employee.blood_type),
            "religion": reference(employee.religion),
        }

    def get_contact(self, employee) -> dict:
        return {
            "personal_email": employee.personal_email,
            "work_email": employee.work_email,
            "phone": employee.phone,
            "mobile": employee.mobile,
            "address": employee.address,
            "province": reference(employee.province),
            "city": reference(employee.city),
            "district": reference(employee.district),
            "village": reference(employee.village),
        }

    def get_employment(self, employee) -> dict:
        """
        Ringkasan kepegawaian yang berlaku sekarang.

        **Syarat kontrak tidak ada di sini** — `contract_start/end`,
        `probation_*`, `notice_period_days`. Bukan karena internal,
        melainkan karena belum diputuskan: tanggal berakhirnya kontrak
        adalah informasi yang berat, dan menampilkannya diam-diam di
        halaman profil bukan cara yang benar untuk memberitahukannya.
        Menunggu keputusan, bukan dihilangkan selamanya.

        Roster, shift, dan kalender kerja juga tidak ada: itu jadwal,
        milik kontrak "Attendance & Leave" yang belum dibuat.
        """
        employment = getattr(employee, "employment", None)

        if employment is None:
            return {
                "status": None,
                "type": None,
                "join_date": None,
                "effective_date": None,
                "confirmation_date": None,
                "job_location": "",
            }

        return {
            "status": reference(employment.employment_status),
            "type": reference(employment.employment_type),
            "join_date": employment.join_date,
            "effective_date": employment.employment_effective_date,
            "confirmation_date": employment.confirmation_date,
            "job_location": employment.job_location,
        }

    def get_organization(self, employee) -> dict:
        organization = getattr(employee, "organization", None)

        if organization is None:
            return {
                "company": None,
                "branch": None,
                "location": None,
                "division": None,
                "department": None,
                "section": None,
                "position": None,
                "job_level": None,
                "job_grade": None,
                "cost_center": None,
                "supervisor": None,
                "effective_date": None,
            }

        return {
            "company": reference(organization.company),
            "branch": reference(organization.branch),
            "location": reference(organization.location),
            "division": reference(organization.division),
            "department": reference(organization.department),
            "section": reference(organization.section),
            "position": reference(organization.position),
            "job_level": reference(organization.job_level),
            "job_grade": reference(organization.job_grade),
            "cost_center": reference(organization.cost_center),
            "supervisor": person(organization.reports_to),
            "effective_date": organization.organization_effective_date,
        }

    def get_emergency_contact(self, employee) -> dict:
        return {
            "name": employee.emergency_contact_name,
            "phone": employee.emergency_contact_phone,
        }
