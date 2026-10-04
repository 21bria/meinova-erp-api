from rest_framework.routers import DefaultRouter

from .views import (
    AccountingPolicyLineViewSet,
    AccountingPolicyRuleViewSet,
    AccountingPolicyViewSet,
)


router = DefaultRouter()
router.register(
    "accounting-policies",
    AccountingPolicyViewSet,
    basename="finance-accounting-policy",
)
router.register(
    "accounting-policy-rules",
    AccountingPolicyRuleViewSet,
    basename="finance-accounting-policy-rule",
)
router.register(
    "accounting-policy-lines",
    AccountingPolicyLineViewSet,
    basename="finance-accounting-policy-line",
)

urlpatterns = router.urls
