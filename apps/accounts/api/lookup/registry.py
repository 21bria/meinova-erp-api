from django.contrib.auth import get_user_model

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
        "email",
        "first_name",
        "last_name",
    ]

    ordering = [
        "email",
    ]