from rest_framework.routers import DefaultRouter

from .views import WorkflowApprovalViewSet


router = DefaultRouter()

router.register(
    "approvals",
    WorkflowApprovalViewSet,
    basename="workflow-approval",
)

urlpatterns = router.urls
