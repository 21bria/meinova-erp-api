from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class Employee(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_profile",
    )

    # Keunikan dikondisikan ke is_deleted (lihat Meta.constraints).
    # Tanpa itu, nomor karyawan yang sudah di-soft-delete akan terus
    # terkunci dan tidak bisa dipakai ulang.
    employee_number = models.CharField(max_length=50)
    nik = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    passport_number = models.CharField(max_length=100,blank=True,default="")
    tax_number = models.CharField(max_length=50,blank=True,default="")

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    gender = models.ForeignKey(
        "administration.Gender",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    religion = models.ForeignKey(
        "administration.Religion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    nationality = models.ForeignKey(
        "administration.Nationality",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    blood_type = models.ForeignKey(
        "administration.BloodType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    marital_status = models.ForeignKey(
        "administration.MaritalStatus",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    birth_place = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    birth_date = models.DateField(null=True,blank=True)

    # ------------------------------------------------------------------
    # Alamat
    #
    # Dua bagian yang sengaja dipisah. `address` memuat detail yang tidak
    # punya master dan tidak akan pernah punya — nama jalan, nomor,
    # RT/RW; empat FK di bawahnya menunjuk master Geography yang sudah
    # ada (Province -> Kabupaten/Kota -> Kecamatan -> Kelurahan/Desa).
    #
    # Menyimpan seluruh alamat sebagai satu teks membuatnya tidak bisa
    # dikelompokkan maupun disaring — "berapa pegawai di Kabupaten Halmahera
    # Tengah" tidak bisa dijawab dari kolom teks. Sebaliknya, menjadikan
    # detailnya master berarti setiap nama jalan di Indonesia harus
    # dibuatkan barisnya lebih dulu.
    #
    # Semuanya nullable, dan itu disengaja: alamat lazim terisi bertahap,
    # dan pegawai tidak boleh gagal disimpan gara-gara kelurahannya belum
    # diketahui. Yang dijaga `clean()` cuma konsistensi rantainya.
    # ------------------------------------------------------------------
    address = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Alamat detail: nama jalan, nomor, RT/RW. Wilayah "
            "administratifnya diisi di field Province sampai "
            "Kelurahan/Desa."
        ),
    )

    province = models.ForeignKey(
        "administration.Province",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    city = models.ForeignKey(
        "administration.City",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="Kabupaten/Kota",
    )

    district = models.ForeignKey(
        "administration.District",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="Kecamatan",
    )

    village = models.ForeignKey(
        "administration.Village",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="Kelurahan/Desa",
    )

    personal_email = models.EmailField(
        blank=True,
        default="",
    )

    work_email = models.EmailField(
        blank=True,
        default="",
    )

    phone = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    mobile = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )
    emergency_contact_phone = models.CharField(max_length=50,blank=True,default="")
    emergency_contact_name = models.CharField(max_length=150,blank=True, default="")
    # ------------------------------------------------------------------
    # Foto pegawai
    #
    # Dua kolom untuk satu foto, dan itu keadaan peralihan yang
    # disengaja — bukan kelalaian.
    #
    # `avatar_file` yang berlaku sekarang: berkasnya duduk di
    # `uploads.UploadedFile`, jadi ia ikut mendapat seluruh yang sudah
    # dipunyai kerangka unggahan — folder per tenant dan per kategori,
    # thumbnail, soft delete, dan yang terpenting **penyajian
    # berautentikasi** lewat `preview/`. `avatar` yang lama sebuah
    # `ImageField` yang dilayani `MEDIA_URL` statis: siapa pun yang
    # menebak jalurnya bisa membukanya, tanpa login.
    #
    # Yang lama **tidak dihapus dan tidak dimigrasikan paksa**. Ia
    # tinggal sebagai jalur baca kompatibilitas untuk tenant yang
    # kolomnya sudah terisi; urutan bacanya dipegang satu tempat,
    # `apps.hr.avatar.resolve_employee_avatar()`, supaya Self Service,
    # kartu pegawai HR, dan avatar di sidebar tidak masing-masing
    # menyusun urutan yang berbeda.
    # ------------------------------------------------------------------

    avatar_file = models.ForeignKey(
        "uploads.UploadedFile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=(
            "Foto pegawai. Diunggah lewat kerangka unggahan dengan "
            "kategori Avatar."
        ),
    )

    avatar = models.ImageField(
        upload_to="employees/avatars/",
        null=True,
        blank=True,
        help_text=(
            "Kolom foto lama. Hanya dibaca untuk kompatibilitas; foto "
            "baru masuk lewat Avatar File."
        ),
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    is_active = models.BooleanField( default=True)

    class Meta:
        db_table = "hr_employee"
        ordering = ["first_name", "last_name"]
        indexes = [
            models.Index(
                fields=["employee_number"],
                name="idx_hr_employee_number",
            ),
            models.Index(
                fields=["nik"],
                name="idx_hr_employee_nik",
            ),
            models.Index(
                fields=["first_name", "last_name"],
                name="idx_hr_employee_name",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["employee_number"],
                condition=Q(is_deleted=False),
                name="uniq_active_employee_number",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee_number} - {self.full_name}"

    def clean(self):
        """
        Rantai wilayah alamat harus konsisten dengan induknya.

        Lapisan ketiga, dan satu-satunya yang berlaku untuk pemanggil API
        langsung. Form sudah menyaring dropdown-nya lewat `lookup_params`
        dan mengosongkan anaknya lewat `depends_on`, tapi keduanya bisa
        dilewati — dan alamat yang kecamatannya milik kabupaten lain tidak
        berbunyi sampai ada yang mencetak surat keterangan domisili.
        Pola yang sama dengan `OrganizationAssignment.clean()`.

        Diperiksa lewat **FK induknya** (`city.province_id`), bukan lewat
        nama: nama wilayah berulang di seluruh Indonesia, dan pencocokan
        nama tetap menghasilkan jawaban yang terlihat masuk akal — itu
        yang membuatnya berbahaya.
        """
        super().clean()

        errors: dict[str, str] = {}

        # Anak yang menempel ke induk yang salah.
        if self.province_id and self.city_id:
            if self.city.province_id != self.province_id:
                errors["city"] = (
                    f"{self.city.name} bukan bagian dari Province "
                    f"{self.province.name}."
                )

        if self.city_id and self.district_id:
            if self.district.city_id != self.city_id:
                errors["district"] = (
                    f"{self.district.name} bukan bagian dari "
                    f"Kabupaten/Kota {self.city.name}."
                )

        if self.district_id and self.village_id:
            if self.village.district_id != self.district_id:
                errors["village"] = (
                    f"{self.village.name} bukan bagian dari Kecamatan "
                    f"{self.district.name}."
                )

        # Anak tanpa induk. Yang ditolak bukan alamat yang belum lengkap
        # — kelurahan yang mengambang tanpa kecamatan yang menaunginya
        # tidak bisa ditelusuri ke wilayah mana pun, dan justru itu satu
        # kolom yang gunanya menelusuri wilayah.
        if self.city_id and not self.province_id:
            errors["province"] = (
                "Province wajib diisi kalau Kabupaten/Kota dipilih."
            )

        if self.district_id and not self.city_id:
            errors["city"] = (
                "Kabupaten/Kota wajib diisi kalau Kecamatan dipilih."
            )

        if self.village_id and not self.district_id:
            errors["district"] = (
                "Kecamatan wajib diisi kalau Kelurahan/Desa dipilih."
            )

        # Foto yang bukan foto.
        #
        # Kolomnya FK ke `UploadedFile` yang memuat **seluruh** jenis
        # berkas tenant — kontrak PDF, berkas import, lampiran dokumen.
        # Tanpa pemeriksaan ini, satu pk yang salah ketik membuat kartu
        # pegawai menunjuk scan kontrak orang lain, dan kesalahannya
        # baru berbunyi saat ada yang membuka halamannya: gambar rusak,
        # tanpa satu pun petunjuk ke sebabnya.
        #
        # Diperiksa **dua** hal, bukan satu. Kategori menjaga berkasnya
        # mendarat di folder yang benar dan ikut aturan penyajian
        # avatar; jenis berkas menjaga isinya memang gambar — kategori
        # sendirian masih meloloskan PDF yang diunggah sebagai avatar.
        if self.avatar_file_id:
            from apps.uploads.models import UploadedFile

            uploaded = self.avatar_file

            if uploaded.category != UploadedFile.Category.AVATAR:
                errors["avatar_file"] = (
                    "Berkas foto harus diunggah dengan kategori Avatar."
                )

            elif uploaded.file_type != UploadedFile.FileType.IMAGE:
                errors["avatar_file"] = (
                    "Berkas foto harus berupa gambar."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def full_name(self) -> str:
        parts = [
            self.first_name,
            self.last_name,
        ]

        return " ".join(
            part.strip()
            for part in parts
            if part and part.strip()
        )

    @property
    def display_name(self) -> str:
        return self.full_name