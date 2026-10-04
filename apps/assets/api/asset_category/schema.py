from apps.framework.builders import field, tabs, ui


GENERAL_FIELDS = {
    "code": field.text(
        tab="general",
        label="Code",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        help_text=(
            "Kode tetap, mis. LAPTOP atau RADIO_HT. Disimpan dalam huruf "
            "besar; kode kategori yang sudah dihapus boleh dipakai lagi."
        ),
        order=10,
    ),

    "name": field.text(
        tab="general",
        label="Name",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "description": field.textarea(
        tab="general",
        label="Description",
        rows=2,
        required=False,
        table=False,
        search=True,
        order=30,
    ),

    "sort_order": field.integer(
        tab="general",
        label="Sort Order",
        required=False,
        table=True,
        sortable=True,
        help_text="Angka kecil tampil lebih dulu di dropdown.",
        order=40,
    ),

    "is_active": field.switch(
        tab="general",
        label="Active",
        required=False,
        table=True,
        filter=True,
        sortable=True,
        help_text=(
            "Dimatikan: kategori tidak bisa dipilih lagi untuk aset baru, "
            "tetapi aset yang sudah memakainya tidak berubah."
        ),
        order=50,
    ),

    "requires_serial_number": field.switch(
        tab="general",
        label="Requires Serial Number",
        required=False,
        table=True,
        filter=True,
        help_text=(
            "Dinyalakan: aset berkategori ini tidak bisa diaktifkan tanpa "
            "serial number. Tidak berlaku surut untuk aset yang sudah aktif."
        ),
        order=60,
    ),

    "allow_employee_custody": field.switch(
        tab="general",
        label="Employee Custody",
        required=False,
        table=True,
        filter=True,
        help_text="Boleh dipegang perorangan (mis. laptop, HP).",
        order=70,
    ),

    "allow_organization_custody": field.switch(
        tab="general",
        label="Organization Custody",
        required=False,
        table=True,
        filter=True,
        help_text=(
            "Boleh dipegang unit/department dengan PIC (mis. kendaraan, "
            "alat berat). Minimal satu dari dua saklar ini harus hidup; "
            "penyimpanan (STORAGE) selalu boleh."
        ),
        order=80,
    ),
}


ASSET_CATEGORY_SCHEMA = {
    "module": "assets/categories",
    "name": "AssetCategory",
    "label": "Asset Category",
    "endpoint": "/api/assets/categories/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Asset Category",
            description=(
                "Klasifikasi operasional aset — berlaku untuk seluruh "
                "company. Tidak menentukan akun atau penyusutan."
            ),
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
    },

    "tabs": [
        tabs.form(
            key="general",
            label="General",
            fields=list(GENERAL_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
    ],

    "fields": GENERAL_FIELDS,
}
