from rest_framework.routers import DefaultRouter

from .views import JournalLineViewSet, JournalViewSet


router = DefaultRouter()
router.register("journals", JournalViewSet, basename="finance-journal")
router.register(
    "journal-lines", JournalLineViewSet, basename="finance-journal-line",
)

urlpatterns = router.urls
