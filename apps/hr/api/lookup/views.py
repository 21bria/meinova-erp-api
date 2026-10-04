from apps.framework.lookup import BaseLookupView


class HRLookupView(BaseLookupView):
    """
    Endpoint lookup untuk data transaksional HR (program pelatihan,
    lowongan, kandidat). Referensi HR-nya sendiri tetap dilayani
    `/api/administration/references/hr/lookup/`.
    """
