from django.db import models
from apps.core.models.base import BaseModel

class Company(BaseModel):
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )

    company_type = models.ForeignKey(
        "administration.CompanyType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)

    legal_name = models.CharField(max_length=255, blank=True)
    tax_number = models.CharField(max_length=100, blank=True)

    country = models.ForeignKey(
        "administration.Country",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )
    province = models.ForeignKey(
        "administration.Province",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )
    city = models.ForeignKey(
        "administration.City",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )

    address = models.TextField(blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    class Meta:
        db_table = "master_company"
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                name="uniq_core_company_code",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name
    
class Branch(BaseModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="branches",
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)

    country = models.ForeignKey(
        "administration.Country",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branches",
    )
    province = models.ForeignKey(
        "administration.Province",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branches",
    )
    city = models.ForeignKey(
        "administration.City",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branches",
    )

    address = models.TextField(blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)


    class Meta:
        db_table = "master_branch"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="uniq_core_branch_company_code",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Location(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="locations")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="locations")

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)

    location_type = models.ForeignKey(
        "administration.LocationType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="locations",
    )

    country = models.ForeignKey("administration.Country", on_delete=models.SET_NULL, null=True, blank=True, related_name="locations")
    province = models.ForeignKey("administration.Province", on_delete=models.SET_NULL, null=True, blank=True, related_name="locations")
    city = models.ForeignKey("administration.City", on_delete=models.SET_NULL, null=True, blank=True, related_name="locations")

    address = models.TextField(blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "master_location"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_core_location_company_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Division(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="divisions")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="divisions")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="divisions")

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    class Meta:
        db_table = "master_division"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_core_division_company_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Department(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="departments")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="departments")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="departments")
    division = models.ForeignKey(Division, on_delete=models.SET_NULL, null=True, blank=True, related_name="departments")

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    class Meta:
        db_table = "master_department"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_core_department_company_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Section(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sections")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="sections")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="sections")
    division = models.ForeignKey(Division, on_delete=models.SET_NULL, null=True, blank=True, related_name="sections")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="sections")

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    class Meta:
        db_table = "master_section"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_core_section_company_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Position(BaseModel):
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="positions")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL,null=True,blank=True, related_name="positions")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="positions")
    division = models.ForeignKey(Division,on_delete=models.SET_NULL,null=True,blank=True,related_name="positions")
    department = models.ForeignKey(Department,on_delete=models.SET_NULL,  null=True,blank=True,related_name="positions" )
    section = models.ForeignKey(Section,on_delete=models.SET_NULL,null=True,blank=True,related_name="positions")

    job_category = models.ForeignKey("administration.JobCategory",on_delete=models.SET_NULL,null=True,blank=True,related_name="positions")
    job_level = models.ForeignKey("administration.JobLevel",on_delete=models.SET_NULL,null=True,blank=True,related_name="positions")
    reports_to = models.ForeignKey("self", on_delete=models.SET_NULL,null=True,blank=True, related_name="sub_positions")
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    headcount = models.PositiveSmallIntegerField(default=1)
    description = models.TextField(blank=True)

    is_manager = models.BooleanField(default=False)

    class Meta:
        db_table = "master_position"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="uniq_core_position_company_code",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

   
class CostCenter(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="cost_centers")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="cost_centers")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, related_name="cost_centers")
    division = models.ForeignKey(Division, on_delete=models.SET_NULL, null=True, blank=True, related_name="cost_centers")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="cost_centers")

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    class Meta:
        db_table = "master_cost_center"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_core_cost_center_company_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Facility(BaseModel):
    """
    Bangunan atau sarana di dalam sebuah lokasi kerja.

    **Bukan tempat penempatan pegawai.** Workshop, gudang, jetty, dan
    camp di Gebe semuanya berdiri di Location "Gebe" yang sama; yang
    dipakai absensi, kalender libur, dan cakupan data tetap Location.
    Sebelum ini semuanya dijejalkan sebagai `LocationType`, dan
    akibatnya satu site harus dipecah jadi belasan Location — sehingga
    "berapa orang di Gebe" tidak lagi bisa dijawab satu angka.

    Kodenya unik **per company**, sama seperti seluruh master
    organisasi lain di sini: dua perusahaan boleh sama-sama punya
    fasilitas berkode `WS-01`.
    """

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="facilities",
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="facilities",
    )

    # Wajib, tidak seperti induk lain di master ini: fasilitas tanpa
    # lokasi tidak punya arti — pertanyaannya selalu "workshop di mana".
    location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="facilities",
    )

    # PROTECT, bukan SET_NULL: jenis fasilitas yang masih dipakai tidak
    # boleh hilang diam-diam dan menyisakan baris tanpa jenis.
    facility_type = models.ForeignKey(
        "administration.FacilityType",
        on_delete=models.PROTECT,
        related_name="facilities",
    )

    code = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    class Meta:
        db_table = "master_facility"
        ordering = ["company", "location", "code"]
        constraints = [
            # Dikondisikan ke `is_deleted` — tanpa itu kode fasilitas
            # yang sudah dihapus mengunci nilainya selamanya. Lihat
            # aturan di CLAUDE.md; `Location` sendiri belum dikonversi.
            models.UniqueConstraint(
                fields=["company", "code"],
                condition=models.Q(is_deleted=False),
                name="uniq_active_administration_facility_company_code",
            ),
        ]
        indexes = [
            models.Index(
                fields=["company", "location"],
                name="idx_facility_company_location",
            ),
            models.Index(
                fields=["facility_type", "is_active"],
                name="idx_facility_type_active",
            ),
        ]
        verbose_name = "Facility"
        verbose_name_plural = "Facilities"

    def __str__(self):
        return f"{self.code} — {self.name}"

    def clean(self):
        """
        Lapisan ketiga, sama pola dengan `OrganizationAssignment.clean()`.

        Dropdown yang tersaring dan resolver import bisa dilewati dengan
        menembak API langsung; ini yang menolak fasilitas Gebe yang
        dititipkan ke company lain.
        """
        super().clean()

        from django.core.exceptions import ValidationError

        errors = {}

        if self.location_id and self.company_id:
            if self.location.company_id != self.company_id:
                errors["location"] = (
                    "Lokasi ini bukan milik company yang dipilih."
                )

        if self.branch_id and self.company_id:
            if self.branch.company_id != self.company_id:
                errors["branch"] = (
                    "Branch ini bukan milik company yang dipilih."
                )

        # Branch kosong di Location berarti "berlaku umum", jadi hanya
        # ketidakcocokan yang benar-benar bertentangan yang ditolak.
        if self.branch_id and self.location_id:
            location_branch = self.location.branch_id

            if location_branch and location_branch != self.branch_id:
                errors["branch"] = (
                    "Branch ini tidak cocok dengan branch milik lokasinya."
                )

        if errors:
            raise ValidationError(errors)
