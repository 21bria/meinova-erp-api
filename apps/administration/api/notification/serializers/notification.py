from rest_framework import serializers

from apps.administration.models import Notification, NotificationSetting


class NotificationSerializer(serializers.ModelSerializer):
    """
    Notifikasi dibuat sistem, bukan diketik orang.

    Karena itu seluruh isinya read-only kecuali `is_read`. Sebelumnya
    serializer ini `fields = "__all__"` dan viewsetnya menerima POST,
    jadi siapa pun bisa membuat notifikasi untuk dirinya sendiri — tidak
    ada gunanya, dan membuat isi bel tidak lagi bisa dipercaya sebagai
    catatan apa yang sungguh terjadi.
    """

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "type",
            "module",
            "link",
            "object_type",
            "object_id",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "title",
            "message",
            "type",
            "module",
            "link",
            "object_type",
            "object_id",
            "read_at",
            "created_at",
        ]


class NotificationSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationSetting
        fields = [
            "id",
            "in_app_enabled",
            "email_enabled",
            "push_enabled",
            "sms_enabled",
        ]
        read_only_fields = ["id"]
