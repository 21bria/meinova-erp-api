from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)

    # Mata rantai yang selama ini hilang. `Role`, `RoleMenuPermission`,
    # dan tabel cakupan data semuanya sudah ada dan semuanya
    # mengandaikan role itu dipegang seseorang — tapi tidak ada satu
    # pun kolom yang menghubungkannya ke User, jadi seluruh RBAC-nya
    # menggantung. Engine approval jadi pemakai pertamanya: step yang
    # bukan garis komando (HR, bagian travel) ditunjuk lewat role,
    # bukan lewat atasan.
    # `through` menunjuk model yang kita tulis sendiri di atas tabel
    # `auth_users_roles` yang **sudah ada**. Bukan tabel kedua, dan
    # bukan pemindahan baris: bentuk tabel bikinan Django tadi sudah
    # tepat pada grain yang dibutuhkan (satu baris per user-role,
    # unik), jadi yang berubah hanya siapa yang mendeklarasikannya.
    #
    # Gunanya baru terasa di stage berikutnya: kewenangan per penugasan
    # butuh tempat menempel, dan keanggotaan yang dibuat otomatis tidak
    # punya tempat itu. Di stage ini **tidak ada satu kolom pun**
    # ditambahkan — `user.roles` berperilaku persis seperti sebelumnya.
    roles = models.ManyToManyField(
        "accounts.Role",
        blank=True,
        related_name="users",
        through="accounts.RoleAssignment",
    )

    # Bahasa antarmuka pilihan pemegang akun.
    #
    # **Preferensi tampilan, bukan data bisnis.** Tidak ada satu pun
    # perhitungan — payroll, cuti, roster, kehadiran — yang boleh
    # membacanya, dan tidak ada satu pun nama master yang diterjemahkan
    # karenanya. Yang berubah hanya kata-kata milik sistem di layar
    # orang itu.
    #
    # Bawaannya `"en"` supaya seluruh akun yang sudah ada tetap melihat
    # layar yang persis sama sesudah migration ini — perubahan bahasa
    # harus datang dari orangnya, bukan dari sebuah migration.
    #
    # Pilihannya diturunkan dari `settings.LANGUAGES`, jadi bahasa
    # ketiga nanti tidak butuh migration kedua untuk mengubah `choices`
    # — Django memang membuat migration untuk perubahan `choices`, tapi
    # migration itu tidak menyentuh satu baris data pun.
    language = models.CharField(
        max_length=10,
        choices=settings.LANGUAGES,
        default="en",
        help_text="Bahasa antarmuka. Tidak memengaruhi zona waktu maupun data bisnis.",
    )

    class Meta:
        db_table = "auth_users"

    def __str__(self):
        return self.username