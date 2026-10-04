from rest_framework.routers import DefaultRouter

from .views import TrainingParticipantViewSet, TrainingProgramViewSet


router = DefaultRouter()

router.register(
    "training-programs",
    TrainingProgramViewSet,
    basename="training-program",
)

router.register(
    "training-participants",
    TrainingParticipantViewSet,
    basename="training-participant",
)

urlpatterns = router.urls
