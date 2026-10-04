from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel

from apps.administration.models import (
    EmploymentStatus,
    EmploymentType,
    EmployeeGroup,
    ContractType,
    ProbationType,
    TerminationReason,
    WorkCalendar,
    WorkSchedule,
    Shift,
)

from .employee import Employee

class EmploymentAssignment(BaseModel):
    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name="employment",
    )

    # Nullable supaya import massal bisa menyimpan tanggal bergabung
    # dan masa kontrak walau file klien belum memuat klasifikasi
    # kepegawaian. Form tetap mewajibkannya lewat schema — yang
    # dilonggarkan hanya modelnya, bukan input manual.
    employment_status = models.ForeignKey(
        EmploymentStatus,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    employment_type = models.ForeignKey(
        EmploymentType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    employee_group = models.ForeignKey(
        EmployeeGroup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    contract_type = models.ForeignKey(
        ContractType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    probation_type = models.ForeignKey(
        ProbationType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    join_date = models.DateField(
        null=True,
        blank=True,
    )

    employment_effective_date = models.DateField(
        null=True,
        blank=True,
    )

    confirmation_date = models.DateField(
        null=True,
        blank=True,
    )

    probation_start = models.DateField(
        null=True,
        blank=True,
    )

    probation_end = models.DateField(
        null=True,
        blank=True,
    )

    contract_start = models.DateField(
        null=True,
        blank=True,
    )

    contract_end = models.DateField(
        null=True,
        blank=True,
    )

    termination_date = models.DateField(
        null=True,
        blank=True,
    )

    termination_reason = models.ForeignKey(
        TerminationReason,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    retirement_date = models.DateField(
        null=True,
        blank=True,
    )

    work_schedule = models.ForeignKey(
        WorkSchedule,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    working_calendar = models.ForeignKey(
        WorkCalendar,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    shift = models.ForeignKey(
        Shift,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    # Gelombang rotasi untuk pegawai site. Titik jangkar siklusnya ada
    # di `RosterCrew.cycle_start_date` supaya menggeser jadwal satu
    # gelombang cukup mengubah satu baris.
    roster_crew = models.ForeignKey(
        "administration.RosterCrew",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    # ------------------------------------------------------------------
    # Roster
    # ------------------------------------------------------------------
    #
    # Dua kolom ini yang menentukan apakah seseorang diproses generator
    # roster sama sekali. Kosong = pegawai non-roster (HO), dan jadwal
    # tidak pernah dibuatkan untuknya — bukan dibuat lalu diabaikan.

    roster_policy = models.ForeignKey(
        "administration.RosterPolicy",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
        help_text=(
            "Pola roster pegawai ini (6:2, 8:2, …). Dikosongkan = "
            "pegawai non-roster, tidak diproses Roster Generator."
        ),
    )

    # Jangkar **per pegawai**, bukan per crew. Dua orang dengan policy
    # yang sama persis boleh punya tanggal mulai yang berbeda — itu
    # keadaan normal di site yang gelombangnya bergantian, dan
    # memaksakan satu jangkar bersama membuat setiap pengecualian jadi
    # kasus khusus permanen.
    #
    # Artinya ditentukan `RosterPolicy.roster_start_basis`: hari pertama
    # kerja, hari tiba di site, atau hari berangkat dari Point of Hire.
    roster_cycle_start = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Current Cycle Start pegawai ini. Artinya mengikuti Cycle "
            "Start Basis pada Roster Policy-nya. Boleh tanggal lampau — "
            "jadwal berangkat dari blok yang sedang dijalani."
        ),
    )

    roster_start_basis = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=(
            "Menimpa Cycle Start Basis milik policy untuk pegawai ini "
            "saja. Dikosongkan = ikut policy."
        ),
    )

    # Pasangan back-to-back: yang masuk saat orang ini off. **Referensi,
    # bukan validasi** — pegawai tanpa pasangan tetap sah, dan tidak ada
    # satu pun jalur yang memblokir karena kolom ini kosong. Yang ada
    # cuma peringatan di layar preview, dan pembanding jadwal di layar
    # detail.
    #
    # Sengaja tidak disimetriskan otomatis: A menunjuk B sementara B
    # menunjuk C adalah keadaan yang perlu dilihat orang, bukan
    # dibetulkan diam-diam.
    back_to_back_partner = models.ForeignKey(
        "hr.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="back_to_back_of",
        help_text=(
            "Pegawai yang masuk saat orang ini off. Opsional — tidak "
            "pernah menghalangi jadwal disetujui."
        ),
    )

    # Menimpa jangkar milik crew untuk pegawai yang swing-nya digeser
    # sendiri (ganti gelombang, kembali dari cuti panjang). Kosong =
    # ikut crew.
    # Menimpa hari perjalanan hasil pencocokan (site, POH). Untuk
    # kasus yang tidak bisa disimpulkan dari jarak: pegawai yang
    # rutenya bersambung, atau yang memang disepakati berbeda.
    # Kosong = ikut master Roster Policy.
    travel_days_override = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Hari perjalanan sekali jalan khusus pegawai ini. "
            "Kosongkan untuk ikut aturan (site, Point of Hire)."
        ),
    )

    roster_start_override = models.DateField(
        null=True,
        blank=True,
    )

    # Penempatan kerja apa adanya dari file klien ("Jakarta", "Gebe",
    # "Gebe/Bacan/Ternate"). Sengaja teks, bukan FK ke Location:
    # nilainya sering belum ada di master dan bisa lebih dari satu
    # lokasi. Penempatan terstrukturnya tetap di
    # `OrganizationAssignment.location`.
    job_location = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    # Kota tempat pegawai direkrut — "Point Of Hire" di form Travel
    # Request. Bukan basa-basi administratif: ke sanalah perusahaan
    # menanggung tiket pulang setiap blok off, jadi kolom ini yang
    # menentukan tujuan travel out, bukan alamat rumah yang bisa
    # berpindah-pindah.
    #
    # Menempel di penempatan kerja, bukan di `Employee`: pegawai yang
    # dipindah basis rekrutnya (Denpasar → Makassar) mengubah hak tiketnya
    # sejak penempatan itu berlaku.
    point_of_hire = models.ForeignKey(
        "administration.City",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    notice_period_days = models.PositiveIntegerField(
        default=0,
    )

    employment_notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_employment"
        ordering = [
            "employee__employee_number",
        ]


    def clean(self):
        super().clean()

        errors = {}

        # ---------------------------------------------------------
        # Probation
        # ---------------------------------------------------------

        if (
            self.probation_start
            and not self.probation_end
        ):
            errors["probation_end"] = (
                "Probation End wajib diisi."
            )

        if (
            self.probation_end
            and not self.probation_start
        ):
            errors["probation_start"] = (
                "Probation Start wajib diisi."
            )

        if (
            self.probation_start
            and self.probation_end
            and self.probation_end < self.probation_start
        ):
            errors["probation_end"] = (
                "Probation End tidak boleh lebih awal "
                "dari Probation Start."
            )

        if (
            self.probation_type
            and (
                not self.probation_start
                or not self.probation_end
            )
        ):
            errors["probation_type"] = (
                "Probation Start dan Probation End "
                "wajib diisi jika Probation Type dipilih."
            )

        # ---------------------------------------------------------
        # Contract
        # ---------------------------------------------------------

        if (
            self.contract_start
            and not self.contract_end
        ):
            errors["contract_end"] = (
                "Contract End wajib diisi."
            )

        if (
            self.contract_end
            and not self.contract_start
        ):
            errors["contract_start"] = (
                "Contract Start wajib diisi."
            )

        if (
            self.contract_start
            and self.contract_end
            and self.contract_end < self.contract_start
        ):
            errors["contract_end"] = (
                "Contract End tidak boleh lebih awal "
                "dari Contract Start."
            )

        if (
            (
                self.contract_start
                or self.contract_end
            )
            and not self.contract_type
        ):
            errors["contract_type"] = (
                "Contract Type wajib dipilih "
                "jika Contract Start atau Contract End diisi."
            )

        # Pegawai tetap tidak boleh membawa masa kontrak yang masih
        # terisi. Bukan soal kerapian: baris "Employment Type =
        # Permanent" berdampingan dengan "Contract End = 2026-08-03"
        # terbaca sebagai pegawai tetap yang kontraknya akan habis, dan
        # tidak ada satu pun cara membedakannya dari kontrak yang memang
        # masih berjalan. Kontrak PKWT-nya yang dulu tetap ada — di
        # riwayat Employee Action, bukan di kolom keadaan sekarang.
        #
        # Penentunya `EmploymentType.requires_contract`, bukan kode
        # master: tenant yang menamai jenis kepegawaiannya sendiri tidak
        # boleh lolos dari aturan ini hanya karena kodenya bukan "CONT".
        if (
            self.employment_type_id
            and not self.employment_type.requires_contract
            and (self.contract_start or self.contract_end)
        ):
            errors["contract_end"] = (
                f"{self.employment_type.name} tidak memakai masa "
                "kontrak. Kosongkan Contract Start/End — kontrak "
                "sebelumnya tetap tersimpan di riwayat Employee Action."
            )

        # ---------------------------------------------------------
        # Confirmation
        # ---------------------------------------------------------
        #
        # Semua perbandingan di bawah menjaga `join_date` yang kosong
        # lebih dulu. Kolomnya nullable (import massal boleh menyimpan
        # tanggal tanpa klasifikasi kepegawaian), dan
        # `date < None` melempar TypeError — 500 tanpa pesan, bukan 400
        # berisi nama kolomnya.

        if (
            self.confirmation_date
            and self.join_date
            and self.confirmation_date < self.join_date
        ):
            errors["confirmation_date"] = (
                "Confirmation Date tidak boleh lebih awal "
                "dari Join Date."
            )

        # ---------------------------------------------------------
        # Termination
        # ---------------------------------------------------------

        if (
            self.termination_date
            and self.join_date
            and self.termination_date < self.join_date
        ):
            errors["termination_date"] = (
                "Termination Date tidak boleh lebih awal "
                "dari Join Date."
            )

        if (
            self.termination_reason
            and not self.termination_date
        ):
            errors["termination_date"] = (
                "Termination Date wajib diisi jika "
                "Termination Reason dipilih."
            )

        if (
            self.termination_date
            and not self.termination_reason
        ):
            errors["termination_reason"] = (
                "Termination Reason wajib diisi jika "
                "Termination Date diisi."
            )

        # ---------------------------------------------------------
        # Retirement
        # ---------------------------------------------------------

        if (
            self.retirement_date
            and self.join_date
            and self.retirement_date < self.join_date
        ):
            errors["retirement_date"] = (
                "Retirement Date tidak boleh lebih awal "
                "dari Join Date."
            )

        # ---------------------------------------------------------
        # Roster
        # ---------------------------------------------------------

        # Override tanpa crew tidak punya arti: yang ditimpa adalah
        # jangkar milik crew.
        if self.roster_start_override and not self.roster_crew_id:
            errors["roster_crew"] = (
                "Roster Crew wajib dipilih jika Roster Start Override "
                "diisi."
            )

        # Crew menentukan pola kerjanya, jadi work_schedule yang
        # berbeda dari milik crew akan membuat perhitungan hari kerja
        # dan absensi memakai dua pola yang bertentangan.
        if (
            self.roster_crew_id
            and self.work_schedule_id
            and self.roster_crew.work_schedule_id != self.work_schedule_id
        ):
            errors["work_schedule"] = (
                "Work Schedule harus sama dengan milik Roster Crew "
                f"({self.roster_crew.work_schedule})."
            )

        # ---------------------------------------------------------
        # Roster Policy
        # ---------------------------------------------------------

        policy = self.roster_policy if self.roster_policy_id else None

        # Policy tanpa pola tetap sah sebagai aturan site — hari
        # perjalanan, tenggat pengajuan — tapi tidak bisa menghasilkan
        # jadwal. Ditolak di sini, di layar tempat orangnya memilih,
        # bukan nanti saat generate gagal jauh dari form.
        if policy is not None and not policy.has_cycle_pattern:
            errors["roster_policy"] = (
                f"{policy.code} belum mengisi pola siklus (Work Days / "
                "Field Break Days), jadi tidak bisa dipakai sebagai "
                "roster pegawai. Isi polanya di master Roster Policy, "
                "atau pilih policy lain."
            )

        # Jangkar tanpa policy tidak punya arti: yang menentukan apa
        # arti tanggal itu adalah Cycle Start Basis milik policy.
        if self.roster_cycle_start and not self.roster_policy_id:
            errors["roster_policy"] = (
                "Roster Policy wajib dipilih jika Current Cycle Start "
                "diisi."
            )

        # Sebaliknya: policy tanpa jangkar tidak bisa menghasilkan
        # tanggal apa pun. Generator akan melewatinya diam-diam, dan
        # pegawainya kehilangan jadwal tanpa ada yang tahu kenapa.
        if self.roster_policy_id and not self.roster_cycle_start:
            errors["roster_cycle_start"] = (
                "Current Cycle Start wajib diisi untuk pegawai roster — "
                "tanpa titik jangkar, sistem tidak tahu pegawai ini "
                "sedang di hari ke berapa siklusnya."
            )

        # **Roster Policy yang menentukan; crew mengikutinya.** Urutan
        # ini kebalikan dari yang dulu berlaku, dan pembalikannya
        # disengaja: pola sekarang milik policy. Dua sumber yang
        # berbeda menghasilkan jadwal dan perhitungan cuti yang
        # berbeda, dan tidak ada satu layar pun yang memperlihatkannya.
        if policy is not None and self.roster_crew_id:
            schedule = self.roster_crew.work_schedule

            crew_pattern = (
                schedule.cycle_work_days,
                schedule.cycle_off_days,
            )

            policy_pattern = (
                policy.cycle_work_days,
                policy.cycle_off_days,
            )

            if crew_pattern != policy_pattern:
                errors["roster_crew"] = (
                    f"Pola Roster Crew ({crew_pattern[0]}/"
                    f"{crew_pattern[1]}) berbeda dari Roster Policy "
                    f"{policy.code} ({policy_pattern[0]}/"
                    f"{policy_pattern[1]}). Samakan salah satunya — "
                    "dua pola yang bertentangan menghasilkan jadwal "
                    "dan potongan cuti yang berbeda."
                )

        # Pasangan back-to-back adalah referensi, bukan aturan. Yang
        # dijaga cuma satu hal yang tidak mungkin benar.
        if (
            self.back_to_back_partner_id
            and self.employee_id
            and self.back_to_back_partner_id == self.employee_id
        ):
            errors["back_to_back_partner"] = (
                "Pegawai tidak bisa jadi pasangan back-to-back dirinya "
                "sendiri."
            )

        if errors:
            raise ValidationError(errors)


    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.employee.full_name}"
        )