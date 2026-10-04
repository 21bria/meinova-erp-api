from rest_framework import serializers

from apps.payroll.models import AllowanceTemplateLine


class AllowanceTemplateLineSerializer(serializers.ModelSerializer):
    template_code = serializers.CharField(
        source="template.code", read_only=True, default=None,
    )
    template_name = serializers.CharField(
        source="template.name", read_only=True, default=None,
    )

    # Kolom tabel yang berbunyi seperti yang dimaksudnya.
    #
    # Generator memetakan **semua** boolean ke `column.status`, jadi
    # kolomnya terbaca "Active"/"Inactive" — pada kolom Taxable itu
    # bukan cuma janggal, itu salah: "Active" tidak menjawab apakah
    # tunjangan ini menambah dasar pajak. Dua field label di bawah yang
    # dipakai kolomnya (`display_key`), tanpa menyentuh cara generator
    # memperlakukan boolean di modul lain.
    # Basis pun label, bukan `percent_of_basic`. Ini kolom yang paling
    # sering dibaca HR di layar ini; enum mentah di situ adalah
    # kebocoran yang sama seperti `fixed_30` di layar Payroll Review.
    basis_label = serializers.SerializerMethodField()

    def get_basis_label(self, instance) -> str:
        from apps.payroll.models import PayrollBasis

        try:
            return PayrollBasis(instance.basis).label
        except ValueError:
            return instance.basis

    is_taxable_label = serializers.SerializerMethodField()
    is_prorated_label = serializers.SerializerMethodField()

    def get_is_taxable_label(self, instance) -> str:
        return "Taxable" if instance.is_taxable else "Non-taxable"

    def get_is_prorated_label(self, instance) -> str:
        from apps.payroll.models import QUANTITY_BASES

        if instance.basis in QUANTITY_BASES:
            # Basis per hari tidak pernah diprorata lagi — nilainya
            # sudah mengandung harinya. Menampilkan "Prorated" di sini
            # menjanjikan sesuatu yang tidak terjadi.
            return "Per hari (tanpa prorata)"

        return "Prorated" if instance.is_prorated else "Tidak diprorata"

    class Meta:
        model = AllowanceTemplateLine
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
