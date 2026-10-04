from rest_framework.routers import DefaultRouter

from .views import WorkflowDefinitionViewSet


router = DefaultRouter()

router.register(
    "definitions",
    WorkflowDefinitionViewSet,
    basename="workflow-definition",
)

urlpatterns = router.urls
