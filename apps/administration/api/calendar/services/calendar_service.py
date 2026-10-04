from apps.core.services.master import BaseMasterService

from apps.administration.models import (
    Holiday,
    RosterCrew,
    WorkCalendar,
)


# `FiscalYearService` dan `PostingPeriodService` pindah ke Finance.


class HolidayService:
    @staticmethod
    def list():
        return (
            Holiday.objects
            .select_related("company", "location")
            # `applies_to` dan `selected_companies` membaca daftar
            # perusahaan tiap baris. Tanpa prefetch, satu halaman berisi
            # 50 hari libur bercakupan SELECTED_COMPANIES menjadi 50
            # query tambahan yang tidak terlihat di serializer.
            .prefetch_related("companies")
            .filter(is_deleted=False)
            .order_by("date")
        )


class WorkCalendarService:
    @staticmethod
    def list():
        return (
            WorkCalendar.objects
            .select_related("company", "location")
            .filter(is_deleted=False)
            # GLOBAL di atas, lalu COMPANY, lalu LOCATION — urutan yang
            # sama dengan presedennya.
            .order_by("scope", "company__name", "name")
        )

class RosterCrewService(BaseMasterService):
    model = RosterCrew

    @staticmethod
    def list():
        return (
            RosterCrew.objects
            .select_related("company", "location", "work_schedule")
            .filter(is_deleted=False)
            .order_by("company__name", "code")
        )
