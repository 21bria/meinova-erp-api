from apps.core.models.base_reference import BaseReference


class CompanyType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_company_type"

class BranchType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_branch_type"

class LocationType(BaseReference):
    """
    Jenis **lokasi kerja** — tempat orang ditempatkan.

    Isinya sengaja pendek: Head Office, Office, Mine, Project, Port.
    Yang menentukan apakah sesuatu masuk ke sini adalah pertanyaan
    "apakah ada orang yang penempatannya di situ, dan absensi serta
    kalender liburnya menempel ke situ?".

    Workshop, Warehouse, Jetty, Camp, dan kawan-kawan **bukan** jenis
    lokasi walau sempat lama tercampur di sini — itu bangunan/fasilitas
    di dalam sebuah lokasi. Satu site Gebe punya workshop, gudang, dan
    jetty sekaligus; kalau ketiganya jadi Location, satu orang harus
    dipilihkan salah satunya sebagai tempat kerjanya, dan angka per
    lokasi jadi tidak bisa dijumlahkan. Lihat [`FacilityType`].
    """

    class Meta(BaseReference.Meta):
        db_table = "master_location_type"


class FacilityType(BaseReference):
    """
    Jenis **fasilitas** — bangunan atau sarana di dalam sebuah lokasi.

    Dipisah dari `LocationType` karena keduanya menjawab pertanyaan
    berbeda: Location menjawab "orang ini bekerja di mana", Facility
    menjawab "ada apa saja di sana". Satu Location punya banyak
    Facility, dan tidak ada orang yang penempatannya di sebuah Facility.
    """

    class Meta(BaseReference.Meta):
        db_table = "master_facility_type"

