"""
Panggung bersama untuk test Visitor Request (BT-1).

BT-1 adalah **test pelindung** perilaku Visitor. Sejak BT-2A Visitor
dipersempit jadi eksternal saja: tamu internal tidak bisa lagi dibuat,
disunting, atau diajukan. Dokumen internal **lama** tetap harus terbaca
dan bisa menyelesaikan siklusnya — `make_legacy_internal` membuatnya
seperti yang ditinggalkan riwayat, melewati service hari ini.
Kontraknya: `docs/claude/hr/business-trip.md` §15, §24, §31.

Sebelum berkas ini ada, modul Visitor tidak punya satu pun test backend.

Dua lokasi (kantor pusat dan site) karena separuh perilaku yang dikunci
— cakupan layar pos jaga, lokasi bawaan dari pemohon — hanya bisa
salah kalau ada lebih dari satu tempat.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model

from apps.accounts.models import Role
from apps.administration.models import Company, Location
from apps.administration.models.references.visitor import (
    VisitPurpose,
    VisitType,
)
from apps.administration.seeds.numbering import seed_numbering
from apps.core.testing.tenant import ReusableTenantTestCase
from apps.hr.api.visitor.services import (
    ExternalVisitorService,
    VisitorRequestService,
)
from apps.hr.models import (
    Employee,
    OrganizationAssignment,
    VisitorType,
)
from apps.workflow.seeds import workflows as workflow_seed


JOIN_DATE = date(2024, 1, 1)


class VisitorTestCase(ReusableTenantTestCase):
    reusable_schema_name = "fast_visitor"

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "visitor-bt1"
        tenant.name = "Visitor BT-1"

    @classmethod
    def build_baseline(cls):
        # Tanpa deret nomor `document_number` terbit kosong — sah, tapi
        # membuat assertion soal nomor tidak menguji apa pun.
        seed_numbering()

        cls.company, _ = Company.objects.get_or_create(
            code="VST",
            is_deleted=False,
            defaults={"name": "Visitor Co"},
        )

        cls.head_office, _ = Location.objects.get_or_create(
            code="VST-HO",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Jakarta HO"},
        )

        cls.site, _ = Location.objects.get_or_create(
            code="VST-SITE",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Kendari Site"},
        )

        cls.purpose, _ = VisitPurpose.objects.get_or_create(
            code="VST-MEETING",
            is_deleted=False,
            defaults={"name": "Business Meeting"},
        )

        cls.visit_type, _ = VisitType.objects.get_or_create(
            code="VST-OFFICIAL",
            is_deleted=False,
            defaults={"name": "Official"},
        )

        # Alur dari seed sungguhan (`HR-VISITOR-REQUEST`), bukan rantai
        # yang disusun tangan: rantai salinan tetap hijau sesudah seed-nya
        # berubah. `update_or_create`, aman diulang.
        workflow_seed.seed()

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(
        cls,
        *,
        location=None,
        reports_to=None,
        roles=None,
        with_user: bool = True,
    ) -> Employee:
        User = get_user_model()

        cls._counter += 1
        n = cls._counter

        user = None

        if with_user:
            username = f"vst.user{n}"

            user = User.objects.create_user(
                username=username,
                email=f"{username}@example.test",
                password="Test-Only#Pw1",
                first_name="Visitor",
                last_name=f"Employee {n}",
            )

            if roles:
                user.roles.set(
                    Role.objects.filter(code__in=roles, is_deleted=False),
                )

        employee = Employee.objects.create(
            employee_number=f"VST{n:04d}",
            first_name="Visitor",
            last_name=f"Employee {n}",
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location or cls.head_office,
            reports_to=reports_to,
            organization_effective_date=JOIN_DATE,
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_guest(cls, **extra):
        cls._counter += 1

        data = {
            "full_name": f"Guest {cls._counter}",
            "identity_number": f"317100000000{cls._counter:04d}",
            "organization_name": "PT Vendor",
        }
        data.update(extra)

        return ExternalVisitorService.create(data=data)

    @classmethod
    def make_request(
        cls,
        *,
        requester,
        host=None,
        visitor_type=VisitorType.EXTERNAL,
        guest=None,
        employee=None,
        start=None,
        end=None,
        user=None,
        **extra,
    ):
        from django.utils import timezone

        today = timezone.localdate()

        data = {
            "requester": requester,
            "host_employee": host or requester,
            "visitor_type": visitor_type,
            "visit_purpose": cls.purpose,
            "visit_type": cls.visit_type,
            "visit_start_date": start or today,
            "visit_end_date": end or start or today,
        }

        if visitor_type == VisitorType.EXTERNAL:
            data["external_visitor"] = guest or cls.make_guest()
        else:
            data["employee"] = employee

        data.update(extra)

        return VisitorRequestService.create(data=data, user=user)

    @classmethod
    def make_legacy_internal(cls, *, requester, employee, status=None, **extra):
        """
        Dokumen tamu internal **lama** — dibuat sebelum BT-2A menutupnya.

        Service hari ini menolak `internal`, jadi barisnya dibuat sebagai
        tamu luar lalu dialihkan langsung di database, persis bentuk
        yang ditinggalkan riwayat. `full_clean()` memastikan barisnya
        tetap sah menurut model.
        """
        from apps.hr.models import VisitorRequest, VisitorRequestStatus

        request = cls.make_request(requester=requester, **extra)

        VisitorRequest.objects.filter(pk=request.pk).update(
            visitor_type=VisitorType.INTERNAL,
            employee=employee,
            external_visitor=None,
            status=status or VisitorRequestStatus.DRAFT,
        )

        request.refresh_from_db()
        request.full_clean()

        return request
