from rest_framework import serializers

from apps.administration.models import (
    Branch,
    Company,
    CostCenter,
    Department,
    Division,
    Position,
    Section,
    Location,
)

from apps.administration.models.references.hr import (
    JobGrade,
    JobLevel,
)

from apps.hr.models import Employee


class EmployeeOrganizationFieldsMixin(
    serializers.Serializer,
):
    company = serializers.PrimaryKeyRelatedField(
        source="organization.company",
        queryset=Company.objects.all(),
        required=False,
        allow_null=True,
    )

    # Versi siap tampil untuk kolom tabel dan kartu Overview.
    #
    # Field lookup di atas mengirim **pk**, dan generator memetakan
    # kolomnya ke `<field>_name`. Tanpa dua field ini kolom Company dan
    # Location tampil `-` di **semua** baris tanpa satu pun error —
    # kegagalan yang tidak bisa dibedakan dari data yang memang belum
    # diisi. Pola yang sama sudah menjatuhkan layar Work Calendar,
    # Holiday, dan Audit Trail.
    company_name = serializers.CharField(
        source="organization.company.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="organization.location.name",
        read_only=True,
        default=None,
    )

    branch = serializers.PrimaryKeyRelatedField(
        source="organization.branch",
        queryset=Branch.objects.all(),
        required=False,
        allow_null=True,
    )

    location = serializers.PrimaryKeyRelatedField(
        source="organization.location",
        queryset=Location.objects.all(),
        required=False,
        allow_null=True,
    )

    division = serializers.PrimaryKeyRelatedField(
        source="organization.division",
        queryset=Division.objects.all(),
        required=False,
        allow_null=True,
    )

    department = serializers.PrimaryKeyRelatedField(
        source="organization.department",
        queryset=Department.objects.all(),
        required=False,
        allow_null=True,
    )

    section = serializers.PrimaryKeyRelatedField(
        source="organization.section",
        queryset=Section.objects.all(),
        required=False,
        allow_null=True,
    )

    position = serializers.PrimaryKeyRelatedField(
        source="organization.position",
        queryset=Position.objects.all(),
        required=False,
        allow_null=True,
    )

    job_level = serializers.PrimaryKeyRelatedField(
        source="organization.job_level",
        queryset=JobLevel.objects.all(),
        required=False,
        allow_null=True,
    )

    job_grade = serializers.PrimaryKeyRelatedField(
        source="organization.job_grade",
        queryset=JobGrade.objects.all(),
        required=False,
        allow_null=True,
    )

    reports_to = serializers.PrimaryKeyRelatedField(
        source="organization.reports_to",
        queryset=Employee.objects.all(),
        required=False,
        allow_null=True,
    )

    # Label siap tampil untuk field lookup atasan.
    #
    # Tanpa ini form menampilkan **pk mentah** ("191") sampai dropdown-nya
    # dibuka. Lookup lain di layar ini selamat karena daftar opsinya
    # termuat penuh saat halaman dibuka dan komponennya bisa mencocokkan
    # sendiri; daftar pegawai dimuat belakangan, jadi tidak ada yang bisa
    # dicocokkan. Mengandalkan daftar opsi memang rapuh — nilai yang
    # kebetulan tidak ada di halaman pertama akan gagal dengan cara yang
    # sama.
    reports_to_name = serializers.SerializerMethodField()

    def get_reports_to_name(self, instance):
        organization = getattr(instance, "organization", None)
        superior = getattr(organization, "reports_to", None)

        if superior is None:
            return None

        # Bentuknya disamakan dengan `label` di `/api/hr/employees/lookup/`
        # — kalau berbeda, isi field berubah tampilan begitu dropdown-nya
        # dibuka, dan itu terbaca seperti nilainya ikut berganti.
        name = (
            superior.display_name
            or superior.full_name
            or superior.employee_number
        )

        return f"{superior.employee_number} - {name}"

    cost_center = serializers.PrimaryKeyRelatedField(
        source="organization.cost_center",
        queryset=CostCenter.objects.all(),
        required=False,
        allow_null=True,
    )

    organization_effective_date = serializers.DateField(
        source="organization.organization_effective_date",
        required=False,
        allow_null=True,
    )

    organization_notes = serializers.CharField(
        source="organization.organization_notes",
        required=False,
        allow_blank=True,
    )