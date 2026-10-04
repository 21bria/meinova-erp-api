from rest_framework.routers import DefaultRouter

from .views import WorkflowDelegationViewSet


router = DefaultRouter()

router.register(
    "delegations",
    WorkflowDelegationViewSet,
    basename="workflow-delegation",
)

urlpatterns = router.urls
