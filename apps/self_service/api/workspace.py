"""
Kontrak `GET /api/me/workspace/` — ringkasan hari kerja pemegang akun.

**Daftar putih eksplisit**, alasan yang sama persis dengan
`SelfProfileSerializer`: tidak satu field pun di sini lahir dari
introspeksi model, jadi kolom baru yang ditambahkan HR, Payroll, atau
Workflow besok **tidak** ikut terkirim sampai ada yang memutuskan ia
boleh.

Bedanya dengan `/api/me/profile/`, dan kenapa keduanya memang dua
endpoint
-------------------------------------------------------------------
Profil menjawab "apa isi kartu kepegawaian saya" — satu baris Employee,
berubah beberapa kali setahun. Workspace menjawab "bagaimana hari kerja
saya" — tujuh sumber berbeda, berubah setiap hari. Menggabungkannya
berarti layar profil ikut membayar tujuh query itu setiap kali dibuka,
dan kartu identitas berhenti bisa di-cache.

Yang **tidak** ada di sini, dan sengaja
---------------------------------------
Nilai gaji dalam bentuk apa pun, catatan internal HR (`notes`,
`review_notes`, `adjustment_reason`), metadata audit
(`created_by`/`updated_by`/`deleted_*`), koordinat dan alamat presensi,
identitas perangkat absensi, internal engine workflow (nama step,
approver, `can_configure`), dan pk akun. Daftar itu bukan hasil
penyaringan — tidak satu pun pernah ikut terbawa, karena tidak satu pun
pernah disebut.
"""

from rest_framework import serializers

from apps.self_service.api.profile import reference


# ----------------------------------------------------------------------
# Seksi
# ----------------------------------------------------------------------


class WorkspaceActionSerializer(serializers.Serializer):
    """
    Tombol yang **backend** putuskan layak tampil.

    Rutenya ikut dikirim, bukan dipetakan frontend dari `code`. Dua peta
    rute yang harus tetap sepakat adalah cara satu tombol diam-diam
    mendarat di halaman yang salah setelah rute modulnya dipindah.
    """

    code = serializers.CharField(read_only=True)
    route = serializers.CharField(read_only=True)


class SelfWorkspaceSerializer(serializers.Serializer):
    """
    Pembungkus tipis: `hero` dirakit dari baris Employee yang sudah
    di-resolve, sisanya diteruskan apa adanya dari
    `SelfWorkspaceService`.

    `Serializer` biasa, bukan `ModelSerializer` — yang terakhir
    menurunkan field dari model, dan penurunan otomatis adalah persis
    mekanisme yang membuat kolom baru ikut terkirim tanpa ada yang
    memutuskannya.
    """

    def __init__(self, employee, *, workspace, **kwargs):
        self.workspace = workspace

        super().__init__(employee, **kwargs)

    identity = serializers.SerializerMethodField()
    hero = serializers.SerializerMethodField()

    as_of = serializers.SerializerMethodField()
    schedule = serializers.SerializerMethodField()
    attendance = serializers.SerializerMethodField()
    requests = serializers.SerializerMethodField()
    leave = serializers.SerializerMethodField()
    permission = serializers.SerializerMethodField()
    overtime = serializers.SerializerMethodField()
    payslip = serializers.SerializerMethodField()
    quick_actions = serializers.SerializerMethodField()

    # ------------------------------------------------------------------
    # Identitas
    # ------------------------------------------------------------------

    def get_identity(self, employee) -> dict:
        """
        Sama persis dengan `GET /api/me/` — **dipinjam, bukan ditulis
        ulang**. Nama dan foto yang berbeda antara sidebar dan dashboard
        adalah selisih yang terlihat pemakainya sebelum terlihat siapa
        pun yang membaca kodenya.
        """
        from apps.self_service.api.serializers import SelfIdentitySerializer

        return SelfIdentitySerializer(
            employee,
            context=self.context,
        ).data

    def get_hero(self, employee) -> dict:
        """
        Konteks kerja seperlunya untuk kepala dashboard.

        Enam field, dan batasnya disengaja: yang dipakai orang untuk
        berorientasi ("saya siapa, di mana, di bawah siapa"). Sisi
        lengkapnya — tanggal bergabung, cost center, job grade, atasan,
        seluruh alamat — tinggal di `/me/profile`, dan mengulangnya di
        sini persis yang membuat dua halaman terbaca sebagai halaman
        yang sama dengan jumlah field berbeda.
        """
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        return {
            "position": reference(getattr(organization, "position", None)),
            "department": reference(getattr(organization, "department", None)),
            "company": reference(getattr(organization, "company", None)),
            "location": reference(getattr(organization, "location", None)),
            "employment_status": reference(
                getattr(employment, "employment_status", None),
            ),
            "employment_type": reference(
                getattr(employment, "employment_type", None),
            ),
        }

    # ------------------------------------------------------------------
    # Seksi dashboard
    # ------------------------------------------------------------------
    #
    # Diteruskan apa adanya dari service. Bentuknya sudah final di sana
    # — menyalinnya lagi field per field di sini cuma menambah satu
    # tempat lagi yang bisa ketinggalan.

    def get_as_of(self, _employee):
        return self.workspace["as_of"]

    def get_schedule(self, _employee) -> dict:
        return self.workspace["schedule"]

    def get_attendance(self, _employee) -> dict:
        return self.workspace["attendance"]

    def get_requests(self, _employee) -> dict:
        return self.workspace["requests"]

    def get_leave(self, _employee) -> dict:
        return self.workspace["leave"]

    def get_permission(self, _employee) -> dict:
        return self.workspace["permission"]

    def get_overtime(self, _employee) -> dict:
        return self.workspace["overtime"]

    def get_payslip(self, _employee) -> dict:
        return self.workspace["payslip"]

    def get_quick_actions(self, _employee) -> list:
        return self.workspace["quick_actions"]
