"""
Kontrak baca Self Service.

**Whitelist eksplisit, bukan `EmployeeSerializer` yang di-masking.**
Serializer admin memuat ±120 field — termasuk `notes`, `organization_notes`,
`employment_notes`, `basic_salary`, dan pk akun — dan menyaringnya berarti
setiap field baru yang ditambahkan HR besok ikut terbuka di Self Service
sampai ada yang ingat menutupnya. Daftar putih gagal ke arah yang
sebaliknya: field baru tidak muncul sampai ada yang memutuskan ia boleh.

`allow_self=True` pada `EmployeeDataPolicy` **tidak** dibaca di sini.
Policy itu menjawab pertanyaan administratif ("siapa boleh melihat
kelompok data ini pada kartu pegawai"); yang employee-facing adalah
keputusan tersendiri. Lihat `docs/claude/self-service.md` → C2.
"""

from rest_framework import serializers


class SelfAvatarSerializer(serializers.Serializer):
    """
    Foto pegawai beserta fallback-nya.

    Bentuknya **selalu sama**, termasuk untuk yang belum punya foto:
    `url` boleh `null`, `initials` tidak pernah. Layar yang menerimanya
    karena itu tidak perlu menghitung inisial sendiri — dan perhitungan
    yang tidak diduplikasi adalah perhitungan yang tidak bisa berbeda
    antara sidebar dan halaman profil.
    """

    url = serializers.CharField(read_only=True, allow_null=True)
    source = serializers.CharField(read_only=True, allow_null=True)
    initials = serializers.CharField(read_only=True)


class SelfIdentitySerializer(serializers.Serializer):
    """
    Identitas seperlunya. Profil lengkap menyusul di Stage 4.

    `Serializer` biasa, bukan `ModelSerializer`: yang terakhir menurunkan
    field dari model, dan penurunan otomatis adalah persis mekanisme yang
    membuat kolom baru ikut terkirim tanpa ada yang memutuskannya.
    """

    id = serializers.IntegerField(read_only=True)
    employee_number = serializers.CharField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    avatar = serializers.SerializerMethodField()

    def get_avatar(self, employee) -> dict:
        """
        Urutannya dari `apps.hr.avatar`, alamatnya milik Self Service.

        `employee_photo()` yang memutuskan **foto yang mana** — urutan
        yang sama dengan kartu pegawai HR dan sidebar, dan itu memang
        tidak boleh berbeda. Yang berbeda alamatnya: di sini
        `/api/me/avatar/`, yang dijaga identitas.

        **Sengaja bukan `/api/uploads/<id>/preview/`.** Alamat itu hak
        bacanya diturunkan dari hak baca baris Employee-nya, jadi
        pegawai tanpa `hr.view_employee` akan menerima halaman yang
        terbuka dengan gambar yang 404 — persis jaminan Stage 2 yang
        bocor lewat pintu belakang.

        Alamatnya tetap dikirim meski isinya belum tentu ada? Tidak:
        `url` bernilai `null` kalau memang tidak ada foto, supaya layar
        tidak pernah memasang `<img>` yang sudah pasti gagal.
        """
        from apps.hr.avatar import employee_initials, employee_photo

        source, _obj = employee_photo(employee)

        url = None

        if source is not None:
            request = self.context.get("request")

            path = "/api/me/avatar/"

            url = request.build_absolute_uri(path) if request else path

        return SelfAvatarSerializer({
            "url": url,
            "source": source,
            "initials": employee_initials(employee),
        }).data
