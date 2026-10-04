from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .choices import PayrollRunEmployeeStatus
from .payroll_run import PayrollRun


class PayrollRunEmployee(BaseModel):
    """
    Satu pegawai di dalam satu payroll run — dan **snapshot**-nya.

    Kolom organisasi, konfigurasi payroll, dan gaji pokok disalin ke
    sini, tidak dibaca lewat relasi saat slip dibuka. Itu inti Tahap 9:
    perubahan Salary Master bulan depan tidak boleh mengubah payroll
    yang sudah terbit, dan satu-satunya cara menjamin itu adalah
    menyimpan angkanya, bukan jalan menuju angkanya.

    FK ke masternya tetap ada — untuk menyaring dan melaporkan — tapi
    yang dipakai mencetak selalu kolom nilai di baris ini.
    """

    run = models.ForeignKey(
        PayrollRun,
        on_delete=models.CASCADE,
        related_name="employees",
    )

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="payroll_run_lines",
    )

    payroll_assignment = models.ForeignKey(
        "hr.PayrollAssignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_run_lines",
    )

    # --- snapshot organisasi -------------------------------------------
    company = models.ForeignKey(
        "administration.Company", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    branch = models.ForeignKey(
        "administration.Branch", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    location = models.ForeignKey(
        "administration.Location", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    division = models.ForeignKey(
        "administration.Division", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    department = models.ForeignKey(
        "administration.Department", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    section = models.ForeignKey(
        "administration.Section", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    cost_center = models.ForeignKey(
        "administration.CostCenter", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    position = models.ForeignKey(
        "administration.Position", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )

    # --- snapshot konfigurasi payroll ----------------------------------
    payroll_group = models.ForeignKey(
        "payroll.PayrollGroup", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    salary_grade = models.ForeignKey(
        "payroll.SalaryGrade", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    salary_level = models.ForeignKey(
        "payroll.SalaryLevel", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    tax_status = models.ForeignKey(
        "payroll.TaxStatus", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    overtime_group = models.ForeignKey(
        "payroll.OvertimeGroup", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    allowance_template = models.ForeignKey(
        "payroll.AllowanceTemplate", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    deduction_template = models.ForeignKey(
        "payroll.DeductionTemplate", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )

    # Kebijakan perhitungan yang berlaku waktu run ini dihitung, beserta
    # dasar yang dipakainya. Dibekukan seperti snapshot yang lain:
    # kebijakan yang diganti bulan depan, atau assignment yang pindah
    # kebijakan, tidak boleh mengubah angka periode ini.
    #
    # Kosong = pegawai ini mengikuti `PayrollSetting` perusahaannya.
    # Bedanya dengan "punya kebijakan yang kebetulan sama" harus tetap
    # terbaca — itu yang membuat "kenapa dua orang di perusahaan yang
    # sama dihitung berbeda" punya jawaban di barisnya sendiri.
    payroll_policy = models.ForeignKey(
        "payroll.PayrollPolicy", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )

    pay_basis = models.CharField(max_length=20, blank=True, default="")

    # Upah sehari yang benar-benar dipakai, sudah hasil resolusi —
    # entah diambil apa adanya dari assignment atau diturunkan dari
    # gaji sebulan. Nol untuk pegawai bulanan.
    # Enam desimal, bukan dua, dan itu yang membuat kolomnya bisa
    # dipakai memeriksa: tarif yang diturunkan dari gaji sebulan jarang
    # bulat, dan angka yang sudah dibulatkan tidak menghasilkan upah
    # yang dibayar kalau dikalikan kembali dengan jumlah harinya.
    daily_rate = models.DecimalField(
        max_digits=18, decimal_places=6, default=0,
    )
    currency = models.ForeignKey(
        "administration.Currency", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )

    payment_method = models.CharField(max_length=30, blank=True, default="")

    # --- snapshot kepegawaian ------------------------------------------
    join_date = models.DateField(null=True, blank=True)
    termination_date = models.DateField(null=True, blank=True)

    basic_salary = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )

    # --- hari & jam yang jadi dasar hitung ------------------------------
    period_days = models.PositiveSmallIntegerField(default=0)
    working_days = models.DecimalField(
        max_digits=7, decimal_places=2, default=0,
    )
    # Hari yang dibayar. Artinya mengikuti dasar perhitungan, dan
    # kedua arti itu **sama**: hari yang menghasilkan uang. Bulanan =
    # hari masa kerja dikurangi alpa dan cuti tidak dibayar; harian =
    # hari yang benar-benar membentuk upah (pengali tarif harian).
    paid_days = models.DecimalField(
        max_digits=7, decimal_places=2, default=0,
    )
    attendance_days = models.DecimalField(
        max_digits=7, decimal_places=2, default=0,
    )
    # BT-3: hari tugas Business Trip yang dibayar — **bukan** hadir
    # fisik, jadi terpisah dari `attendance_days` dan tidak pernah
    # dihitung dua kali. Snapshot: run yang sudah Finalized tetap
    # menyimpan angka saat dihitung, apa pun yang terjadi pada dokumen
    # perjalanannya sesudah itu.
    business_trip_days = models.DecimalField(
        max_digits=7, decimal_places=2, default=0,
    )
    absent_days = models.DecimalField(
        max_digits=7, decimal_places=2, default=0,
    )
    leave_days = models.DecimalField(
        max_digits=7, decimal_places=2, default=0,
    )
    unpaid_leave_days = models.DecimalField(
        max_digits=7, decimal_places=2, default=0,
    )
    overtime_hours = models.DecimalField(
        max_digits=9, decimal_places=2, default=0,
    )

    # Faktor proration untuk pegawai yang masuk/berhenti di tengah
    # periode. 1 = sebulan penuh.
    # Kenapa gaji pokoknya jadi segitu — dijawab barisnya sendiri,
    # bukan dihitung ulang orang dari kolom lain. `working_days` di atas
    # adalah pembilangnya (hari yang benar-benar dalam masa kerja),
    # dua kolom di bawah pembagi dan metodenya.
    proration_method = models.CharField(
        max_length=20,
        blank=True,
        default="",
    )
    proration_base_days = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=0,
    )

    proration_factor = models.DecimalField(
        max_digits=9, decimal_places=6, default=1,
    )

    # --- potongan ketidakhadiran (Business Decision #2) -----------------
    #
    # Empat kolom yang membuat "kenapa pegawai ini dipotong Rp600.000"
    # dijawab barisnya sendiri. Tanpa pembagi dan metodenya, angka
    # potongan cuma bisa diperiksa dengan menghitung ulang — dan yang
    # menghitung ulang tidak tahu kebijakan mana yang berlaku waktu run
    # itu dijalankan.
    #
    # Jumlah harinya sudah ada di atas (`absent_days`,
    # `unpaid_leave_days`), sudah bersih dari tanggal yang tumpang
    # tindih: satu tanggal yang berstatus alpa di absensi sekaligus
    # cuti tidak dibayar yang disetujui dihitung **sekali**, sebagai
    # cuti.
    attendance_deduction_method = models.CharField(
        max_length=20,
        blank=True,
        default="",
    )
    deduction_base_days = models.DecimalField(
        max_digits=7, decimal_places=2, default=0,
    )
    absence_deduction = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )
    unpaid_leave_deduction = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )

    # --- hasil ----------------------------------------------------------
    gross_earning = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )
    taxable_earning = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )
    total_deduction = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )
    tax_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )
    net_pay = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )

    # Beban perusahaan atas pegawai ini — porsi pemberi kerja BPJS dan
    # sejenisnya. Tidak ikut `total_deduction`, tidak mengubah
    # `net_pay`; biaya tenaga kerja seorang pegawai adalah
    # `gross_earning + employer_contribution`.
    employer_contribution = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )

    status = models.CharField(
        max_length=20,
        choices=PayrollRunEmployeeStatus.choices,
        default=PayrollRunEmployeeStatus.PENDING,
    )

    # Pegawai yang sengaja dikeluarkan dari run ini. Barisnya tetap ada
    # — "kenapa si A tidak dibayar bulan ini" harus punya jawaban di
    # dokumen, bukan berupa baris yang menghilang tanpa jejak.
    is_excluded = models.BooleanField(default=False)
    exclusion_reason = models.TextField(blank=True)

    findings = models.JSONField(default=list, blank=True)

    # Seluruh konfigurasi yang dipakai, dibekukan saat Finalize.
    snapshot = models.JSONField(default=dict, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_run_employee"
        ordering = ["run", "employee__employee_number"]
        verbose_name = "Payroll Run Employee"
        verbose_name_plural = "Payroll Run Employees"

        constraints = [
            models.UniqueConstraint(
                fields=["run", "employee"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_run_employee",
            ),
        ]

        indexes = [
            models.Index(
                fields=["run", "status"],
                name="idx_payroll_run_emp_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.run_id} - {self.employee_id}"
