from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.accounts.jwt import bind_tenant

User = get_user_model()


class LoginSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        token["user_id"] = str(user.id)
        token["username"] = user.username
        token["email"] = user.email
        token["is_staff"] = user.is_staff
        token["is_superuser"] = user.is_superuser

        # Token hanya sah di tenant tempat ia terbit — lihat
        # `apps.accounts.jwt`. Access token mewarisinya dari refresh token.
        bind_tenant(token)

        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        data["user"] = MeSerializer(self.user).data

        return data


class MeSerializer(serializers.ModelSerializer):
    """
    Identitas + wewenang pengguna yang sedang login.

    Dipakai frontend untuk menampilkan nama di sidebar dan menyaring
    menu. Sebelumnya nama dan emailnya **ditulis mati** di
    `AppSidebar.vue` — semua orang yang login melihat "Meinardus /
    admin@meinova.id" apa pun akunnya.
    """

    permissions = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    initials = serializers.SerializerMethodField()
    placement = serializers.SerializerMethodField()
    data_scope = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "display_name",
            "initials",
            "is_staff",
            "is_superuser",
            "is_active",
            # Bahasa antarmuka pilihan pemegang akun. Dibaca frontend
            # saat login untuk menyetel ulang bahasanya — supaya
            # pilihan itu ikut orangnya, bukan ikut browsernya.
            #
            # **Ditambahkan, bukan menggantikan apa pun.** Konsumen
            # lama yang tidak mengenal kolom ini tidak terpengaruh.
            "language",
            # `groups` bawaan Django sengaja **tidak** dikirim. Model
            # User memang mewarisinya dari AbstractUser, tapi tidak ada
            # satu baris kode pun di sistem ini yang membacanya — hak
            # akses seluruhnya lewat `roles`. Mengirimkannya membuat
            # orang mengisinya lalu heran kenapa tidak berpengaruh.
            "roles",
            "permissions",
            "capabilities",
            "placement",
            "data_scope",
        ]

    def get_full_name(self, user):
        return user.get_full_name() or user.username

    def get_display_name(self, user):
        """Nama yang enak dibaca; jatuh ke username lalu email."""
        return (
            user.get_full_name()
            or user.username
            or user.email
        )

    def get_initials(self, user):
        """Dua huruf untuk avatar, dari nama atau email."""
        source = self.get_display_name(user) or ""

        parts = [part for part in source.replace(".", " ").split() if part]

        if not parts:
            return "?"

        if len(parts) == 1:
            return parts[0][:2].upper()

        return (parts[0][0] + parts[-1][0]).upper()

    def get_roles(self, user):
        return list(
            user.roles
            .filter(is_deleted=False)
            .values("id", "code", "name")
        )

    def get_capabilities(self, user):
        from apps.accounts.capabilities import capabilities_for

        return capabilities_for(user)

    def get_permissions(self, user):
        if user.is_superuser:
            return ["*"]

        return list(user.get_all_permissions())

    def get_placement(self, user):
        """
        Penempatan organisasi pemegang akun.

        Dipakai form untuk mengisi Company/Site/Section sendiri lewat
        `default="$me.placement.company"` — admin site tidak perlu
        mencari perusahaannya di daftar dua belas baris yang sepuluh di
        antaranya bernama "Default Location".

        **Bukan** cakupan, dan dua hal itu tidak boleh dicampur.
        Penempatan menjawab "orang ini duduk di mana"; cakupan menjawab
        "boleh melihat baris yang mana". HR pusat ditempatkan di
        Jakarta tapi cakupannya seluruh tenant — mengunci form-nya ke
        Jakarta akan salah.

        Akun tanpa pegawai (akun sistem, superuser yang bukan karyawan)
        mengembalikan dict kosong, dan itu keadaan yang sah.
        """
        from apps.accounts.scoping import DataScopeService

        placement = DataScopeService.placement_for(user)

        return placement or {}

    def get_data_scope(self, user):
        """
        Ringkasan cakupan data + nilai yang tersirat darinya.

        `unrestricted=False` yang membuat form mengunci Company/Site:
        orang yang cuma boleh melihat satu site tidak boleh membuat
        dokumen untuk site lain — dokumennya akan tersimpan lalu
        seketika hilang dari layarnya sendiri, dan dari kursinya itu
        terbaca seperti penyimpanan yang gagal.
        """
        from apps.accounts.scoping import DataScopeService

        scope = DataScopeService.for_user(user)

        values = DataScopeService.implied_values(user)

        return {
            **scope.summary(),
            # Nilai untuk tombol pintas "Lokasi Saya" — lihat
            # `get_self_filter_values`. Terpisah dari `values` di bawah
            # karena menjawab pertanyaan yang berbeda: `values`
            # **mengunci** form, yang ini cuma mengisikan filter yang
            # tetap bisa diubah orangnya.
            "self_filter": self.get_self_filter_values(user),
            # `values` yang dipakai form untuk mengunci, **per jenis**,
            # bukan satu penanda "terkunci" untuk seluruh form:
            # `readonly_when={"field": "$me.data_scope.values.company",
            # "op": "is_not_null"}`.
            #
            # Bedanya nyata. Admin bercakupan company boleh memilih site
            # mana pun **di dalam** company-nya; mengunci Site untuknya
            # hanya karena cakupannya sempit membuatnya tidak bisa
            # menyusun roster site sebelah yang memang tanggung
            # jawabnya. Cakupan yang menunjuk **dua** lokasi tidak
            # menyiratkan satu pun nilai (`implied_values` sudah
            # membuangnya), jadi form-nya tetap terbuka.
            "values": values,
        }


    # ------------------------------------------------------------------
    # Tombol pintas "Lokasi Saya"
    # ------------------------------------------------------------------

    def get_self_filter_values(self, user) -> dict:
        """
        Isi tombol pintas per jenis filter, dibaca schema lewat
        `self_filter="$me.data_scope.self_filter.location"`.

        Bawaannya **sama persis dengan sebelumnya**: lokasi penempatan
        pemegangnya, satu nilai. Yang berbeda hanya untuk direksi —
        penempatan yang sama di seluruh badan usaha yang boleh ia
        lihat, sebagai daftar. Tempatnya tetap tempat ia duduk; yang
        ditambahkan cuma baris-baris kembarannya.

        Aturan "siapa yang direksi" dan "lokasi mana yang boleh
        dilihatnya" tidak ditulis di sini melainkan di
        `apps/accounts/board.py`, karena penyaring dashboard membaca
        aturan yang sama persis saat memperluas pilihan Location. Dua
        salinan aturan itu akan menyimpang, dan menyimpangnya berbunyi
        seperti kebocoran: tombol memilih lokasi yang tidak ada di
        daftar pilihannya sendiri.

        Kosong berarti tombolnya tidak ditampilkan sama sekali, dan itu
        keadaan yang sah: akun tanpa pegawai tidak punya penempatan.
        """
        from apps.accounts import board
        from apps.accounts.scoping import DataScopeService

        placement = DataScopeService.placement_for(user)

        values: dict = {}

        location = placement.get("location")

        if location is not None:
            values["location"] = location

            kembaran = board.self_filter_location_ids(user, location)

            # Kalau penempatannya sendiri di luar cakupannya, nilainya
            # dibiarkan berdiri. Menggantinya dengan daftar kosong
            # membuat tombolnya hilang tanpa sebab yang terlihat.
            if kembaran:
                values["location"] = kembaran

        return values


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        user = self.context["request"].user

        if not user.check_password(value):
            raise serializers.ValidationError("Password lama tidak sesuai.")

        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({
                "confirm_password": "Konfirmasi password tidak sama."
            })

        validate_password(attrs["new_password"], self.context["request"].user)

        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])

        return user

class ProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Yang boleh diubah pengguna atas dirinya sendiri.

    **Daftarnya sengaja pendek, dan bukan `MeSerializer`.** Serializer
    itu mengirim `is_staff`, `is_superuser`, `roles`, dan `permissions`;
    memakainya sebagai jalur tulis berarti siapa pun bisa menaikkan
    dirinya jadi superuser lewat satu PATCH ke endpoint profilnya
    sendiri. Dua serializer terpisah, dan yang menulis hanya mengenal
    empat kolom.

    `username` juga tidak ikut: ia dipakai untuk login, tercetak di
    jejak audit, dan dirujuk dokumen yang sudah berjalan.
    """

    class Meta:
        model = User
        # `language` ikut karena memang preferensi tampilan milik
        # orangnya sendiri — sederajat dengan namanya, bukan dengan
        # role atau izinnya. Validasi pilihannya dijalankan
        # `ChoiceField` bawaan ModelSerializer dari
        # `settings.LANGUAGES`; nilai di luar daftar dibalas 400,
        # bukan tersimpan diam-diam.
        fields = ["first_name", "last_name", "email", "language"]

    def validate_email(self, value):
        value = (value or "").strip()

        if not value:
            raise serializers.ValidationError("Email wajib diisi.")

        # `User.email` unik, dan `full_clean()` tidak dijalankan oleh
        # DRF di jalur ini — tanpa pemeriksaan ini tabrakannya muncul
        # sebagai IntegrityError 500, bukan pesan yang menempel di
        # kolomnya.
        taken = (
            User.objects
            .filter(email__iexact=value)
            .exclude(pk=self.instance.pk if self.instance else None)
            .exists()
        )

        if taken:
            raise serializers.ValidationError(
                "Email ini sudah dipakai akun lain.",
            )

        return value
