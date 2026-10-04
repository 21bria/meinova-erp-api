from django.db import models

from apps.core.models import BaseModel

from .choices import DEFAULT_PRORATION_METHOD, PayrollProrationMethod


class PayrollSetting(BaseModel):
    """
    Kebijakan penggajian satu perusahaan.

    Dua keputusan tinggal di sini, dan keduanya sengaja dipisah:
    **prorata gaji pokok** karena masuk/berhenti di tengah periode
    (Business Decision #1) dan **potongan ketidakhadiran** karena alpa
    atau cuti tidak dibayar (Business Decision #2). Yang pertama
    menentukan berapa hak gaji seseorang; yang kedua menentukan berapa
    yang hilang dari hak itu. Mencampurnya jadi satu aturan adalah cara
    membuat pegawai yang masuk tanggal 16 lalu alpa sehari diprorata
    dua kali.

    Bentuknya mengikuti `TenantSetting` dan `PrintSetting` yang sudah
    ada: **satu baris per company**, disunting lewat layar CRUD dialog,
    bisa disalin ke perusahaan lain lewat `copy_to_companies`. Yang
    dihindari dengan meniru pola itu bukan cuma kerapian — layar
    `setting` tunggal hanya bisa menyunting satu baris (`.first()`), dan
    tenant berisi dua belas perusahaan akan punya sebelas kebijakan yang
    tidak punya jalan masuk sama sekali.

    **Tidak ada konfigurasi prorata per pegawai, dan itu disengaja.**
    Dua orang di satu perusahaan dengan gaji sebulan yang sama tidak
    boleh dibayar berbeda hanya karena barisnya diisi orang yang
    berbeda. Yang boleh berbeda per pegawai cuma **fakta**-nya: tanggal
    masuk, tanggal berhenti, dan kalender kerjanya.

    Barisnya **tidak** effective-dated, dan itu keputusan, bukan
    kelalaian: payroll yang sudah Finalized kebal terhadap perubahan
    master mana pun — angkanya dibekukan di `PayrollRunEmployee.snapshot`
    dan `Payslip.snapshot`, dan run terkunci menolak dihitung ulang.
    Jadi mengganti metode hari ini hanya berlaku untuk run yang belum
    final; membangun sistem versioning kedua di atas itu berarti dua
    tempat yang harus sepakat tentang hal yang sama.
    """

    company = models.OneToOneField(
        "administration.Company",
        on_delete=models.CASCADE,
        related_name="payroll_setting",
    )

    proration_method = models.CharField(
        max_length=20,
        choices=PayrollProrationMethod.choices,
        default=DEFAULT_PRORATION_METHOD,
        help_text=(
            "Cara gaji sebulan dipecah jadi hak harian untuk pegawai "
            "yang masuk atau berhenti di tengah periode."
        ),
    )

    prorate_on_join = models.BooleanField(
        default=True,
        help_text=(
            "Pegawai yang masuk di tengah periode dibayar sejak "
            "tanggal masuknya saja. Dimatikan berarti ia menerima gaji "
            "sebulan penuh."
        ),
    )

    prorate_on_termination = models.BooleanField(
        default=True,
        help_text=(
            "Pegawai yang berhenti di tengah periode dibayar sampai "
            "hari terakhirnya saja. Dimatikan berarti ia menerima gaji "
            "sebulan penuh."
        ),
    )

    # ------------------------------------------------------------------
    # Potongan ketidakhadiran (Business Decision #2)
    #
    # Sengaja **terpisah** dari `proration_method` di atas, walaupun
    # daftar pilihannya sama. Keduanya menjawab pertanyaan yang berbeda:
    # yang di atas "berapa hak gaji orang yang belum sebulan bekerja",
    # yang di bawah "berapa nilai sehari yang hilang kalau ia tidak
    # masuk". Perusahaan yang memprorata dengan hari kalender tapi
    # memotong absen dengan pembagi 30 bukan perusahaan yang salah
    # konfigurasi — itu praktik yang lazim, dan satu kolom untuk dua
    # keputusan membuatnya mustahil.
    # ------------------------------------------------------------------

    attendance_deduction_method = models.CharField(
        max_length=20,
        choices=PayrollProrationMethod.choices,
        blank=True,
        default="",
        help_text=(
            "Pembagi yang dipakai menghitung nilai sehari untuk "
            "potongan absen dan cuti tidak dibayar. Dikosongkan "
            "berarti mengikuti pembagi hari yang tertulis di periode "
            "payroll — perilaku yang berlaku sebelum kebijakan ini ada."
        ),
    )

    deduct_absence = models.BooleanField(
        default=True,
        help_text=(
            "Hari yang tercatat alpa di absensi memotong gaji. "
            "Dimatikan berarti ketidakhadiran ditangani di luar "
            "payroll."
        ),
    )

    deduct_unpaid_leave = models.BooleanField(
        default=True,
        help_text=(
            "Hari cuti berjenis tidak dibayar memotong gaji. Jenis "
            "cuti mana yang tidak dibayar tetap ditentukan Payroll "
            "Leave Rule, bukan di sini."
        ),
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "payroll_setting"
        ordering = ["company__name"]
        verbose_name = "Payroll Setting"
        verbose_name_plural = "Payroll Settings"

    def __str__(self) -> str:
        return f"Payroll Setting - {self.company.name}"
