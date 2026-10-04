from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.helpcenter.api.article.views import HelpArticleViewSet
from apps.helpcenter.api.category.views import HelpCategoryViewSet
from apps.helpcenter.api.portal.views import (
    HelpArticleDetailView,
    HelpContextualView,
    HelpFeedbackView,
    HelpPortalView,
    HelpSearchView,
)

router = DefaultRouter()
router.register("categories", HelpCategoryViewSet, basename="help-category")
router.register("articles", HelpArticleViewSet, basename="help-article")

urlpatterns = [
    # Rute spesifik selalu di atas router — kalau tidak, `articles/`
    # milik portal ditelan router viewset yang mendaftar prefix sama.
    path(
        "portal/",
        HelpPortalView.as_view(),
        name="help-portal",
    ),
    path(
        "portal/search/",
        HelpSearchView.as_view(),
        name="help-portal-search",
    ),
    path(
        "portal/contextual/",
        HelpContextualView.as_view(),
        name="help-portal-contextual",
    ),
    path(
        "portal/articles/<slug:slug>/",
        HelpArticleDetailView.as_view(),
        name="help-portal-article",
    ),
    path(
        "portal/articles/<slug:slug>/feedback/",
        HelpFeedbackView.as_view(),
        name="help-portal-feedback",
    ),

    path("lookup/", include("apps.helpcenter.api.lookup.urls")),

    path("", include(router.urls)),
]
