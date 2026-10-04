from django.urls import include, path

urlpatterns = [
    path("lookup/",
         include("apps.accounts.api.lookup.urls")
    ),
    
    path("auth/", include("apps.accounts.api.auth.urls")),
    path("users/", include("apps.accounts.api.users.urls")),
    path("roles/", include("apps.accounts.api.roles.urls")),
    path("permissions/", include("apps.accounts.api.permissions.urls")),
    path("menu-permissions/", include("apps.accounts.api.menu_permissions.urls")),
    path("role-permissions/", include("apps.accounts.api.role_permissions.urls")),
    path("user-roles/", include("apps.accounts.api.user_roles.urls")),
    path("api-keys/", include("apps.accounts.api.api_keys.urls")),

    # Future
    path("sessions/", include("apps.accounts.api.sessions.urls")),
    path("password-policy/", include("apps.accounts.api.password_policy.urls")),
]