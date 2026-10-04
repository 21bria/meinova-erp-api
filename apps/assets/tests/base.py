"""
Panggung bersama test Asset Management.

`ReusableTenantTestCase` dengan schema `fast_assets` (lihat
`docs/claude/testing.md`). Pondasi — dua company, lokasi, fasilitas,
deret nomor — dibuat idempoten di `build_baseline`; kategori, aset, dan
user dibuat per test dengan kode dari penghitung.

Dua company karena separuh aturan register — lokasi/fasilitas lintas
company, serial unik **per company** — hanya bisa salah kalau ada lebih
dari satu.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import assign_roles
from datetime import date

from apps.administration.models import Company, Department, Facility, Location
from apps.administration.models.references.organization import FacilityType
from apps.administration.seeds.numbering import seed_numbering
from apps.assets.models import CustodyType, ReturnReason, TransferReason
from apps.assets.services import (
    AssetAssignmentService,
    AssetCategoryService,
    AssetReturnService,
    AssetService,
    AssetTransferService,
)
from apps.hr.models import Employee, OrganizationAssignment
from apps.core.testing.tenant import ReusableTenantTestCase


class AssetsTestCase(ReusableTenantTestCase):
    reusable_schema_name = "fast_assets"

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "assets-test"
        tenant.name = "Assets Test"

    @classmethod
    def build_baseline(cls):
        # Tanpa deret AST, `AssetService.create()` menolak — sengaja,
        # karena kode aset adalah identitas.
        seed_numbering()

        cls.company_a, _ = Company.objects.get_or_create(
            code="AST-CO-A",
            is_deleted=False,
            defaults={"name": "Asset Co A"},
        )
        cls.company_b, _ = Company.objects.get_or_create(
            code="AST-CO-B",
            is_deleted=False,
            defaults={"name": "Asset Co B"},
        )

        cls.loc_a1 = cls._location(cls.company_a, "AST-A-HO", "A Head Office")
        cls.loc_a2 = cls._location(cls.company_a, "AST-A-SITE", "A Site")
        cls.loc_b1 = cls._location(cls.company_b, "AST-B-HO", "B Head Office")

        cls.facility_type, _ = FacilityType.objects.get_or_create(
            code="AST-STORE",
            is_deleted=False,
            defaults={"name": "Store"},
        )

        cls.fac_a1 = cls._facility(cls.company_a, cls.loc_a1, "AST-A-HO-WH")
        cls.fac_a2 = cls._facility(cls.company_a, cls.loc_a2, "AST-A-SITE-WH")

        cls.dept_a_mining = cls._department(cls.company_a, "AST-A-MINING", "Mining")
        cls.dept_a_it = cls._department(cls.company_a, "AST-A-IT", "IT")
        cls.dept_b_fin = cls._department(cls.company_b, "AST-B-FIN", "Finance")

    @classmethod
    def _department(cls, company, code, name):
        department, _ = Department.objects.get_or_create(
            company=company,
            code=code,
            defaults={"name": name},
        )

        return department

    @classmethod
    def _location(cls, company, code, name):
        location, _ = Location.objects.get_or_create(
            code=code,
            is_deleted=False,
            defaults={"company": company, "name": name},
        )

        return location

    @classmethod
    def _facility(cls, company, location, code):
        facility, _ = Facility.objects.get_or_create(
            company=company,
            code=code,
            is_deleted=False,
            defaults={
                "location": location,
                "facility_type": cls.facility_type,
                "name": code,
            },
        )

        return facility

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def next_code(cls, prefix: str = "CAT") -> str:
        cls._counter += 1

        return f"{prefix}{cls._counter:04d}"

    @classmethod
    def make_category(cls, *, requires_serial_number=False, **extra):
        return AssetCategoryService.create(
            data={
                "code": cls.next_code("CAT"),
                "name": "Category",
                "requires_serial_number": requires_serial_number,
                **extra,
            },
        )

    @classmethod
    def make_asset(cls, *, company=None, location=None, category=None, **extra):
        company = company or cls.company_a

        if location is None:
            location = cls.loc_a1 if company == cls.company_a else cls.loc_b1

        return AssetService.create(
            data={
                "company": company,
                "location": location,
                "category": category or cls.make_category(),
                "name": "Laptop",
                **extra,
            },
        )

    @classmethod
    def make_active_asset(cls, *, category=None, **extra):
        """Aset ACTIVE dengan custody STORAGE — siap diserahkan."""
        return AssetService.activate(
            asset=cls.make_asset(category=category, **extra),
        )

    @classmethod
    def make_employee(
        cls,
        *,
        company=None,
        location=None,
        department=None,
        placed: bool = True,
        user=None,
    ) -> Employee:
        """
        Pegawai dengan `OrganizationAssignment` aktif (atau tanpa, bila
        `placed=False`). Penempatan adalah satu-satunya sumber company/
        lokasi/department pegawai — tidak ada kolom itu di `Employee`.
        """
        cls._counter += 1
        n = cls._counter

        employee = Employee.objects.create(
            employee_number=f"ASTEMP{n:05d}",
            first_name="Asset",
            last_name=f"Holder {n}",
            user=user,
        )

        if placed:
            company = company or cls.company_a

            OrganizationAssignment.objects.create(
                employee=employee,
                company=company,
                location=location or (
                    cls.loc_a1 if company == cls.company_a else cls.loc_b1
                ),
                department=department,
                organization_effective_date=date(2024, 1, 1),
            )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def hand_over(cls, asset, employee=None, *, location=None, **extra):
        """Aset STORAGE → pegawai lewat Assignment yang selesai."""
        assignment = AssetAssignmentService.create(data={
            "asset": asset,
            "target_custody_type": CustodyType.EMPLOYEE,
            "employee": employee or cls.make_employee(),
            "location": location or cls.loc_a1,
            **extra,
        })
        AssetAssignmentService.submit(assignment=assignment)
        AssetAssignmentService.complete(assignment=assignment)

        asset.refresh_from_db()

        return asset

    @classmethod
    def hand_to_department(cls, asset, department, *, pic=None, location=None):
        """Aset STORAGE → unit organisasi (+ PIC) lewat Assignment."""
        assignment = AssetAssignmentService.create(data={
            "asset": asset,
            "target_custody_type": CustodyType.ORGANIZATION,
            "department": department,
            "pic_employee": pic,
            "location": location or cls.loc_a1,
        })
        AssetAssignmentService.submit(assignment=assignment)
        AssetAssignmentService.complete(assignment=assignment)

        asset.refresh_from_db()

        return asset

    @classmethod
    def make_return(cls, asset, *, destination=None, user=None, **extra):
        data = {
            "asset": asset,
            "destination_location": destination or cls.loc_a1,
            "reason": ReturnReason.END_OF_USE,
            **extra,
        }

        return AssetReturnService.create(data=data, user=user)

    @classmethod
    def make_transfer(
        cls,
        asset,
        *,
        to=CustodyType.EMPLOYEE,
        location=None,
        user=None,
        **extra,
    ):
        """Draft Transfer. Kolom tujuan memakai nama dokumen (`target_*`)."""
        data = {
            "asset": asset,
            "target_custody_type": to,
            "target_location": location or cls.loc_a1,
            "reason": TransferReason.REASSIGNMENT,
            **extra,
        }

        return AssetTransferService.create(data=data, user=user)

    @classmethod
    def make_workflow(
        cls,
        *,
        approver,
        company=None,
        document_type="asset_assignment",
    ):
        """Alur satu meja (pengguna tertentu) untuk satu jenis dokumen aset."""
        from apps.workflow.models import (
            ApproverType,
            WorkflowDefinition,
            WorkflowStatus,
            WorkflowStep,
        )

        cls._counter += 1

        definition = WorkflowDefinition.objects.create(
            code=f"AST-WF-{cls._counter}",
            name=f"{document_type} test flow",
            module="assets",
            document_type=document_type,
            company=company or cls.company_a,
            status=WorkflowStatus.ACTIVE,
        )

        WorkflowStep.objects.create(
            definition=definition,
            sequence=1,
            name="Asset Admin",
            approver_type=ApproverType.USER,
            approver_user=approver,
        )

        return definition

    @classmethod
    def make_user(cls, *, permissions=(), authorities=None):
        """
        User dengan satu role berisi `permissions` (codename app assets).

        `authorities=None` → kewenangan UNRESTRICTED; daftar
        `[("location", pk), …]` → EXPLICIT. `.roles.add()` saja tidak
        memberi akses baris — kewenangannya dinyatakan saat penugasan.
        """
        cls._counter += 1
        n = cls._counter

        user = get_user_model().objects.create_user(
            username=f"asset.user{n}",
            email=f"asset.user{n}@example.test",
            password="Test-Only#Pw1",
        )

        if permissions:
            role = Role.objects.create(
                code=f"AST-ROLE-{n}",
                name=f"Asset role {n}",
            )

            role.permissions.set(
                Permission.objects.filter(
                    content_type__app_label="assets",
                    codename__in=permissions,
                ),
            )

            if authorities is None:
                entry = {
                    "role": role.pk,
                    "authority_mode": AuthorityMode.UNRESTRICTED,
                }
            else:
                entry = {
                    "role": role.pk,
                    "authority_mode": AuthorityMode.EXPLICIT,
                    "authorities": [
                        {"resource_type": kind, "resource_id": pk}
                        for kind, pk in authorities
                    ],
                }

            assign_roles(user, [entry])

        return user
