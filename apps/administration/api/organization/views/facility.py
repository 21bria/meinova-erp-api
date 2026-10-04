from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.administration.api.organization.serializers import (
    FacilitySerializer,
)
from apps.administration.api.organization.services import (
    FacilityService,
)


class FacilityViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Bangunan/sarana di dalam sebuah lokasi kerja.

    Bukan tempat penempatan pegawai — itu tetap `Location`. Lihat
    docstring model `Facility`.

    `ServiceWriteMixin` dipasang di depan base-nya supaya create/update
    benar-benar lewat service, dan `Facility.clean()` ikut jalan.
    Tanpa itu `service_class` cuma dipakai untuk `get_queryset()` dan
    `soft_delete()`, dan pemeriksaan company/branch/location tidak
    pernah dipanggil dari jalur API.
    """

    serializer_class = FacilitySerializer
    service_class = FacilityService

    framework_module = "administration/organization/facility"
    schema_type = "crud"

    ordering = ["code"]

    search_fields = [
        "code",
        "name",
        "company__name",
        "location__name",
        "facility_type__name",
    ]

    filterset_fields = [
        "company",
        "branch",
        "location",
        "facility_type",
        "is_active",
    ]

    # Fasilitas adalah aset di sebuah lokasi, jadi disaring dengan peta
    # yang sama seperti master organisasi lain — admin site tidak perlu
    # membaca daftar gudang milik site lain.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
    }

    schema = {
        "title": "Facility",
        "endpoint": "/api/administration/organization/facility/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
        },
        "fields": {
            "company": {
                "lookup_endpoint": (
                    "/api/administration/organization/lookup/companies/"
                ),
                "required": True,
                "placement": "quick",
                "order": 10,
            },

            "branch": {
                "lookup_endpoint": (
                    "/api/administration/organization/lookup/branches/"
                ),
                "depends_on": "company",
                "lookup_params": {
                    "company_id": "$company",
                },
                "order": 20,
            },

            # Seluruh induk yang mungkin terisi dikirim, bukan cuma yang
            # terdekat — Location boleh melompati Branch, dan penyaringan
            # satu level akan gugur begitu perantaranya kosong.
            "location": {
                "lookup_endpoint": (
                    "/api/administration/organization/lookup/locations/"
                ),
                "depends_on": "company",
                "lookup_params": {
                    "company_id": "$company",
                    "branch_id": "$branch",
                },
                "label": "Location",
                "required": True,
                "placement": "quick",
                "order": 30,
            },

            "facility_type": {
                "lookup_endpoint": (
                    "/api/administration/references/organization/"
                    "lookup/facility-types/"
                ),
                "label": "Facility Type",
                "required": True,
                "placement": "quick",
                "order": 40,
            },

            "code": {
                "label": "Facility Code",
                "placeholder": "e.g. WS-01",
                "required": True,
                "order": 50,
            },

            "name": {
                "label": "Facility Name",
                "placeholder": "e.g. Workshop Gebe",
                "required": True,
                "order": 60,
            },

            "description": {
                "label": "Description",
                "order": 70,
            },

            "is_active": {
                "label": "Active",
                "placement": "quick",
                "order": 999,
            },
        },
    }
