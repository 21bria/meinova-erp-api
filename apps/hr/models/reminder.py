"""
Kebijakan pengingat tanggal kepegawaian.

Empat tanggal yang sudah tersimpan di master tapi tidak pernah ada yang
menagihnya: masa percobaan yang mau habis, kontrak yang mau berakhir,
ulang tahun, dan hari jadi kerja. Ketiga yang pertama punya konsekuensi
administratif — kalau lewat tanpa keputusan, pegawainya otomatis jadi
tetap, atau justru bekerja tanpa dasar kontrak.

**Berapa hari sebelumnya harus muncul adalah kebijakan perusahaan,
bukan angka yang boleh ditebak kode.** HR yang butuh dua minggu untuk
menyiapkan berkas perpanjangan kontrak berbeda dari yang butuh sebulan,
dan menanam salah satunya di kode berarti tenant lain harus menunggu
rilis. Karena itu ambangnya per jenis, diatur dari layar.

Dipisah per jenis, bukan satu ambang untuk semuanya: ulang tahun yang
diingatkan 30 hari sebelumnya sama tidak bergunanya dengan kontrak yang
baru diingatkan H-3.
"""

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel


class ReminderKind(models.TextChoices):
    PROBATION_END = "probation_end", "Probation End"
    CONTRACT_END = "contract_end", "Contract End"
    BIRTHDAY = "birthday", "Birthday"
    WORK_ANNIVERSARY = "work_anniversary", "Work Anniversary"


class EmployeeReminderPolicy(BaseModel):
    name = models.CharField(max_length=100, default="Default")

    # ------------------------------------------------------------------
    # Masa percobaan
    # ------------------------------------------------------------------

    probation_enabled = models.BooleanField(
        default=True,
        help_text="Ingatkan masa percobaan yang akan berakhir.",
    )

    probation_lead_days = models.PositiveSmallIntegerField(
        default=14,
        help_text=(
            "Berapa hari sebelum masa percobaan berakhir pengingatnya "
            "mulai muncul."
        ),
    )

    # ------------------------------------------------------------------
    # Kontrak
    # ------------------------------------------------------------------

    contract_enabled = models.BooleanField(
        default=True,
        help_text="Ingatkan kontrak kerja yang akan berakhir.",
    )

    contract_lead_days = models.PositiveSmallIntegerField(
        default=30,
        help_text=(
            "Berapa hari sebelum kontrak berakhir pengingatnya mulai "
            "muncul. Umumnya lebih panjang dari masa percobaan karena "
            "perpanjangan kontrak butuh persetujuan berlapis."
        ),
    )

    # ------------------------------------------------------------------
    # Tanggal personal
    # ------------------------------------------------------------------

    birthday_enabled = models.BooleanField(
        default=True,
        help_text="Ingatkan ulang tahun pegawai.",
    )

    birthday_lead_days = models.PositiveSmallIntegerField(
        default=7,
        help_text="Berapa hari sebelum ulang tahun pengingatnya muncul.",
    )

    anniversary_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Ingatkan hari jadi kerja (ulang tahun masa kerja). "
            "Dimatikan secara bawaan — tidak semua perusahaan "
            "memperingatinya."
        ),
    )

    anniversary_lead_days = models.PositiveSmallIntegerField(
        default=7,
        help_text="Berapa hari sebelum hari jadi kerja pengingatnya muncul.",
    )

    # ------------------------------------------------------------------
    # Perilaku
    # ------------------------------------------------------------------

    keep_overdue_days = models.PositiveSmallIntegerField(
        default=30,
        help_text=(
            "Berapa lama tanggal yang sudah lewat tetap ditampilkan. "
            "Nol berarti langsung hilang begitu tanggalnya lewat — dan "
            "kontrak yang terlewat justru itu yang paling perlu "
            "terlihat, karena pegawainya masih bekerja tanpa dasar."
        ),
    )

    # ------------------------------------------------------------------
    # Penerima
    # ------------------------------------------------------------------

    notify_hr = models.BooleanField(
        default=True,
        help_text=(
            "Kirim pengingat ke pemegang role HR. Yang diterima "
            "masing-masing tetap dibatasi cakupan datanya — admin site "
            "tidak menerima pengingat pegawai kantor pusat."
        ),
    )

    notify_employee = models.BooleanField(
        default=False,
        help_text=(
            "Kirim juga ke pegawai yang bersangkutan, untuk masa "
            "percobaan dan kontrak saja. Ulang tahun tidak pernah "
            "dikirim ke orangnya sendiri."
        ),
    )

    # ------------------------------------------------------------------
    # Tonggak email
    # ------------------------------------------------------------------

    email_milestones = models.CharField(
        max_length=100,
        default="30,14,7,1",
        blank=True,
        help_text=(
            "Sisa hari saat email dikirim, dipisah koma. Bel diperbarui "
            "tiap hari sebagai hitung mundur; email tidak boleh begitu — "
            "tiga puluh salinan surat yang sama membuat orang berhenti "
            "membaca yang ke-31. Dikosongkan = tidak ada email pengingat, "
            "hanya bel."
        ),
    )

    is_default = models.BooleanField(default=True)

    class Meta:
        db_table = "hr_employee_reminder_policy"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        # Ambang nol berarti pengingatnya baru muncul di hari-H, dan itu
        # tidak menyisakan waktu untuk menyiapkan apa pun. Dimatikan
        # lewat penanda `*_enabled`, bukan lewat ambang nol — dua cara
        # mematikan hal yang sama membuat layarnya membingungkan.
        zero = [
            name
            for name, enabled, days in [
                ("probation_lead_days", self.probation_enabled, self.probation_lead_days),
                ("contract_lead_days", self.contract_enabled, self.contract_lead_days),
                ("birthday_lead_days", self.birthday_enabled, self.birthday_lead_days),
                (
                    "anniversary_lead_days",
                    self.anniversary_enabled,
                    self.anniversary_lead_days,
                ),
            ]
            if enabled and not days
        ]

        if zero:
            raise ValidationError(
                {
                    name: (
                        "Isi minimal 1 hari, atau matikan pengingatnya "
                        "lewat penanda di atasnya."
                    )
                    for name in zero
                },
            )

    # ------------------------------------------------------------------

    @property
    def milestones(self) -> list[int]:
        """
        Tonggak email sebagai daftar angka, urut menurun.

        Nilai yang tidak masuk akal **dibuang diam-diam**, bukan
        menggagalkan seluruh pengingat: kolom ini diketik tangan, dan
        satu koma berlebih tidak boleh membuat seluruh tenant berhenti
        menerima pemberitahuan kontrak.
        """
        found: set[int] = set()

        for piece in str(self.email_milestones or "").split(","):
            piece = piece.strip()

            if not piece.lstrip("-").isdigit():
                continue

            value = int(piece)

            if value >= 0:
                found.add(value)

        return sorted(found, reverse=True)

    @classmethod
    def resolve(cls) -> "EmployeeReminderPolicy":
        """
        Kebijakan yang berlaku, dibuatkan bawaan kalau belum ada.

        Dibuat saat dibaca, bukan lewat migrasi data: tenant baru tidak
        boleh punya dashboard yang kosong hanya karena seed-nya belum
        dijalankan, dan angkanya memang punya bawaan yang masuk akal.
        """
        policy = (
            cls.objects
            .filter(is_deleted=False)
            .order_by("-is_default", "id")
            .first()
        )

        if policy is None:
            policy = cls.objects.create(name="Default", is_default=True)

        return policy
