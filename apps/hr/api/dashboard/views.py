from apps.framework.views.dashboard import BaseDashboardAPIView

from .schema import HR_DASHBOARD_SCHEMA
from .services import HRDashboardService


class HRDashboardAPIView(BaseDashboardAPIView):
    """
    Nama resolver harus persis `resolve_<key widget>` — itu satu-satunya
    penghubung antara schema dan perhitungannya. Widget yang ada di
    schema tapi resolvernya belum ditulis akan gagal berisik, bukan
    tampil kosong.
    """

    framework_module = "hr/dashboard"
    schema = HR_DASHBOARD_SCHEMA

    service_class = HRDashboardService

    # ------------------------------------------------------------------
    # Kartu KPI
    # ------------------------------------------------------------------

    def resolve_total_employees(self, *, context, widget):
        return self.service_class.total_employees(context)

    def resolve_attendance_rate(self, *, context, widget):
        return self.service_class.attendance_rate_widget(context)

    def resolve_active_leaves(self, *, context, widget):
        return self.service_class.active_leaves(context)

    def resolve_overtime_hours(self, *, context, widget):
        return self.service_class.overtime_hours(context)

    def resolve_turnover_rate(self, *, context, widget):
        return self.service_class.turnover_rate(context)

    def resolve_open_vacancies(self, *, context, widget):
        return self.service_class.open_vacancies(context)

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    def resolve_attendance_trend(self, *, context, widget):
        return self.service_class.attendance_trend(context)

    def resolve_employees_by_unit(self, *, context, widget):
        return self.service_class.employees_by_unit(context)

    def resolve_employees_by_education(self, *, context, widget):
        return self.service_class.employees_by_education(context)

    # ------------------------------------------------------------------
    # Daftar
    # ------------------------------------------------------------------

    def resolve_leave_recap(self, *, context, widget):
        return self.service_class.leave_recap(context)

    def resolve_recent_leaves(self, *, context, widget):
        return self.service_class.recent_leaves(
            context,
            limit=widget.get("limit") or 5,
        )

    def resolve_upcoming_trainings(self, *, context, widget):
        return self.service_class.upcoming_trainings(
            context,
            limit=widget.get("limit") or 5,
        )

    def resolve_employment_reminders(self, *, context, widget):
        from .reminders import EmployeeReminderService

        return EmployeeReminderService.collect(
            context,
            limit=widget.get("limit") or 8,
        )
