from django.db.models import (
    BooleanField,
    Count,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
)

from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.accounts import board
from apps.administration.models import (
    Branch,
    Company,
    CostCenter,
    Department,
    Division,
    Position,
    Section,
    Facility,
    Location,
)


# ======================================================================
# Organization Scope — peta cakupan data per dropdown
# ======================================================================
#
# Dropdown organisasi adalah **pilihan filter** dashboard dan laporan,
# jadi isinya harus sudah tersaring cakupan data pemegang akun: filter
# hanya boleh mempersempit apa yang boleh dilihat, tidak pernah
# memperluasnya. Tanpa peta di bawah, GM yang cakupannya dua company
# tetap melihat nama seluruh perusahaan di tenant dan bisa memilih
# perusahaan yang bukan tanggung jawabnya.
#
# Petanya dua arah, dan arah keduanya yang sering terlupa:
#
# * **ke atas** lewat FK langsung (`company_id` pada Location) — yang
#   bercakupan company melihat lokasi miliknya saja;
# * **ke bawah** lewat relasi balik (`locations__id` pada Company) —
#   yang cakupannya cuma satu lokasi (role bermode `own` sedalam
#   Location) melihat perusahaan pemilik lokasi itu saja, bukan
#   ketiga-tiganya.
#
# Arah kedua hanya dipasang di Company/Branch/Location karena ketiganya
# yang berdiri sebagai filter di layar. Yang lebih dalam cukup ke atas:
# jenis cakupan yang tidak ada di peta **dilewati**, bukan menolak
# semua (lihat `DataScopeService.filter`).

COMPANY_SCOPE = {
    "company": "id",
    "branch": "branches__id",
    "location": "locations__id",
    "division": "divisions__id",
    "department": "departments__id",
    "section": "sections__id",
    "cost_center": "cost_centers__id",
}

BRANCH_SCOPE = {
    "company": "company_id",
    "branch": "id",
    "location": "locations__id",
    "division": "divisions__id",
    "department": "departments__id",
    "section": "sections__id",
    "cost_center": "cost_centers__id",
}

LOCATION_SCOPE = {
    "company": "company_id",
    "branch": "branch_id",
    "location": "id",
    "division": "divisions__id",
    "department": "departments__id",
    "section": "sections__id",
    "cost_center": "cost_centers__id",
}

DIVISION_SCOPE = {
    "company": "company_id",
    "branch": "branch_id",
    "location": "location_id",
    "division": "id",
}

DEPARTMENT_SCOPE = {
    "company": "company_id",
    "branch": "branch_id",
    "location": "location_id",
    "division": "division_id",
    "department": "id",
}

SECTION_SCOPE = {
    "company": "company_id",
    "branch": "branch_id",
    "location": "location_id",
    "division": "division_id",
    "department": "department_id",
    "section": "id",
}

POSITION_SCOPE = {
    "company": "company_id",
    "branch": "branch_id",
    "location": "location_id",
    "division": "division_id",
    "department": "department_id",
    "section": "section_id",
}

COST_CENTER_SCOPE = {
    "company": "company_id",
    "branch": "branch_id",
    "location": "location_id",
    "division": "division_id",
    "department": "department_id",
    "cost_center": "id",
}

FACILITY_SCOPE = {
    "company": "company_id",
    "branch": "branch_id",
    "location": "location_id",
}


# **Kolom induk yang kosong ikut lolos**, dan ini bukan kelonggaran
# yang diambil diam-diam: di master organisasi hanya `company` yang
# wajib, dan induk kosong sudah punya arti tetap di modul ini —
# "berlaku umum", aturan yang sama persis dipakai `apply_filters` di
# bawah dan resolver import pegawai.
#
# Tanpa ini, penambahan cakupan pada dropdown justru **mencabut** yang
# sudah jalan: department, jabatan, dan cost center yang lokasinya
# memang sengaja dibiarkan kosong akan hilang dari dropdown seluruh
# admin site — hilang tanpa pesan, dan dari kursinya terbaca seperti
# masternya yang terhapus.
SCOPE_ALLOW_NULL = True


class OrganizationScopedLookup(BaseLookup):
    """
    Lookup master organisasi yang menerima SELURUH induk di atasnya,
    bukan cuma induk terdekat.

    Dua alasan:

    1. Hierarki boleh dilompati (Location.branch boleh kosong), jadi form
       yang cuma mengisi Company harus tetap bisa menyaring. Menyaring
       satu level saja membuat dropdown menampilkan data seluruh
       perusahaan begitu level perantaranya dilewati.
    2. Induk yang kosong di master berarti "berlaku umum", jadi
       penyaringan memakai pola "cocok dengan induk ATAU induknya
       kosong" — sama dengan resolver import di
       `apps/hr/imports/employee/resolver.py`.
    """

    data_scope_allow_null = SCOPE_ALLOW_NULL

    @classmethod
    def apply_filters(cls, queryset, params):
        for field_name in cls.filter_fields:
            values = cls.filter_values(params, field_name)

            if not values:
                continue

            # Bercentang banyak di induknya: `?company_id=1,2` datang
            # dari filter Company yang sekarang multi-select. Sesama
            # nilai di satu parameter di-OR-kan lewat `__in`, sama
            # dengan aturan filter dashboard.
            condition = (
                Q(**{field_name: values[0]})
                if len(values) == 1
                else Q(**{f"{field_name}__in": values})
            )

            if cls.is_nullable(field_name):
                condition |= Q(**{f"{field_name}__isnull": True})

            queryset = queryset.filter(condition)

        return queryset

    @classmethod
    def is_nullable(cls, field_name: str) -> bool:
        relation_name = field_name.removesuffix("_id")

        try:
            return cls.model._meta.get_field(relation_name).null
        except Exception:
            return False


@register_lookup
class CompanyLookup(BaseLookup):
    name = "companies"
    model = Company
    search_fields = ["code", "name"]
    ordering = ["code"]
    data_scope = COMPANY_SCOPE
    data_scope_allow_null = SCOPE_ALLOW_NULL

    @classmethod
    def serialize(cls, instance):
        """
        Ikut mengirim nomor pegawai berikutnya milik company ini.

        Dipakai `autofill` pada field Company di form Employee: begitu
        companynya dipilih, kolom Employee Number langsung
        memperlihatkan nomor yang akan terbit (`KW260007`) alih-alih
        kotak kosong. Pola yang sama dengan `RosterCrewLookup` yang
        mengirim `work_schedule` supaya autofill-nya ada isinya.

        Angkanya **tebakan** — lihat `EmployeeNumberService.preview()`.
        Yang benar-benar terbit dialokasikan server saat Simpan.
        """
        from apps.hr.api.employee.services.employee_number_service import (
            EmployeeNumberService,
        )

        data = super().serialize(instance)

        data["next_employee_number"] = EmployeeNumberService.preview(
            instance,
        )

        return data


@register_lookup
class BranchLookup(OrganizationScopedLookup):
    name = "branches"
    model = Branch
    search_fields = ["code", "name"]
    filter_fields = ["company_id"]
    ordering = ["code"]
    data_scope = BRANCH_SCOPE


@register_lookup
class LocationLookup(OrganizationScopedLookup):
    """
    Dropdown lokasi kerja.

    **Namanya diberi pembeda company kalau memang ambigu.** Location
    unik per company, jadi satu gedung yang ditempati dua badan usaha
    berdiri sebagai dua baris — di tenant peragaan, "Jakarta Head
    Office" milik MNI dan milik MMR. Sebelum ini keduanya tampil
    dengan tulisan yang sama persis di dropdown: yang memilih tidak
    punya cara tahu mana yang mana, dan angka yang keluar terbaca
    seperti cakupan yang bocor padahal barisnya memang berbeda.

    Yang diubah **hanya label**; `value` tetap `Location.id`.
    """

    name = "locations"
    model = Location
    search_fields = ["code", "name"]
    filter_fields = [
        "company_id",
        "branch_id",
    ]
    ordering = ["code"]
    data_scope = LOCATION_SCOPE

    @classmethod
    def get_queryset(cls):
        # Jumlah company yang memakai nama ini, dihitung **satu
        # subquery untuk seluruh halaman** — bukan satu query per
        # baris di `serialize`.
        #
        # Dihitung atas seluruh master, bukan atas hasil yang sudah
        # tersaring cakupan: kalau tidak, label sebuah lokasi berubah
        # tergantung siapa yang membukanya, dan dua orang yang
        # membicarakan layar yang sama menyebut nama yang berbeda.
        siblings = (
            Location.objects
            .filter(is_deleted=False, name=OuterRef("name"))
            .order_by()
            .values("name")
            .annotate(total=Count("company_id", distinct=True))
            .values("total")[:1]
        )

        return (
            super().get_queryset()
            .select_related("company")
            .annotate(
                name_company_count=Subquery(
                    siblings,
                    output_field=IntegerField(),
                )
            )
        )

    @classmethod
    def apply_scope(cls, queryset, request):
        queryset = super().apply_scope(queryset, request)

        if board.is_board_member(getattr(request, "user", None)):
            queryset = cls.group_by_code(queryset)

        return queryset

    @classmethod
    def group_by_code(cls, queryset):
        """
        Satu baris per **kode** lokasi.

        Untuk direksi, "Jakarta Head Office" adalah satu tempat, bukan
        dua belas baris master. Yang dipilihnya diperluas kembali ke
        seluruh id ber-kode sama oleh
        `board.expand_location_selection`, jadi wakil mana yang terpilih
        di sini tidak menentukan hasilnya — id terkecil dipakai supaya
        daftarnya tetap sama tiap kali dibuka.

        `DISTINCT ON` butuh kolom pertama `order_by` sama dengan kolom
        distinct-nya; `ordering = ["code"]` pada lookup ini memang sudah
        begitu, jadi `apply_ordering` sesudahnya tidak membatalkannya.
        """
        return (
            queryset
            .annotate(is_grouped=Value(True, output_field=BooleanField()))
            .order_by("code", "id")
            .distinct("code")
        )

    @classmethod
    def serialize(cls, instance):
        data = super().serialize(instance)

        # Baris yang sudah mewakili seluruh company **tidak** diberi
        # ekor company: "Jakarta Head Office — MNI" untuk baris yang
        # sebenarnya menjaring MNI *dan* MMR adalah tulisan yang salah,
        # dan salahnya ke arah yang membuat orang mengira sisanya tidak
        # ikut terhitung.
        if getattr(instance, "is_grouped", False):
            return data

        if (getattr(instance, "name_company_count", 0) or 0) > 1:
            code = getattr(instance.company, "code", "")

            if code:
                data["label"] = f"{data['label']} — {code}"

        return data


@register_lookup
class DivisionLookup(OrganizationScopedLookup):
    name = "divisions"
    model = Division
    search_fields = ["code", "name"]
    filter_fields = [
        "company_id",
        "branch_id",
        "location_id",
    ]
    ordering = ["code"]
    data_scope = DIVISION_SCOPE


@register_lookup
class DepartmentLookup(OrganizationScopedLookup):
    name = "departments"
    model = Department
    search_fields = ["code", "name"]
    filter_fields = [
        "company_id",
        "branch_id",
        "location_id",
        "division_id",
    ]
    ordering = ["code"]
    data_scope = DEPARTMENT_SCOPE


@register_lookup
class SectionLookup(OrganizationScopedLookup):
    name = "sections"
    model = Section
    search_fields = ["code", "name"]
    filter_fields = [
        "company_id",
        "branch_id",
        "location_id",
        "division_id",
        "department_id",
    ]
    ordering = ["code"]
    data_scope = SECTION_SCOPE


@register_lookup
class PositionLookup(OrganizationScopedLookup):
    name = "positions"
    model = Position
    search_fields = ["code", "name"]
    filter_fields = [
        "company_id",
        "branch_id",
        "location_id",
        "division_id",
        "department_id",
        "section_id",
    ]
    ordering = ["code"]
    data_scope = POSITION_SCOPE


@register_lookup
class CostCenterLookup(OrganizationScopedLookup):
    name = "cost-centers"
    model = CostCenter
    search_fields = ["code", "name"]
    filter_fields = [
        "company_id",
        "branch_id",
        "location_id",
        "division_id",
        "department_id",
    ]
    ordering = ["code"]
    data_scope = COST_CENTER_SCOPE


@register_lookup
class FacilityLookup(OrganizationScopedLookup):
    """
    Dropdown fasilitas.

    `location_id` ikut di `filter_fields` supaya form yang sudah memilih
    lokasi tidak menawarkan gudang milik site lain — parameter yang
    tidak terdaftar di sini **diabaikan diam-diam**, dan itu penyebab
    klasik dropdown yang "tidak mau tersaring".
    """

    name = "facilities"
    model = Facility
    search_fields = ["code", "name"]
    filter_fields = [
        "company_id",
        "branch_id",
        "location_id",
        "facility_type_id",
    ]
    ordering = ["code"]
    data_scope = FACILITY_SCOPE

