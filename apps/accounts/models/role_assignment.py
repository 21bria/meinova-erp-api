from django.db import models

from apps.accounts.models.authority_types import AuthorityResourceType
from apps.accounts.models.role import DataScopeLevel


class AuthorityMode(models.TextChoices):
    """
    Dari mana kewenangan **satu penugasan** dihitung.

    Sengaja **bukan** salinan enum cakupan lama yang digantikannya, dan
    bedanya bukan gaya:

    * `PLACEMENT` menggantikan `own`. Kata "own" sudah dipakai
      `AuthorityResourceType.OWN` untuk arti yang sama sekali
      lain — "baris yang `user_id`-nya saya", data diri sendiri. Satu
      kata untuk dua gagasan berbeda adalah cara paling murah membuat
      orang salah membaca aturan keamanan, jadi yang ini diberi nama
      yang menyebut maksudnya: kewenangannya **ikut penempatan**
      pemegangnya.
    * `UNRESTRICTED` menggantikan `all` — namanya menyebut akibatnya,
      bukan cakupannya.
    * `EXPLICIT` **berubah arti**, dan ini yang paling penting. Pada
      `Role`, `explicit` tanpa satu pun baris berarti **tanpa
      batasan** — dua keadaan yang berlawanan dinyatakan sama. Di sini
      `EXPLICIT` tanpa baris berarti **tanpa kewenangan**. Baris yang
      hilang tidak boleh berarti akses se-tenant.

    Perbedaan terakhir **sudah berlaku**: `DataScopeService` membaca
    kewenangan penugasan ini dan tidak membaca konfigurasi `Role` sama
    sekali. `authority_mode` kosong pun berarti tertutup — bukan "ikut
    Role" seperti selama transisi.
    """

    UNRESTRICTED = "unrestricted", "Tanpa Batas"
    PLACEMENT = "placement", "Ikut Penempatan Pemegang"
    EXPLICIT = "explicit", "Ditentukan Sendiri"


class RoleAssignment(models.Model):
    """
    Satu baris = satu orang memegang satu role.

    Tabelnya **bukan tabel baru**. `auth_users_roles` sudah dibuat
    Django saat `User.roles` masih M2M implisit, dan bentuknya sudah
    persis yang dibutuhkan: satu baris per (user, role), unik. Yang
    berubah cuma status modelnya — dari dibuat otomatis jadi ditulis
    sendiri — supaya **nanti** ada tempat menempelkan kewenangan per
    penugasan (Stage 4C). Nol baris dipindahkan, nol kolom ditambahkan.

    Kenapa `models.Model`, bukan `BaseModel` seperti hampir semua model
    lain di repo ini: tabel yang sudah ada punya **tiga kolom**, dan
    `BaseModel` akan menuntut `is_deleted`, `created_by`, dan
    seterusnya — kolom yang tidak ada di sana. Menambahkannya bukan
    lagi perubahan status; itu perubahan skema, dan stage ini memang
    tidak boleh melakukannya.

    Soft delete juga **salah** untuk baris ini, bukan cuma mahal.
    Keanggotaan yang dicabut harus benar-benar hilang: `UNIQUE(user,
    role)` tidak mengenal `is_deleted`, jadi baris tercabut yang
    tertinggal akan menolak orang yang sama diberi role yang sama lagi.
    Riwayat pencabutan role, kalau suatu saat dibutuhkan, tempatnya
    audit log — bukan tabel keanggotaan yang dibaca setiap request.

    `unique_together` dipakai — bukan `UniqueConstraint` yang lebih
    baru — karena persis itu yang dipakai through model bikinan Django.
    Menyamainya membuat migration status-saja benar-benar berstatus
    saja: nama constraint yang dihasilkan sama dengan yang sudah ada di
    database, jadi `makemigrations --check` tidak melihat selisih apa
    pun.
    """

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )

    role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )

    # ------------------------------------------------------------------
    # Kewenangan per penugasan (Stage 4C — disimpan, belum dibaca)
    # ------------------------------------------------------------------

    authority_mode = models.CharField(
        max_length=20,
        choices=AuthorityMode.choices,
        blank=True,
        default="",
        help_text=(
            "Dari mana kewenangan penugasan ini dihitung. Kosong "
            "berarti belum ditentukan — yang berlaku konfigurasi "
            "cakupan milik Role-nya."
        ),
    )

    # **Kosong adalah keadaan yang sah, dan disengaja.**
    #
    # Kosong berarti "belum ditentukan; ikut Role" — bukan "tanpa
    # kewenangan". Itu yang membuat stage ini tidak mengubah apa pun:
    # penugasan yang dibuat lewat jalur yang belum tahu soal kewenangan
    # (seed, `.add()`, `.set()`) tetap berperilaku persis seperti
    # sebelumnya, dan Stage 4D bisa membaca keduanya berdampingan
    # sebelum yang lama dicabut.
    #
    # Yang **tidak** boleh: menjadikan kosong sama dengan `EXPLICIT`
    # tanpa baris. Yang satu berarti "belum diatur", yang satu lagi
    # "memang tidak boleh apa-apa", dan menyamakannya akan mengunci
    # orang dari pekerjaannya tanpa satu pun pesan.

    authority_level = models.CharField(
        max_length=20,
        choices=DataScopeLevel.choices,
        blank=True,
        default="",
        help_text=(
            "Tingkat organisasi untuk mode 'Ikut Penempatan Pemegang'."
        ),
    )

    class Meta:
        db_table = "auth_users_roles"
        unique_together = (("user", "role"),)

    def __str__(self):
        return f"{self.user} - {self.role}"


class RoleAssignmentAuthority(models.Model):
    """
    Satu nilai kewenangan untuk **satu penugasan** — bukan untuk role.

    Inilah yang tidak bisa dinyatakan sebelum Stage 4B. Cakupan lama
    per-role menempel pada Role, jadi "Hesti mengurus JKT-HO, Eko
    mengurus SAGEA-MINE, keduanya HR-ADMIN" memaksa dua role. Cakupan
    lama per-orang menempel pada User tanpa kolom role, jadi satu
    barisnya melebarkan **setiap** izin yang dipegang orang itu. Yang di sini menempel pada
    pasangan (orang, role) — persis grain pertanyaannya.

    `resource_type` memakai `AuthorityResourceType` — nilai yang sama
    persis dengan yang dulu dipinjam dari model cakupan lama,
    **termasuk `own`**, supaya backfill bisa menyalin baris lama apa
    adanya tanpa menafsirkannya. `own` di sini tetap berarti "data diri
    sendiri" — tidak ada hubungannya dengan `AuthorityMode.PLACEMENT`.

    Sejak Stage 4J enum-nya **tidak lagi dipinjam dari model yang
    digantikannya**: model pengganti yang runtuh saat pendahulunya
    dihapus bukan pengganti. Lihat `apps.accounts.models.authority_types`.
    """

    assignment = models.ForeignKey(
        "accounts.RoleAssignment",
        on_delete=models.CASCADE,
        related_name="authorities",
    )

    resource_type = models.CharField(
        max_length=50,
        choices=AuthorityResourceType.choices,
    )

    resource_id = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "accounts_role_assignment_authority"
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "resource_type", "resource_id"],
                name="uniq_role_assignment_authority",
            ),
        ]
        ordering = ["assignment", "resource_type", "resource_id"]

    def __str__(self):
        return (
            f"{self.assignment} - {self.resource_type} - "
            f"{self.resource_id or 'ALL'}"
        )
