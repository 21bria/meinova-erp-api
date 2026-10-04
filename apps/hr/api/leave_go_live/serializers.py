from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.models import LeaveGoLive

from .services import LeaveGoLiveService


class LeaveGoLiveSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
    )

    # Diturunkan, bukan disimpan — dua tanggal yang harus selalu
    # berselisih satu hari cepat atau lambat berselisih dua. Tetap
    # dikirim karena inilah tanggal yang disebut HR saat menanyakan
    # datanya ke sistem lama ("saldo per tanggal berapa?").
    cutoff_date = serializers.DateField(read_only=True)

    draft_count = serializers.SerializerMethodField()
    posted_count = serializers.SerializerMethodField()

    class Meta:
        model = LeaveGoLive
        fields = "__all__"

        # Dimatikan dengan alasan yang sama seperti di saldo awal:
        # `UniqueTogetherValidator` bawaan menuntut seluruh anggota
        # constraint hadir di payload, jadi PATCH yang cuma menggeser
        # tanggal dibalas "This field is required" untuk company yang
        # tidak disentuh siapa pun. Constraint database tetap berlaku.
        validators = []

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "company_name",
            "cutoff_date",
            "draft_count",
            "posted_count",
        ]

    def _readiness(self, obj) -> dict:
        cached = getattr(obj, "_readiness_cache", None)

        if cached is None:
            cached = LeaveGoLiveService.readiness(obj)

            obj._readiness_cache = cached

        return cached

    def get_draft_count(self, obj) -> int:
        return self._readiness(obj)["draft_count"]

    def get_posted_count(self, obj) -> int:
        return self._readiness(obj)["posted_count"]

    def validate(self, attrs):
        instance = self.instance

        company = attrs.get(
            "company",
            getattr(instance, "company", None),
        )

        if company is not None:
            existing = (
                LeaveGoLive.objects
                .filter(company=company, is_deleted=False)
                .exclude(pk=getattr(instance, "pk", None))
                .first()
            )

            # Ditolak di sini, bukan dibiarkan jatuh sebagai
            # IntegrityError: pesan constraint tidak menempel di kolom
            # mana pun dan tidak menyebut tanggal yang sudah tersimpan —
            # padahal itu satu-satunya hal yang perlu diketahui
            # pengetiknya sebelum memutuskan menggesernya atau tidak.
            if existing is not None:
                raise serializers.ValidationError(
                    {
                        "company": (
                            f"{company.name} sudah punya tanggal "
                            f"go-live cuti ({existing.go_live_date}). "
                            f"Ubah baris itu, jangan membuat yang baru."
                        ),
                    },
                )

        return attrs
