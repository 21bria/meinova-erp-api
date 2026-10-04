from rest_framework import serializers


class EmployeeGeneralFieldsMixin(serializers.Serializer):
    full_name = serializers.CharField(
        read_only=True,
    )

    display_name = serializers.CharField(
        read_only=True,
    )

    # Nama untuk kolom tabel — lihat catatan di mixin employment:
    # kolom field lookup mencari `<nama_field>_name`, dan yang tidak
    # dikirim tampil "-" untuk semua baris tanpa error.
    gender_name = serializers.CharField(
        source="gender.name",
        read_only=True,
        default=None,
    )

    # Wajib, kecuali kalau nomornya minta dibuatkan. Kewajibannya
    # dipindah ke `validate()` di bawah karena `required=True` ditegakkan
    # DRF sebelum field lain sempat dibaca — form yang mencentang Auto
    # Generate akan ditolak sebelum ada satu baris pun kode kita jalan.
    employee_number = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )

    # Bukan kolom model: penanda yang dibaca `EmployeeService.create`,
    # lalu dibuang. Hanya berlaku saat create — nomor yang sudah terbit
    # tidak pernah dihitung ulang.
    auto_generate_employee_number = serializers.BooleanField(
        required=False,
        default=False,
        write_only=True,
    )

    first_name = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )

    # Penanda "kewarganegaraannya Indonesia", dibaca form untuk
    # menyalakan blok alamat wilayah (Province sampai Kelurahan/Desa).
    # Read-only dan bukan kolom sungguhan: sumbernya master
    # `Nationality`.
    #
    # Ada di dua jalur sekaligus dan memang harus: nilai ini terisi dari
    # sini saat form dimuat, dan diperbarui `autofill` pada field
    # Nationality begitu penggunanya memilih kewarganegaraan lain. Kalau
    # cuma salah satu, blok wilayahnya benar saat dibuka lalu salah
    # setelah diubah — atau sebaliknya.
    nationality_code = serializers.CharField(
        source="nationality.code",
        read_only=True,
        default=None,
    )

    # Nama untuk kolom tabel dan label dropdown yang sudah terisi —
    # kolom field lookup mencari `<nama_field>_name`, dan yang tidak
    # dikirim tampil "-" tanpa satu pun error.
    province_name = serializers.CharField(
        source="province.name",
        read_only=True,
        default=None,
    )

    city_name = serializers.CharField(
        source="city.name",
        read_only=True,
        default=None,
    )

    district_name = serializers.CharField(
        source="district.name",
        read_only=True,
        default=None,
    )

    village_name = serializers.CharField(
        source="village.name",
        read_only=True,
        default=None,
    )

    def validate_employee_number(self, value):
        return (value or "").strip()

    def validate(self, attrs):
        attrs = super().validate(attrs)

        auto = attrs.get("auto_generate_employee_number", False)

        # Pada update, `employee_number` boleh tidak dikirim sama sekali
        # (PATCH) — yang dilarang cuma mengosongkannya.
        is_create = self.instance is None

        number = attrs.get(
            "employee_number",
            None if is_create else self.instance.employee_number,
        )

        if auto and not is_create:
            raise serializers.ValidationError(
                {
                    "auto_generate_employee_number": (
                        "Nomor pegawai hanya dibuat otomatis saat "
                        "pegawainya dibuat. Nomor yang sudah terbit "
                        "tidak diganti — ia sudah tercetak di kontrak "
                        "dan terdaftar di mesin absensi."
                    ),
                },
            )

        if not auto and not str(number or "").strip():
            raise serializers.ValidationError(
                {
                    "employee_number": (
                        "Employee Number wajib diisi, atau nyalakan "
                        "Auto Generate."
                    ),
                },
            )

        # Keunikannya dikondisikan ke `is_deleted`, jadi DRF tidak
        # membangkitkan validatornya sendiri dan tabrakan baru muncul di
        # `full_clean()` sebagai "Constraint uniq_active_employee_number
        # is violated" — kalimat yang tidak menempel di kolom mana pun
        # dan tidak memberi tahu siapa pemakai nomor itu.
        if not auto and number:
            from apps.hr.models import Employee

            clash = Employee.objects.filter(
                employee_number=number,
                is_deleted=False,
            )

            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)

            existing = clash.first()

            if existing is not None:
                raise serializers.ValidationError(
                    {
                        "employee_number": (
                            f"Nomor {number} sudah dipakai "
                            f"{existing.full_name}."
                        ),
                    },
                )

        return attrs

    def validate_first_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "First Name is required."
            )

        return value