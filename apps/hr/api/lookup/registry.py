from apps.framework.lookup import BaseLookup, register_lookup

from apps.hr.api.recruitment.scope import CANDIDATE_SCOPE
from apps.hr.models import (
    Candidate,
    EmployeeLeave,
    ExternalVisitor,
    JobVacancy,
    RotationPeriod,
    SiteRotation,
    TrainingProgram,
    VisitorRequest,
)


@register_lookup
class TrainingProgramLookup(BaseLookup):
    name = "training-programs"
    model = TrainingProgram

    label_field = "name"

    search_fields = [
        "code",
        "name",
    ]

    filter_fields = [
        "company_id",
        "training_category_id",
        "provider_id",
        "status",
    ]

    ordering = [
        "-start_date",
        "name",
    ]

    # Program pelatihan milik satu perusahaan.
    data_scope = {
        "company": "company",
    }


@register_lookup
class JobVacancyLookup(BaseLookup):
    name = "job-vacancies"
    model = JobVacancy

    # `title`, bukan `name` — JobVacancy tidak punya kolom `name`.
    label_field = "title"

    search_fields = [
        "code",
        "title",
    ]

    filter_fields = [
        "company_id",
        "branch_id",
        "location_id",
        "division_id",
        "department_id",
        "position_id",
        "status",
    ]

    ordering = [
        "-open_date",
        "title",
    ]

    # Semesta yang sama dengan `JobVacancyViewSet`. Lewat lowongan
    # inilah pelamar menurunkan otoritasnya.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "division": "division",
        "department": "department",
    }


@register_lookup
class SiteRotationLookup(BaseLookup):
    name = "site-rotations"
    model = SiteRotation

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
    ]

    filter_fields = [
        "employee_id",
        "company_id",
        "location_id",
        "roster_crew_id",
        "status",
    ]

    ordering = [
        "-start_date",
    ]

    # Rotasi menyebut pegawai dan penempatannya.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "own": "employee__user_id",
    }

    @classmethod
    def serialize(cls, instance):
        # SiteRotation tidak punya kolom `name`, jadi label bawaan
        # `getattr(instance, "name")` akan melempar AttributeError.
        # Labelnya dirakit dari pegawai + rentang tanggal, karena itu
        # yang membedakan dua dokumen milik orang yang sama.
        return {
            "value": instance.pk,
            "label": (
                f"{instance.employee.employee_number} — "
                f"{instance.start_date}"
                + (f" s/d {instance.end_date}" if instance.end_date else "")
            ),
        }


@register_lookup
class RotationPeriodLookup(BaseLookup):
    name = "rotation-periods"
    model = RotationPeriod

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
    ]

    filter_fields = [
        "rotation_id",
        "employee_id",
        "period_type",
        "status",
    ]

    ordering = [
        "rotation",
        "sequence",
    ]

    # Periode rotasi hanya menyimpan pegawainya, jadi cakupannya
    # lewat penempatan pegawai itu.
    data_scope = {
        "company": "employee__organization__company",
        "branch": "employee__organization__branch",
        "location": "employee__organization__location",
        "own": "employee__user_id",
    }

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": (
                f"#{instance.sequence} "
                f"{instance.get_period_type_display()} "
                f"({instance.start_date} s/d {instance.end_date})"
            ),
            # Ikut dikirim supaya `autofill` pada form Travel Request
            # bisa mengisi tanggal off begitu blok jadwal dipilih.
            # Tanpa ini pengaju harus mengetik ulang tanggal yang sudah
            # tertulis di label dropdown-nya sendiri.
            "start_date": instance.start_date,
            "end_date": instance.end_date,
        }


@register_lookup
class RosterPlanLookup(BaseLookup):
    """
    Rencana roster yang **sudah dibaselinekan** — itu satu-satunya yang
    bisa disesuaikan.

    Yang masih draft sengaja tidak muncul: jadwal yang belum disetujui
    cukup disunting langsung, dan menawarkannya di sini membuat orang
    membuat dokumen penyesuaian untuk sesuatu yang tidak perlu.
    """

    name = "roster-plans"
    model = SiteRotation

    queryset = SiteRotation.objects.select_related(
        "employee",
        "roster_policy",
    ).filter(baseline_version__isnull=False)

    search_fields = [
        "document_number",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
    ]

    filter_fields = [
        "employee_id",
        "company_id",
        "location_id",
        "roster_policy_id",
        "status",
    ]

    ordering = [
        "-start_date",
    ]

    # Sama dengan `site-rotations` — model yang sama, sudut pandang
    # yang berbeda.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "own": "employee__user_id",
    }

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": (
                f"{instance.document_number or f'#{instance.pk}'} — "
                f"{instance.employee.employee_number} "
                f"({instance.start_date} s/d {instance.end_date})"
            ),
            # Ikut dikirim supaya form penyesuaian bisa mengisi pegawai
            # dan menampilkan polanya tanpa satu request tambahan.
            "employee": instance.employee_id,
            "employee_name": instance.employee.full_name,
            "roster_policy": instance.roster_policy_id,
            "cycle_work_days": instance.cycle_work_days,
            "cycle_off_days": instance.cycle_off_days,
            "start_date": instance.start_date,
            "end_date": instance.end_date,
        }


@register_lookup
class RosterSegmentLookup(BaseLookup):
    """
    Segmen **versi berjalan** sebuah rencana.

    Disaring `version_to__isnull=True`; tanpa itu daftarnya memuat
    baris dari setiap versi lama dan orang memilih blok yang sudah
    tidak berlaku — tanpa satu pun tanda bahwa itu yang terjadi.
    """

    name = "rotation-segments"
    model = RotationPeriod

    queryset = RotationPeriod.objects.filter(version_to__isnull=True)

    search_fields = [
        "employee__employee_number",
    ]

    filter_fields = [
        "rotation_id",
        "employee_id",
        "segment_type",
        "cycle_number",
    ]

    ordering = [
        "start_date",
        "sequence",
    ]

    # Sama dengan `rotation-periods`.
    data_scope = {
        "company": "employee__organization__company",
        "branch": "employee__organization__branch",
        "location": "employee__organization__location",
        "own": "employee__user_id",
    }

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": (
                f"Cycle {instance.cycle_number} · "
                f"{instance.get_segment_type_display()} "
                f"({instance.start_date} s/d {instance.end_date})"
            ),
            "segment_type": instance.segment_type,
            "cycle_number": instance.cycle_number,
            "start_date": instance.start_date,
            "end_date": instance.end_date,
        }


@register_lookup
class EmployeeLeaveLookup(BaseLookup):
    """
    Dipakai periode roster untuk menunjuk catatan cuti yang memotong
    saldo pada blok off itu. Disaring `employee_id` dari form — tanpa
    penyaringan, daftarnya seluruh cuti setenant dan nyaris pasti salah
    pilih.
    """

    name = "employee-leaves"
    model = EmployeeLeave

    # Label-nya menyebut nama jenis cuti; tanpa ini setiap baris daftar
    # menambah satu query.
    queryset = EmployeeLeave.objects.select_related("leave_type")

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
    ]

    filter_fields = [
        "employee_id",
        "leave_type_id",
        "status",
    ]

    ordering = [
        "-start_date",
    ]

    # Cuti seseorang adalah data orang itu, dan sampai Stage 3B
    # dropdown ini mengirimkan seluruhnya ke siapa pun yang login —
    # `employee_id` dari form memang menyaringnya, tapi param itu
    # datang dari klien dan bisa dihilangkan.
    #
    # Disaring lewat kolom milik barisnya sendiri (`company`,
    # `location`, …), bukan lewat penempatan pegawainya hari ini:
    # alasannya sama dengan `PAYROLL_RUN_EMPLOYEE_SCOPE` — dokumen yang
    # sudah terbit tidak berpindah pemilik karena orangnya dimutasi.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "own": "employee__user_id",
    }

    require_view_permission = True

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": (
                f"{instance.leave_type.name} "
                f"({instance.start_date} s/d {instance.end_date})"
            ),
        }


@register_lookup
class CandidateLookup(BaseLookup):
    name = "candidates"
    model = Candidate

    label_field = "full_name"

    search_fields = [
        "candidate_number",
        "full_name",
        "email",
    ]

    filter_fields = [
        "vacancy_id",
        "source_id",
        "status_id",
    ]

    ordering = [
        "-applied_date",
        "full_name",
    ]

    # Semesta yang sama dengan tabelnya (`CandidateViewSet`), lewat
    # peta yang sama — bukan salinan. Dropdown yang lebih luas dari
    # tabelnya berarti yang tidak muncul di daftar tetap bisa dipilih,
    # dan bedanya tidak terlihat siapa pun.
    data_scope = CANDIDATE_SCOPE

    require_view_permission = True

    @classmethod
    def serialize(cls, instance):
        """
        Hanya yang dibutuhkan untuk **memilih**.

        Bawaan `BaseLookup` memulangkan `value` dan `label` saja, dan
        itu memang cukup di sini. Ditulis eksplisit supaya penambahan
        kolom di masa depan — email, telepon, gaji yang diharapkan —
        jadi keputusan sadar, bukan akibat sampingan dari mengubah
        `label_field`.
        """
        return {
            "value": instance.pk,
            "label": instance.full_name,
            "code": instance.candidate_number,
        }


# ---------------------------------------------------------------------
# Visitor Management
# ---------------------------------------------------------------------


@register_lookup
class ExternalVisitorLookup(BaseLookup):
    """
    Tamu luar yang sudah terdaftar.

    Ini yang membuat "cari tamu yang pernah datang" mungkin di form
    Visitor Request — tanpa lookup ini, satu-satunya jalan adalah
    mengetik ulang identitasnya tiap kunjungan, dan sesudah itu satu
    orang punya dua belas baris master dengan dua belas ejaan nama.

    Tamu blacklist **tetap** muncul di daftar, dan itu disengaja: yang
    menolaknya `VisitorRequestService.assert_visitor_allowed` dengan
    menyebut alasannya. Membuangnya dari dropdown membuat penggunanya
    menyimpulkan datanya belum ada lalu membuat baris kedua untuk orang
    yang sama — persis cara daftar hitam dilewati tanpa ada yang
    berniat melewatinya.
    """

    name = "external-visitors"
    model = ExternalVisitor

    label_field = "full_name"

    queryset = ExternalVisitor.objects.select_related("city")

    # `email` dan `mobile` sengaja **tidak** ikut dicari. Keduanya
    # bukan cara pos jaga mengenali tamu — yang disodorkan tamu di
    # meja depan kartu identitas — dan mencantumkannya membuat
    # dropdown ini bisa dipakai memastikan alamat surel seseorang.
    #
    # `identity_number` tetap bisa dicari (tamu menyodorkan KTP-nya)
    # tapi **tidak** dikembalikan di payload: memastikan nomor yang
    # sudah dipegang berbeda dari membagikan nomor seluruh daftar.
    search_fields = [
        "visitor_number",
        "full_name",
        "identity_number",
        "organization_name",
    ]

    filter_fields = [
        "identity_type",
        "nationality_id",
        "city_id",
        "country_id",
        "is_blacklisted",
    ]

    ordering = [
        "full_name",
    ]

    @classmethod
    def serialize(cls, instance):
        data = super().serialize(instance)

        # Nama saja tidak cukup membedakan dua tamu bernama sama —
        # dan di daftar vendor itu keadaan yang lumrah. Perusahaan
        # asalnya yang membedakan, jadi ikut di label.
        if instance.organization_name:
            data["label"] = (
                f"{instance.full_name} — {instance.organization_name}"
            )

        data["visitor_number"] = instance.visitor_number
        data["organization_name"] = instance.organization_name
        data["is_blacklisted"] = instance.is_blacklisted

        return data


@register_lookup
class VisitorRequestLookup(BaseLookup):
    """
    Dokumen kunjungan — dipakai field `request` pada Visitor Pass.
    """

    name = "visitor-requests"
    model = VisitorRequest

    queryset = VisitorRequest.objects.select_related(
        "employee",
        "external_visitor",
    )

    search_fields = [
        "document_number",
        "external_visitor__full_name",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
    ]

    filter_fields = [
        "company_id",
        "location_id",
        "host_employee_id",
        "visitor_type",
        "status",
    ]

    ordering = [
        "-visit_start_date",
    ]

    # Dokumen kunjungan menyebut tuan rumah dan tamunya. Pos jaga satu
    # site tidak perlu membaca kunjungan site lain.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "own": "employee__user_id",
    }

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": (
                f"{instance.document_number or 'VR'} — "
                f"{instance.visitor_name or 'Visitor'} "
                f"({instance.visit_start_date})"
            ),
            "visit_start_date": instance.visit_start_date,
            "visit_end_date": instance.visit_end_date,
            "status": instance.status,
        }
