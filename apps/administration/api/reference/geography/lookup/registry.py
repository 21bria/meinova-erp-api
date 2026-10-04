"""
Lookup wilayah.

`filter_fields` di sini yang membuat penyaringan berantai benar-benar
bekerja. Parameter yang **tidak** terdaftar diabaikan diam-diam —
dropdown-nya tetap membalas 200 berisi seluruh baris, dan tidak ada satu
pun error yang menyebutkan bahwa penyaringnya tidak dipakai. Itu
penyebab klasik dropdown yang "tidak mau tersaring", dan di sini
akibatnya paling terasa: tanpa `city_id`, memilih satu kecamatan berarti
mencari di 83.762 kelurahan.
"""

from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import (
    City,
    Country,
    District,
    Province,
    Village,
)


class AreaCodeLabelMixin:
    """
    Label dropdown = `<kode wilayah> — <nama>`.

    Nama wilayah **tidak unik**, dan itu bukan kasus pinggiran: ada
    puluhan "Sukamaju" dan "Sukamulya" yang tersebar di banyak
    kabupaten, dan sebagian kabupaten memakai nama yang sama dengan
    provinsinya. Dropdown yang cuma menampilkan nama membuat yang
    memilih harus menebak — dan tebakan yang salah tersimpan sebagai
    induk yang salah, tanpa satu pun tanda di layar.

    Kodenya di **depan** supaya posisinya tetap sama di tiap baris —
    yang membandingkan dua "Sukamaju" membaca satu kolom, bukan mencari
    ujung nama yang panjangnya berbeda-beda.

    Urutan daftarnya tetap **nama**, bukan kode: yang memilih tahu nama
    wilayahnya dan mencarinya dengan mengetik, sementara kodenya justru
    yang sedang ia cari tahu. Jadi angka di kiri memang tidak berurut —
    itu disengaja, bukan daftar yang gagal tersortir.

    Baris lama yang belum punya `aid` (mis. hasil seed peragaan
    berkode `DKI`) jatuh ke `code`, dan yang tidak punya keduanya tetap
    tampil apa adanya — lebih baik daripada label berawalan pemisah
    yang menggantung.
    """

    @classmethod
    def serialize(cls, instance):
        data = super().serialize(instance)

        code = str(
            getattr(instance, "aid", "")
            or getattr(instance, "code", "")
            or ""
        ).strip()

        if code:
            data["label"] = f"{code} — {data['label']}"

        return data


@register_lookup
class CountryLookup(BaseLookup):
    name = "countries"
    model = Country

    search_fields = ["code","name"]
    ordering = [ "name"]


@register_lookup
class ProvinceLookup(AreaCodeLabelMixin, BaseLookup):
    name = "provinces"
    model = Province

    search_fields = ["code","aid","name"]

    # `country__code` dipakai form Employee: nationality-nya menyimpan
    # kode ISO-2 yang sama dengan `Country.code` (dua-duanya diseed dari
    # konvensi yang sama dan dua-duanya berconstraint unik), jadi rantai
    # Nationality -> Province bisa disambung lewat kode negaranya tanpa
    # ada yang perlu menyimpan pk Country di form.
    #
    # Nama filter dipakai apa adanya sebagai kwarg `filter()`, jadi
    # menembus relasi memang cukup dengan menuliskan jalurnya.
    filter_fields = ["country_id", "country__code"]

    ordering = ["name"]


@register_lookup
class CityLookup(AreaCodeLabelMixin, BaseLookup):
    name = "cities"
    model = City

    search_fields = [ "code","aid","name"]
    filter_fields = ["province_id"]

    ordering = [ "name" ]


@register_lookup
class DistrictLookup(AreaCodeLabelMixin, BaseLookup):
    name = "districts"
    model = District

    search_fields = ["code", "aid", "name"]
    filter_fields = ["city_id"]

    ordering = ["name"]


@register_lookup
class VillageLookup(AreaCodeLabelMixin, BaseLookup):
    name = "villages"
    model = Village

    search_fields = ["code", "aid", "name"]
    filter_fields = ["district_id"]

    ordering = ["name"]
