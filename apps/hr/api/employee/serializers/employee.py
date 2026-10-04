from rest_framework import serializers

from apps.hr.models import Employee

from .mixins.general import EmployeeGeneralFieldsMixin
from .mixins.organization import EmployeeOrganizationFieldsMixin
from .mixins.employment import EmployeeEmploymentFieldsMixin
from .mixins.payroll import EmployeePayrollFieldsMixin

from apps.hr.api.employee.services.employee_service import EmployeeService
from apps.hr.avatar import resolve_employee_avatar
from apps.uploads.api.attach import guard_attachment
from apps.uploads.api.serializers import UploadedFileReferenceSerializer

class EmployeeSerializer(
    EmployeeGeneralFieldsMixin,
    EmployeeOrganizationFieldsMixin,
    EmployeeEmploymentFieldsMixin,
    EmployeePayrollFieldsMixin,
    serializers.ModelSerializer,
):
    full_name = serializers.CharField(
        read_only=True,
    )

    display_name = serializers.CharField(
        read_only=True,
    )

    # Foto pegawai dalam bentuk yang siap dipasang layar:
    # `{url, source, initials}`.
    #
    # Dihitung `resolve_employee_avatar()` — **bukan urutan baca
    # keempat** yang ditulis ulang di sini. Daftar pegawai, kartu
    # pegawai, Self Service, dan sidebar harus menjawab "foto siapa
    # ini" dengan cara yang sama; urutan yang disalin adalah persis
    # cara dua layar mulai menampilkan hal berbeda untuk orang yang
    # sama pada saat yang sama.
    #
    # `avatar_file` sendiri tetap dikirim sebagai id, dan memang harus:
    # yang itu nilai form (widget unggah menulisinya). Yang ini nilai
    # baca — `url`-nya alamat `preview/` yang berautentikasi, jadi
    # tidak ada jalur penyimpanan mentah yang bocor lewat daftar.
    #
    # `initials` ikut dikirim supaya fallback-nya tidak dihitung ulang
    # di frontend: pegawai tanpa foto tetap punya sesuatu untuk
    # ditampilkan, dan yang ditampilkan sama di semua layar.
    avatar_display = serializers.SerializerMethodField()

    def get_avatar_display(self, obj) -> dict:
        return resolve_employee_avatar(
            obj,
            request=self.context.get("request"),
        )

    # Berkas foto untuk widget unggah di form (`detailField` pada
    # schema `avatar_file`). Tanpa ini form yang dibuka ulang hanya
    # memegang id-nya: tidak ada baris berkas, tidak ada pratinjau, dan
    # tombol hapus/ganti tidak punya `public_id` untuk ditembak.
    #
    # Versi referensi, bukan `UploadedFileSerializer` utuh: field ini
    # ikut di setiap baris daftar pegawai, dan yang utuh membawa
    # `file_url` — jalur `MEDIA_URL` statis yang terbuka tanpa login.
    avatar_file_detail = UploadedFileReferenceSerializer(
        source="avatar_file",
        read_only=True,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)

        # Foto: berkas yang ditempel harus aktif, diunggah oleh yang
        # menempel, dan belum dipakai record lain — aturan yang sama
        # dengan lampiran cuti/izin (`FileAccessService.attachment_problem`).
        # Tanpa ini id `UploadedFile` yang berurutan cukup ditebak untuk
        # mengklaim berkas orang lain, dan menempelkannya memberi hak
        # baca lewat `preview/` kepada setiap pembaca pegawai ini.
        #
        # Hanya saat fotonya **berganti**. Form mengirim ulang seluruh
        # record tiap Save; menjaga nilai yang tidak berubah membuat
        # penyunting kedua ditolak karena foto yang diunggah orang lain.
        if "avatar_file" in attrs:
            chosen = attrs["avatar_file"]
            current = (
                self.instance.avatar_file_id
                if self.instance is not None
                else None
            )

            if getattr(chosen, "pk", None) != current:
                guard_attachment(self, "avatar_file", attrs)

        return attrs

    class Meta:
        model = Employee

        fields = [
            # Base
            "id",

            # General
            "user",
            "employee_number",
            # Penanda write-only. Tidak terdaftar di sini = centang
            # Auto Generate dibuang DRF tanpa pesan, dan nomornya
            # tetap diminta manual.
            "auto_generate_employee_number",
            "nik",
            "passport_number",
            "tax_number",
            "first_name",
            "last_name",
            "gender",
            "gender_name",
            "religion",
            "nationality",
            # Tidak terdaftar di sini = blok alamat wilayah tidak pernah
            # tahu kewarganegaraannya, dan syarat tampilnya jatuh ke
            # "selalu sembunyi" begitu form dibuka ulang.
            "nationality_code",
            "blood_type",
            "marital_status",
            "birth_place",
            "birth_date",

            # Alamat. Field yang tidak terdaftar di sini membuat PATCH
            # membalas 200 lalu membuang nilainya tanpa satu pun pesan.
            "address",
            "province",
            "province_name",
            "city",
            "city_name",
            "district",
            "district_name",
            "village",
            "village_name",

            "personal_email",
            "work_email",
            "phone",
            "mobile",
            "emergency_contact_name",
            "emergency_contact_phone",
            "avatar_file",
            "avatar_file_detail",
            "avatar",
            "avatar_display",
            "notes",
            "is_active",

            # Organization
            "company",
            "company_name",
            "branch",
            "location",
            "location_name",
            "division",
            "department",
            "section",
            "position",
            "job_level",
            "job_grade",
            "reports_to",
            "reports_to_name",
            "cost_center",
            "organization_effective_date",
            "organization_notes",

            # Employment
            "employment_status",
            "employment_status_name",
            "employment_type",
            "employment_type_name",
            # Tidak terdaftar di sini = kolom kontrak di form tidak
            # pernah tahu jenis kepegawaiannya berkontrak atau tidak,
            # dan syarat tampilnya jatuh ke "selalu sembunyi".
            "employment_type_requires_contract",
            "employee_group",
            "contract_type",
            "probation_type",
            "employment_effective_date",
            "join_date",
            "confirmation_date",
            "probation_start",
            "probation_end",
            "contract_start",
            "contract_end",
            "job_location",
            "point_of_hire",
            "point_of_hire_name",

            "work_schedule",
            "work_schedule_name",
            "working_calendar",
            "shift",

            # Roster pegawai site. Tidak terdaftar di sini = PATCH
            # membalas 200 lalu nilainya dibuang tanpa pesan apa pun.
            "roster_crew",
            "roster_crew_name",
            "roster_crew_work_schedule",
            "roster_start_override",
            # Field yang tidak terdaftar di sini membuat PATCH membalas
            # 200 lalu membuang nilainya — jebakan "empat sentuhan".
            "roster_policy",
            "roster_policy_name",
            "roster_policy_cycle_length",
            "roster_start_basis_label",
            "roster_cycle_start",
            "back_to_back_partner",
            "back_to_back_partner_name",
            "travel_days_override",

            "notice_period_days",
            "employment_notes",

            # Payroll
            "payroll_group",
            "salary_grade",
            "salary_level",
            "currency",
            "payment_method",
            "tax_status",
            "tax_number_payroll",
            "bpjs_kesehatan_number",
            "bpjs_ketenagakerjaan_number",
            "overtime_eligible",
            "overtime_group",
            "basic_salary",
            "allowance_template",
            "deduction_template",
            "effective_from",
            "effective_to",
            "payroll_notes",

            # Computed
            "full_name",
            "display_name",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "is_deleted",
            "full_name",
            "display_name",
            "gender_name",
            "nationality_code",
            "province_name",
            "city_name",
            "district_name",
            "village_name",
            "employment_status_name",
            "employment_type_name",
            "employment_type_requires_contract",
            "reports_to_name",
            # Kolom foto lama. Read-only di sini, bukan cuma di schema:
            # schema menyembunyikan tombolnya, dan tombol yang
            # tersembunyi masih bisa ditembak lewat PATCH langsung.
            # Foto baru wajib lewat `avatar_file`, yang berkasnya
            # berdiri di kerangka unggahan dan penyajiannya menuntut
            # login.
            "avatar",
            # Turunan murni: dirakit dari `avatar_file` + `avatar`,
            # tidak punya kolom sendiri untuk ditulisi.
            "avatar_display",
            "avatar_file_detail",
        ]

    def create(self, validated_data):
        request = self.context.get("request")

        return EmployeeService.create(
            validated_data,
            user=request.user if request else None,
        )

    def update(self, instance, validated_data):
        request = self.context.get("request")

        return EmployeeService.update(
            instance,
            validated_data,
            user=request.user if request else None,
        )

    def _mask_hidden(self, instance, data):
        """
        Membuang field yang tidak boleh dilihat pembacanya.

        `EmployeeDataPolicy` — sumbu kedua di samping cakupan data:
        cakupan menentukan **baris** yang mana, ini menentukan **bagian
        mana** dari baris itu. Tanpa `request` di context (pemanggil
        internal, seed, task) tidak ada yang disaring; jalur API selalu
        membawanya.

        Dibuang dari payload, bukan dikosongkan jadi `null`: kolom
        kosong dan kolom yang memang belum diisi terbaca sama, dan yang
        pertama membuat orang mengira datanya hilang.
        """
        request = self.context.get("request")

        user = getattr(request, "user", None)

        if user is None:
            return set()

        from apps.hr.api.employee.visibility import EmployeeDataVisibility

        hidden = EmployeeDataVisibility.hidden_employee_fields(
            employee=instance,
            user=user,
        )

        for name in hidden:
            data.pop(name, None)

        return hidden

    def to_representation(self, instance):
        data = super().to_representation(instance)

        hidden = self._mask_hidden(instance, data)

        payroll = (
            instance.payroll_assignments
            .filter(
                is_current=True,
                is_deleted=False,
            )
            .first()
        )

        if payroll is None:
            return data

        # Blok ini menulis ulang kolom payroll dari baris `is_current`,
        # jadi ia **menghidupkan kembali** field yang barusan dibuang
        # `_mask_hidden`. Disaring lagi di sini, bukan dengan memindah
        # urutannya: nilainya memang baru ada setelah baris payroll-nya
        # dibaca.
        payroll_values = {
            "payroll_group": payroll.payroll_group_id,
            "salary_grade": payroll.salary_grade_id,
            "salary_level": payroll.salary_level_id,
            "currency": payroll.currency_id,
            "payment_method": payroll.payment_method,
            "tax_status": payroll.tax_status_id,
            "tax_number_payroll": payroll.tax_number_payroll,
            "bpjs_kesehatan_number": payroll.bpjs_kesehatan_number,
            "bpjs_ketenagakerjaan_number": (payroll.bpjs_ketenagakerjaan_number),
            "overtime_eligible": payroll.overtime_eligible,
            "overtime_group": payroll.overtime_group_id,
            "basic_salary": payroll.basic_salary,
            "allowance_template": payroll.allowance_template_id,
            "deduction_template": payroll.deduction_template_id,
            "effective_from": payroll.effective_from,
            "effective_to": payroll.effective_to,
            "payroll_notes": payroll.payroll_notes,
        }

        data.update({
            key: value
            for key, value in payroll_values.items()
            if key not in hidden
        })

        return data