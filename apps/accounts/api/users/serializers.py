from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.accounts.models import Role
from apps.accounts.services.role_assignment import assign_roles

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    # `write_only` — tidak pernah ikut terkirim dalam response. Tetap
    # perlu ditandai `table: False` di schema: introspeksi model membuat
    # kolomnya sendiri, dan tabel daftar pengguna sempat punya kolom
    # bernama "Password".
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )

    # Role yang dipegang. Inilah hak akses yang sebenarnya berlaku —
    # `groups` bawaan Django ada di model tapi tidak dibaca satu baris
    # kode pun.
    roles = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Role.objects.filter(is_deleted=False),
        required=False,
    )

    role_names = serializers.SerializerMethodField()

    last_login = serializers.DateTimeField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "password",
            "is_active",
            "is_staff",
            "is_superuser",
            "roles",
            "role_names",
            "last_login",
        ]
        read_only_fields = [
            "id",
            "full_name",
            "is_superuser",
            "role_names",
            "last_login",
        ]

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_role_names(self, obj):
        return ", ".join(
            obj.roles.filter(is_deleted=False).values_list("name", flat=True)
        )

    def create(self, validated_data):
        password = validated_data.pop("password", None)

        # M2M tidak bisa dioper ke konstruktor; harus di-set setelah
        # recordnya punya primary key.
        roles = validated_data.pop("roles", None)

        user = User(**validated_data)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save()

        if roles is not None:
            assign_roles(user, roles)

        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        roles = validated_data.pop("roles", None)

        for key, value in validated_data.items():
            setattr(instance, key, value)

        if password:
            instance.set_password(password)

        instance.save()

        if roles is not None:
            assign_roles(instance, roles)

        return instance