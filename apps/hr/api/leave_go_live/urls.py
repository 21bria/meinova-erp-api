from rest_framework.routers import DefaultRouter

from .views import LeaveGoLiveViewSet


router = DefaultRouter()

router.register(
    "leave-go-live",
    LeaveGoLiveViewSet,
    basename="leave-go-live",
)

urlpatterns = router.urls
