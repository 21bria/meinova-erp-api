from apps.framework.views.dashboard import BaseDashboardAPIView

from .schema import ADMINISTRATION_DASHBOARD_SCHEMA
from .services import AdministrationDashboardService


class AdministrationDashboardAPIView(BaseDashboardAPIView):
    """
    Nama resolver harus persis `resolve_<key widget>` — itu satu-satunya
    penghubung antara schema dan perhitungannya. Widget yang ada di
    schema tapi resolvernya belum ditulis gagal berisik, bukan tampil
    kosong.
    """

    framework_module = "administration/dashboard"
    schema = ADMINISTRATION_DASHBOARD_SCHEMA

    service_class = AdministrationDashboardService

    # ------------------------------------------------------------------
    # Kartu KPI
    # ------------------------------------------------------------------

    def resolve_total_companies(self, *, context, widget):
        return self.service_class.total_companies(context)

    def resolve_total_branches(self, *, context, widget):
        return self.service_class.total_branches(context)

    def resolve_total_locations(self, *, context, widget):
        return self.service_class.total_locations(context)

    def resolve_active_users(self, *, context, widget):
        return self.service_class.active_users(context)

    def resolve_audit_events(self, *, context, widget):
        return self.service_class.audit_events(context)

    def resolve_configuration_issues(self, *, context, widget):
        return self.service_class.configuration_issues(context)

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    def resolve_activity_trend(self, *, context, widget):
        return self.service_class.activity_trend(context)

    def resolve_activity_by_module(self, *, context, widget):
        return self.service_class.activity_by_module(context)

    def resolve_organization_structure(self, *, context, widget):
        return self.service_class.organization_structure(context)

    # ------------------------------------------------------------------
    # Daftar
    # ------------------------------------------------------------------

    def resolve_configuration_health(self, *, context, widget):
        return self.service_class.configuration_health(context)

    def resolve_upcoming_holidays(self, *, context, widget):
        return self.service_class.upcoming_holidays(
            context,
            limit=widget.get("limit") or 6,
        )

    def resolve_recent_audit(self, *, context, widget):
        return self.service_class.recent_audit(
            context,
            limit=widget.get("limit") or 8,
        )
