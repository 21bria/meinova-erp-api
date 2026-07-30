from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.organization.views import (
    CompanyViewSet,
    SiteViewSet,
    BranchViewSet,
    DepartmentViewSet,
    DivisionViewSet,
    SectionViewSet,
    PositionViewSet,
    CostCenterViewSet,
)

router = DefaultRouter()
router.register("company", CompanyViewSet, basename="organization-company")
router.register("site", SiteViewSet, basename="organization-site")
router.register("branch", BranchViewSet, basename="organization-branch")
router.register("department", DepartmentViewSet, basename="organization-department")
router.register("division", DivisionViewSet, basename="organization-divison")
router.register("section", SectionViewSet, basename="organization-section")
router.register("position", PositionViewSet, basename="organization-position")
router.register("cost-center", CostCenterViewSet, basename="organization-cost-center")

urlpatterns = [
    path("lookup/",include("apps.administration.api.organization.lookup.urls")),
    path("", include(router.urls)),

]