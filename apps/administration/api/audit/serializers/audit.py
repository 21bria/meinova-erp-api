from rest_framework import serializers

from apps.administration.models import AuditTrail


class AuditTrailSerializer(serializers.ModelSerializer):
    """
    Tiga kolom nama yang dicari tabel, dan dulu tidak satu pun dikirim.

    `columns.ts` hasil generate menunjuk `company_name`, `location_name`,
    dan `user_name`; serializer yang cuma `fields = "__all__"` mengirim
    `company`, `location`, `user` sebagai pk. Akibatnya ketiga kolom itu
    menampilkan **"-" di semua baris** — dan justru kolom "User" yang
    kosong membuat seluruh layar jejak audit tidak menjawab pertanyaan
    yang membuat orang membukanya: siapa yang mengubah ini.

    Selama tabelnya masih nol baris, kesalahan ini tidak kelihatan.
    """

    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    user_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditTrail
        fields = "__all__"

        read_only_fields = ["company_name", "location_name", "user_name"]

    def get_user_name(self, obj) -> str | None:
        """
        Nama yang terbaca, bukan username.

        `demo.hrmanager` di kolom User memaksa pembacanya menerjemahkan
        sendiri; nama lengkapnya sudah ada di akun yang sama. Akun yang
        namanya belum diisi tetap jatuh ke username — lebih baik
        daripada kosong.
        """
        if obj.user_id is None:
            return None

        return obj.user.get_full_name() or obj.user.username
