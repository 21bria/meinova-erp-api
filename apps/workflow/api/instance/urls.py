from rest_framework.routers import DefaultRouter

from .views import WorkflowInstanceViewSet


router = DefaultRouter()

router.register(
    "instances",
    WorkflowInstanceViewSet,
    basename="workflow-instance",
)

urlpatterns = router.urls
