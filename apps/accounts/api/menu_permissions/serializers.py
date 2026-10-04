from rest_framework import serializers

from apps.accounts.models import MenuVisibilityRule


class MenuPermissionSaveSerializer(serializers.Serializer):
    """
    Menerima dua nama untuk daftar menunya: `menus` **dan** `resources`.

    `MTreeBuilder` di frontend adalah komponen generik — dipakai layar
    Menu Permissions maupun Data Permissions — dan ia selalu mengirim
    `resources`. Serializer ini dulu hanya mengenal `menus`, jadi tombol
    Save di layar Menu Permissions **selalu dibalas 400** ("menus: This
    field is required") sejak layarnya dibuat. Tidak kelihatan karena
    penolakannya pun tidak pernah tampil di layar (lihat catatan soal
    `notify` yang tidak pernah dioper).

    `menus` dipertahankan supaya pemanggil skrip dan data uji yang sudah
    ada tidak ikut rusak.
    """

    role = serializers.IntegerField()

    menus = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
    )

    resources = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
    )

    # Syarat pola kerja per menu: `{"<menu_id>": "roster_only"}`.
    #
    # Opsional dan **bukan** pengganti daftar centangnya: menu yang tidak
    # disebut di sini tersimpan tanpa syarat. Pemanggil lama yang cuma
    # mengirim daftar id tetap bekerja seperti sebelumnya.
    rules = serializers.DictField(
        child=serializers.ChoiceField(choices=MenuVisibilityRule.choices),
        required=False,
        allow_empty=True,
    )

    def validate(self, attrs):
        if "menus" not in attrs and "resources" not in attrs:
            raise serializers.ValidationError({
                "menus": "Wajib diisi (atau kirim sebagai 'resources').",
            })

        attrs["menus"] = attrs.get("menus")

        if attrs["menus"] is None:
            attrs["menus"] = attrs.get("resources") or []

        return attrs
