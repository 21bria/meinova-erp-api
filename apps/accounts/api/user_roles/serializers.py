from rest_framework import serializers


class RoleEntryField(serializers.Field):
    """
    Satu entri daftar role: id saja, atau id **berikut** WHERE-nya.

    Dua bentuk, dan yang lama tetap sah — pemanggil yang ada mengirim
    `roles: ["3", "5"]` dan tidak boleh patah. Artinya yang berubah:
    sejak Stage 4H id telanjang berarti "beri rolenya, **tanpa
    kewenangan**", dan penugasannya lahir tertutup sampai WHERE-nya
    ditentukan. Dulu ia diam-diam mewarisi cakupan `Role`.

    Bentuk panjangnya membuat keanggotaan dan WHERE tersimpan dalam
    satu transaksi:

        {"role": 5, "authority_mode": "placement",
         "authority_level": "location"}

    Validasi kombinasinya tidak dikerjakan di sini melainkan di service
    (`validate_authority`), supaya perintah manajemen dan seed — yang
    tidak melewati serializer sama sekali — tunduk pada aturan yang
    persis sama.
    """

    def to_internal_value(self, data):
        if isinstance(data, dict):
            if data.get("role") in (None, ""):
                raise serializers.ValidationError(
                    "Entri role harus menyebut `role`.")

            return data

        if isinstance(data, (int, str)):
            return data

        raise serializers.ValidationError(
            "Entri role harus berupa id atau objek berisi `role`.")

    def to_representation(self, value):
        return value


class UserRoleSaveSerializer(serializers.Serializer):
    user = serializers.IntegerField()

    roles = serializers.ListField(
        child=RoleEntryField(),
        allow_empty=True,
    )


class AuthorityRowSerializer(serializers.Serializer):
    resource_type = serializers.CharField()

    resource_id = serializers.IntegerField(allow_null=True, required=False)


class AssignmentAuthoritySaveSerializer(serializers.Serializer):
    """
    Kewenangan **satu** penugasan.

    Satu penugasan per permintaan, bukan seluruh daftar sekaligus:
    penyimpanan sebagian yang gagal di tengah akan meninggalkan
    sebagian kewenangan tersimpan dan sebagian tidak, dan tidak ada
    yang tahu bagian mana.
    """

    user = serializers.IntegerField()

    role = serializers.IntegerField()

    authority_mode = serializers.CharField()

    authority_level = serializers.CharField(
        allow_blank=True, required=False, default="")

    authorities = AuthorityRowSerializer(many=True, required=False)
