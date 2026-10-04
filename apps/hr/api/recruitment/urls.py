from rest_framework.routers import DefaultRouter

from .views import (
    CandidateInterviewViewSet,
    CandidateViewSet,
    JobVacancyViewSet,
)


router = DefaultRouter()

router.register(
    "job-vacancies",
    JobVacancyViewSet,
    basename="job-vacancy",
)

router.register(
    "candidates",
    CandidateViewSet,
    basename="candidate",
)

router.register(
    "candidate-interviews",
    CandidateInterviewViewSet,
    basename="candidate-interview",
)

urlpatterns = router.urls
