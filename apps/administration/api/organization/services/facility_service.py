from apps.core.services.master import BaseMasterService

from apps.administration.models import Facility


class FacilityService(BaseMasterService):
    """
    Turunan `BaseMasterService`, bukan kelas polos berisi `list()` saja
    seperti master organisasi lain.

    Alasannya `Facility.clean()`: pasangan company/branch/location yang
    tidak konsisten hanya ditolak kalau `full_clean()` benar-benar
    dijalankan, dan itu cuma terjadi lewat jalur service. Viewsetnya
    memasang `ServiceWriteMixin` supaya jalur tulis API sungguh-sungguh
    lewat sini — tanpa keduanya, penjagaan di model tersimpan rapi tanpa
    pernah dipanggil, dan fasilitas Gebe bisa dititipkan ke company lain
    lewat API tanpa satu pun keluhan.
    """

    model = Facility

    @classmethod
    def list(cls):
        return (
            cls.get_queryset()
            .select_related(
                "company",
                "branch",
                "location",
                "facility_type",
            )
            .order_by("company__code", "location__code", "code")
        )
