from rest_framework import serializers

from apps.finance.models import Account


class AccountSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )

    # Generator FE memetakan field lookup ke `<field>_name`. Tanpa
    # keduanya, kolom Company dan Parent menampilkan pk mentah ("20")
    # di seluruh baris — dan itu tidak pernah berbunyi sebagai error.
    parent_name = serializers.SerializerMethodField()

    default_currency_code = serializers.CharField(
        source="default_currency.code", read_only=True, default=None,
    )

    account_type_label = serializers.CharField(
        source="get_account_type_display", read_only=True,
    )

    account_category_label = serializers.CharField(
        source="get_account_category_display", read_only=True,
    )

    # Saldo normal yang **berlaku**, bukan kolom mentahnya. Kolomnya
    # boleh kosong (= ikut golongan), dan menampilkan kosong di layar
    # membuat orang mengira akunnya belum diatur.
    effective_normal_balance = serializers.CharField(read_only=True)

    is_group = serializers.BooleanField(read_only=True)

    has_entries = serializers.SerializerMethodField()

    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = "__all__"

        read_only_fields = [
            "path",
            "level",
            "company_name",
            "parent_name",
            "default_currency_code",
            "account_type_label",
            "account_category_label",
            "effective_normal_balance",
            "is_group",
            "has_entries",
            "can_delete",
        ]

    def get_parent_name(self, obj) -> str | None:
        if obj.parent_id is None:
            return None

        return f"{obj.parent.code} — {obj.parent.name}"

    def get_has_entries(self, obj) -> bool:
        """
        Sudah pernah dipakai jurnal atau belum.

        Dipakai layar untuk menjelaskan kenapa tombol Delete tidak ada.
        Dihitung lewat `exists()`, bukan `count()`: yang ditanyakan
        "pernah atau tidak", dan menghitung seluruh barisnya pada akun
        kas yang berisi ratusan ribu baris adalah harga yang dibayar
        setiap kali daftar akun dibuka.
        """
        annotated = getattr(obj, "journal_line_count", None)

        if annotated is not None:
            return annotated > 0

        return obj.journal_lines.filter(is_deleted=False).exists()

    def get_can_delete(self, obj) -> bool:
        """
        Keadaan dokumen dijawab server, bukan disimpulkan layar dari
        kolom `has_entries` + `children`.

        Aturannya tinggal di `AccountService.before_soft_delete`, dan
        salinan aturan itu di frontend akan tertinggal diam-diam begitu
        syaratnya bertambah — tombolnya tetap tampil dan tiap
        penekanannya berakhir di penolakan API.
        """
        if self.get_has_entries(obj):
            return False

        return not obj.children.filter(is_deleted=False).exists()
