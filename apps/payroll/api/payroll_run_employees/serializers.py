from rest_framework import serializers

from apps.payroll.models import PayrollRunComponent, PayrollRunEmployee


class PayrollRunComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollRunComponent
        fields = [
            "id",
            "sequence",
            "component_type",
            "source",
            "code",
            "name",
            "basis",
            "base_amount",
            "rate",
            "quantity",
            "amount",
            "is_taxable",
            "reduces_taxable",
            "is_prorated",
            "reference_type",
            "reference_id",
            "calculation_note",
        ]


class PayrollRunEmployeeSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True, default=None,
    )
    employee_number = serializers.CharField(
        source="employee.employee_number", read_only=True, default=None,
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None,
    )
    section_name = serializers.CharField(
        source="section.name", read_only=True, default=None,
    )
    position_name = serializers.CharField(
        source="position.name", read_only=True, default=None,
    )
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )
    run_document_number = serializers.CharField(
        source="run.document_number", read_only=True, default=None,
    )
    period_name = serializers.CharField(
        source="run.period.name", read_only=True, default=None,
    )

    # Kebijakan yang dipakai baris ini, sebagai kalimat. Pegawai yang
    # mengikuti default perusahaan **tidak** dibiarkan kosong: sel
    # kosong terbaca seperti data yang gagal termuat, sementara yang
    # sebenarnya terjadi adalah jawaban yang sah.
    payroll_policy_label = serializers.SerializerMethodField()

    # Rincian per komponen — inilah yang membuat hasil bisa diaudit
    # tanpa menjalankan ulang mesin hitungnya.
    components = PayrollRunComponentSerializer(many=True, read_only=True)

    # Kuncinya bukan di baris ini melainkan di run-nya, dan itu persis
    # alasan field ini ada: layar tidak bisa menyimpulkan "boleh
    # disunting" dari kolom mana pun yang dipegang barisnya sendiri.
    # Metode prorata ditampilkan sebagai label, bukan `fixed_30`.
    # Yang membacanya orang HR yang sedang menjawab "kenapa gaji
    # pokoknya segitu", bukan yang menulis kodenya.
    proration_method_label = serializers.SerializerMethodField()

    # Potongan ketidakhadiran. Metodenya juga label, dan "belum
    # ditentukan" ditulis apa adanya — sel kosong di layar Review
    # terbaca seperti data yang gagal termuat.
    attendance_deduction_method_label = serializers.SerializerMethodField()

    # Cuti yang **tidak** memotong. Diturunkan, bukan kolom: kalau
    # disimpan terpisah ia akan menyimpang dari dua angka yang
    # membentuknya.
    paid_leave_days = serializers.SerializerMethodField()

    # Rincian per komponen sebagai teks siap baca — lihat
    # `get_components_summary` untuk alasan bentuknya.
    components_summary = serializers.SerializerMethodField()

    can_edit = serializers.SerializerMethodField()
    can_save = serializers.SerializerMethodField()

    # Baris ini tidak pernah dihapus — yang dikeluarkan dari payroll
    # ditandai Excluded beserta alasannya supaya jejaknya tetap ada.
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRunEmployee
        fields = "__all__"

        # Semua angka lahir dari Calculate. Yang boleh disunting orang
        # cuma pengecualian beserta alasannya, dan catatan.
        read_only_fields = [
            field.name
            for field in PayrollRunEmployee._meta.fields
            if field.name not in {"is_excluded", "exclusion_reason", "notes"}
        ]

    def get_can_edit(self, instance) -> bool:
        from apps.payroll.models import PayrollRunStatus

        return instance.run.status != PayrollRunStatus.FINALIZED

    def get_can_save(self, instance) -> bool:
        return self.get_can_edit(instance)

    def get_can_delete(self, instance) -> bool:
        return False

    def get_components_summary(self, instance) -> str:
        """
        Rincian komponen sebagai teks yang bisa dibaca langsung di layar.

        **Kenapa teks, bukan tabel.** `PayrollRunComponent` sengaja
        tidak punya ViewSet — baris perhitungan bukan resource yang
        boleh disunting, dan membuatkannya route CRUD hanya supaya ada
        tab adalah persis yang tidak boleh dilakukan. Workspace pun
        belum punya tipe tab untuk larik bersarang, dan widget JSON
        tidak ada di framework ini: `field.json` dibuang generator, jadi
        tab yang memakainya terbit sebagai "No form fields configured".
        Yang tersisa dan benar-benar bekerja hari ini adalah textarea
        read-only.

        Bentuknya belum secantik tabel, dan itu utang yang dicatat. Yang
        dijamin di sini bukan kecantikannya melainkan bahwa "kenapa
        tunjangan ini 800.000" bisa dijawab **dari layar**: tiap baris
        membawa nilainya, penanda pajak, dan keterangan yang
        menghasilkan angkanya sendiri.
        """
        # `.all()` apa adanya, lalu diurutkan di Python.
        #
        # Viewset sudah `prefetch_related` komponennya. Menambahkan
        # `.order_by()` di sini akan **melewati** cache prefetch itu
        # dan menerbitkan satu query per baris — daftar Payroll Review
        # berisi 500 pegawai jadi 500 query tambahan, untuk urutan yang
        # sama saja.
        rows = sorted(
            instance.components.all(),
            key=lambda row: (row.sequence, row.code),
        )

        lines: list[str] = []

        # Penghasilan dulu, baru potongan — urutan slip gaji dibaca
        # orang, bukan urutan abjad nilai enumnya ("deduction" jatuh
        # sebelum "earning" dan membuat potongan tercetak di atas).
        for side, title in (
            ("earning", "PENGHASILAN"),
            ("deduction", "POTONGAN"),
        ):
            side_rows = [row for row in rows if row.component_type == side]

            if not side_rows:
                continue

            lines.append("")
            lines.append(title)

            for row in side_rows:
                flags = []

                if side == "earning":
                    flags.append(
                        "kena pajak" if row.is_taxable else "bebas pajak",
                    )

                if row.is_prorated:
                    flags.append("prorata")

                if row.reduces_taxable:
                    flags.append("mengurangi dasar pajak")

                head = f"  {row.code:<16} {row.amount:>16,.2f}"

                if flags:
                    head = f"{head}  [{', '.join(flags)}]"

                lines.append(head)

                if row.calculation_note:
                    lines.append(f"      {row.calculation_note}")

        return "\n".join(lines).strip()

    def get_paid_leave_days(self, instance):
        return instance.leave_days - instance.unpaid_leave_days

    def get_payroll_policy_label(self, instance) -> str:
        from apps.payroll.models import PayrollPayBasis

        basis = ""

        if instance.pay_basis:
            try:
                basis = PayrollPayBasis(instance.pay_basis).label
            except ValueError:
                basis = instance.pay_basis

        if instance.payroll_policy_id is None:
            source = "Default perusahaan"
        else:
            policy = instance.payroll_policy
            source = f"{policy.code} - {policy.name}"

        return f"{source} ({basis})" if basis else source

    def get_attendance_deduction_method_label(self, instance) -> str:
        from apps.payroll.models import PayrollPayBasis, PayrollProrationMethod

        if instance.pay_basis == PayrollPayBasis.DAILY:
            # Dasar harian tidak punya pembagi potongan sama sekali.
            # "Hari kerja periode" di sini akan menyebutkan kebijakan
            # yang tidak pernah dipakai menghitung apa pun.
            return "-"

        if not instance.attendance_deduction_method:
            return "Hari kerja periode"

        try:
            return PayrollProrationMethod(
                instance.attendance_deduction_method,
            ).label
        except ValueError:
            return instance.attendance_deduction_method

    def get_proration_method_label(self, instance) -> str:
        from apps.payroll.models import PayrollProrationMethod

        if not instance.proration_method:
            return ""

        try:
            return PayrollProrationMethod(instance.proration_method).label
        except ValueError:
            return instance.proration_method
