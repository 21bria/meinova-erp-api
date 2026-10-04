from django.db.models import Q
from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import (
    CalendarScope,
    Holiday,
    RosterCrew,
    WorkCalendar,
)


# Lookup `fiscal-years` dan `posting-periods` pindah ke Finance
# (`apps/finance/api/lookup/registry.py`). Nama lookup bersifat
# global di registry ini, jadi keduanya tidak boleh berdiri di dua
# tempat sekaligus — yang terdaftar belakangan menang, diam-diam.

@register_lookup
class HolidayLookup(BaseLookup):
    name = "holidays"
    model = Holiday

    search_fields = [
        "code",
        "name",
    ]

    filter_fields = [
        "scope",
        "company_id",
        "location_id",
        "date",
        "is_national",
        "is_recurring",
    ]

    ordering = [
        "date",
    ]


@register_lookup
class WorkCalendarLookup(BaseLookup):
    name = "work-calendars"
    model = WorkCalendar

    search_fields = [
        "code",
        "name",
    ]

    filter_fields = [
        "scope",
        "company_id",
    ]

    ordering = [
        "-is_default",
        "name",
    ]

    @classmethod
    def apply_filters(cls, queryset, params):
        """
        Tanda tangannya `(queryset, params)`, bukan `(queryset, request)`
        — `BaseLookupView` mengoper `request.query_params`. Versi
        sebelumnya memanggil `request.query_params.get(...)` di sini,
        sehingga endpoint ini selalu membalas 500.
        """
        company_id = params.get("company_id")
        location_id = params.get("location_id")

        if not company_id:
            return queryset

        # Yang ditawarkan: kalender company-nya sendiri **plus yang
        # GLOBAL**.
        #
        # Kalender GLOBAL punya `company IS NULL`, jadi penyaring
        # `company_id=` yang lugas justru membuangnya — dan dropdown
        # override pegawai tidak akan pernah menawarkan `HO-STANDARD`,
        # kalender yang paling banyak dipakai. Kegagalannya diam: yang
        # memilihnya cuma melihat daftar yang lebih pendek, tanpa satu
        # pun tanda bahwa ada yang disembunyikan.
        condition = (
            Q(scope=CalendarScope.GLOBAL)
            | Q(scope=CalendarScope.COMPANY, company_id=company_id)
        )

        if location_id:
            condition |= Q(
                scope=CalendarScope.LOCATION,
                company_id=company_id,
                location_id=location_id,
            )

        return queryset.filter(condition)


@register_lookup
class RosterCrewLookup(BaseLookup):
    name = "roster-crews"
    model = RosterCrew

    # Pola kerjanya ikut dibaca — lihat `serialize` di bawah. Tanpa
    # select_related, satu halaman dropdown menembak satu query per
    # baris hanya untuk mengambil nama polanya.
    queryset = RosterCrew.objects.select_related("work_schedule")

    search_fields = [
        "code",
        "name",
    ]

    filter_fields = [
        "company_id",
        "location_id",
        "work_schedule_id",
    ]

    ordering = [
        "code",
    ]

    @classmethod
    def serialize(cls, instance):
        """
        Ikut membawa pola kerja milik crew.

        Dipakai `autofill` pada field Roster Crew di form Employee:
        memilih crew langsung mengisi Work Schedule. Dua field itu
        wajib sepakat — `EmploymentAssignment.clean()` menolak kalau
        berbeda — jadi membiarkan pengguna menebak polanya hanya
        menghasilkan penolakan saat Simpan, jauh dari tempat kesalahan
        itu dibuat.
        """
        return {
            "value": instance.pk,
            "label": f"{instance.code} — {instance.name}",
            "work_schedule": instance.work_schedule_id,
            "work_schedule_name": (
                instance.work_schedule.name
                if instance.work_schedule_id
                else None
            ),
        }
