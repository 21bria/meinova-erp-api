from django.urls import path

from .views import (
    UserRoleAuthorityView,
    UserRoleSaveView,
    UserRoleTreeView,
)

urlpatterns = [
    path("tree/", UserRoleTreeView.as_view(), name="user-role-tree"),
    path("save/", UserRoleSaveView.as_view(), name="user-role-save"),
    # Keanggotaan dan kewenangan dua endpoint berbeda: yang pertama
    # menjawab "role apa", yang kedua "sejauh mana". Menyatukannya
    # memaksa keduanya disimpan bersama, padahal urutannya justru
    # berurutan — role dulu, kewenangan kemudian.
    path(
        "authority/",
        UserRoleAuthorityView.as_view(),
        name="user-role-authority",
    ),
]
