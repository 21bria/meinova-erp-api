from django.contrib.auth import get_user_model

from apps.accounts.models import Role
from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

User = get_user_model()


@register_lookup
class UserLookup(BaseLookup):
    name = "users"
    model = User

    value_field = "id"
    label_field = "email"

    search_fields = [
        # `username` ikut karena tidak semua akun memakai email sebagai
        # username — mencari "demo.hradmin" tidak boleh nihil hanya
        # karena label dropdown-nya kebetulan menampilkan email.
        "username",
        "email",
        "first_name",
        "last_name",
    ]

    ordering = [
        "email",
    ]

@register_lookup
class RoleLookup(BaseLookup):
    """
    Dropdown Role. Dipakai step approval bertipe Role Holder — sebelum
    ini Role tidak punya endpoint lookup sama sekali, jadi alur yang
    menunjuk role harus diisi lewat shell.
    """

    name = "roles"
    model = Role

    value_field = "id"
    label_field = "name"

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "name",
    ]
