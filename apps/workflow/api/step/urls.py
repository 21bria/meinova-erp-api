from rest_framework.routers import DefaultRouter

from .views import WorkflowStepViewSet


router = DefaultRouter()

router.register(
    "steps",
    WorkflowStepViewSet,
    basename="workflow-step",
)

urlpatterns = router.urls
