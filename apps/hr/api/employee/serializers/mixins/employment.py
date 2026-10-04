from rest_framework import serializers

from apps.hr.models import Employee

from apps.administration.models import (
    City,
    RosterCrew,
    RosterPolicy,
    WorkCalendar,
)
from apps.administration.models.references.hr import (
    ContractType,
    EmployeeGroup,
    EmploymentStatus,
    EmploymentType,
    ProbationType,
)
from apps.administration.models.references.hr_attendance import (
    Shift,
    WorkSchedule,
)


class EmployeeEmploymentFieldsMixin(
    serializers.Serializer,
):
    employment_status = serializers.PrimaryKeyRelatedField(
        source="employment.employment_status",
        queryset=EmploymentStatus.objects.all(),
        required=False,
        allow_null=True,
    )

    # Nama untuk kolom tabel. Generator FE memetakan kolom field lookup
    # ke `<nama_field>_name` kalau `display_key` kosong, jadi tanpa dua
    # field di bawah kolom "Employment Status" dan "Employment Type"
    # mencari kunci yang tidak pernah dikirim — dan tampil "-" untuk
    # semua baris tanpa satu pun pesan error.
    employment_status_name = serializers.CharField(
        source="employment.employment_status.name",
        read_only=True,
        default=None,
    )

    employment_type = serializers.PrimaryKeyRelatedField(
        source="employment.employment_type",
        queryset=EmploymentType.objects.all(),
        required=False,
        allow_null=True,
    )

    employment_type_name = serializers.CharField(
        source="employment.employment_type.name",
        read_only=True,
        default=None,
    )

    # Penanda "jenis ini memakai masa kontrak", dibaca form untuk
    # menyalakan kolom Contract Type/Start/End. Read-only dan bukan
    # kolom sungguhan: sumbernya master `EmploymentType`.
    #
    # Ada di dua jalur sekaligus dan memang harus: nilai ini terisi dari
    # sini saat form dimuat, dan diperbarui `autofill` pada field
    # Employment Type begitu penggunanya memilih jenis lain. Kalau cuma
    # salah satu, kolom kontraknya benar saat dibuka lalu salah setelah
    # diubah — atau sebaliknya.
    employment_type_requires_contract = serializers.BooleanField(
        source="employment.employment_type.requires_contract",
        read_only=True,
        default=False,
    )

    employee_group = serializers.PrimaryKeyRelatedField(
        source="employment.employee_group",
        queryset=EmployeeGroup.objects.all(),
        required=False,
        allow_null=True,
    )

    # Cermin Feature Applicability milik group, dibaca form untuk
    # menyalakan kolom Shift dan Roster. Read-only dan bukan kolom
    # sungguhan: sumbernya master `EmployeeGroup`.
    #
    # `default=True`, bukan `False` — pegawai yang belum punya group
    # tidak boleh kehilangan kolomnya, dan aturannya harus sama dengan
    # `default=True` di masternya. Alasan yang sama dengan `not is_false`
    # pada `visible_when`-nya.
    #
    # Ada di dua jalur sekaligus dan memang harus, persis seperti
    # `employment_type_requires_contract`: terisi dari sini saat form
    # dimuat, diperbarui `autofill` begitu group-nya diganti. Kalau cuma
    # salah satu, kolomnya benar saat dibuka lalu salah setelah diubah —
    # atau sebaliknya.
    employee_group_shift_applicable = serializers.BooleanField(
        source="employment.employee_group.shift_applicable",
        read_only=True,
        default=True,
    )

    employee_group_roster_applicable = serializers.BooleanField(
        source="employment.employee_group.roster_applicable",
        read_only=True,
        default=True,
    )

    contract_type = serializers.PrimaryKeyRelatedField(
        source="employment.contract_type",
        queryset=ContractType.objects.all(),
        required=False,
        allow_null=True,
    )

    probation_type = serializers.PrimaryKeyRelatedField(
        source="employment.probation_type",
        queryset=ProbationType.objects.all(),
        required=False,
        allow_null=True,
    )

    work_schedule = serializers.PrimaryKeyRelatedField(
        source="employment.work_schedule",
        queryset=WorkSchedule.objects.all(),
        required=False,
        allow_null=True,
    )

    working_calendar = serializers.PrimaryKeyRelatedField(
        source="employment.working_calendar",
        queryset=WorkCalendar.objects.all(),
        required=False,
        allow_null=True,
    )

    shift = serializers.PrimaryKeyRelatedField(
        source="employment.shift",
        queryset=Shift.objects.all(),
        required=False,
        allow_null=True,
    )

    # Gelombang rotasi pegawai site. Sudah lama ada di model dan di
    # schema form, tapi tidak pernah ada di serializer — akibatnya
    # dropdown-nya tampil kosong walau datanya terisi, dan PATCH yang
    # mengirim crew membalas 200 lalu membuang nilainya. Jebakan
    # "empat sentuhan" yang sudah tercatat di CLAUDE.md.
    roster_crew = serializers.PrimaryKeyRelatedField(
        source="employment.roster_crew",
        queryset=RosterCrew.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )

    roster_crew_name = serializers.CharField(
        source="employment.roster_crew.name",
        read_only=True,
        default=None,
    )

    # Pola kerja milik crew, dibaca untuk mengisi Work Schedule di form
    # begitu crew dipilih. Read-only: yang jadi sumber kebenaran tetap
    # `work_schedule`, ini cuma nilai yang ditawarkan.
    roster_crew_work_schedule = serializers.PrimaryKeyRelatedField(
        source="employment.roster_crew.work_schedule",
        read_only=True,
        default=None,
    )

    work_schedule_name = serializers.CharField(
        source="employment.work_schedule.name",
        read_only=True,
        default=None,
    )

    roster_start_override = serializers.DateField(
        source="employment.roster_start_override",
        required=False,
        allow_null=True,
    )

    travel_days_override = serializers.IntegerField(
        source="employment.travel_days_override",
        required=False,
        allow_null=True,
        min_value=0,
    )

    # ------------------------------------------------------------------
    # Roster
    # ------------------------------------------------------------------
    #
    # Dua kolom yang menentukan apakah pegawai ini diproses Roster
    # Generator sama sekali. Kosong = pegawai non-roster (HO), dan
    # jadwalnya tidak pernah dibuat — bukan dibuat lalu diabaikan.

    roster_policy = serializers.PrimaryKeyRelatedField(
        source="employment.roster_policy",
        queryset=RosterPolicy.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )

    roster_policy_name = serializers.CharField(
        source="employment.roster_policy.name",
        read_only=True,
        default=None,
    )

    # Dikirim supaya `visible_when` pada kolom Current Cycle Start punya
    # nilai yang bisa dinilai **saat form dimuat**, bukan cuma setelah
    # policy-nya diganti. Kalau salah satu jalur ini dicabut, kolomnya
    # benar di satu keadaan dan salah di keadaan lain.
    roster_policy_cycle_length = serializers.IntegerField(
        source="employment.roster_policy.cycle_length",
        read_only=True,
        default=None,
    )

    roster_start_basis_label = serializers.CharField(
        source="employment.roster_policy.get_roster_start_basis_display",
        read_only=True,
        default=None,
    )

    roster_cycle_start = serializers.DateField(
        source="employment.roster_cycle_start",
        required=False,
        allow_null=True,
    )

    back_to_back_partner = serializers.PrimaryKeyRelatedField(
        source="employment.back_to_back_partner",
        queryset=Employee.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )

    back_to_back_partner_name = serializers.SerializerMethodField()

    def get_back_to_back_partner_name(self, obj) -> str | None:
        employment = getattr(obj, "employment", None)
        partner = getattr(employment, "back_to_back_partner", None)

        if partner is None:
            return None

        return f"{partner.employee_number} - {partner.full_name}"

    # Kolom modelnya `employment_effective_date`. Sempat ber-`source`
    # `employment.effective_from` — nama kolom yang tidak ada di
    # `EmploymentAssignment` sama sekali, jadi tanggal yang diketik
    # pengguna berakhir sebagai atribut liar di instance, dibuang saat
    # simpan, lalu diisi ulang dari Join Date oleh
    # `EmploymentService.save()`. Membalas 200 tanpa satu pun pesan.
    employment_effective_date = serializers.DateField(
        source="employment.employment_effective_date",
        required=False,
        allow_null=True,
    )

    join_date = serializers.DateField(
        source="employment.join_date",
        required=False,
        allow_null=True,
    )

    confirmation_date = serializers.DateField(
        source="employment.confirmation_date",
        required=False,
        allow_null=True,
    )

    probation_start = serializers.DateField(
        source="employment.probation_start",
        required=False,
        allow_null=True,
    )

    probation_end = serializers.DateField(
        source="employment.probation_end",
        required=False,
        allow_null=True,
    )

    contract_start = serializers.DateField(
        source="employment.contract_start",
        required=False,
        allow_null=True,
    )

    contract_end = serializers.DateField(
        source="employment.contract_end",
        required=False,
        allow_null=True,
    )

    job_location = serializers.CharField(
        source="employment.job_location",
        required=False,
        allow_blank=True,
        default="",
    )

    # Kota rekrut — tujuan tiket pulang tiap blok off, dicetak sebagai
    # "Point Of Hire" di Travel Request.
    point_of_hire = serializers.PrimaryKeyRelatedField(
        source="employment.point_of_hire",
        queryset=City.objects.all(),
        required=False,
        allow_null=True,
    )

    point_of_hire_name = serializers.CharField(
        source="employment.point_of_hire.name",
        read_only=True,
        default=None,
    )

    notice_period_days = serializers.IntegerField(
        source="employment.notice_period_days",
        required=False,
        allow_null=True,
    )

    employment_notes = serializers.CharField(
        source="employment.employment_notes",
        required=False,
        allow_blank=True,
        default="",
    )