"""
Baris sebuah model yang boleh **dibaca** seorang pengguna — dijawab
dari deklarasi viewset-nya sendiri.

Kenapa ini ada
--------------
Tiga lapis otoritas baca sudah lengkap dan sudah dipakai di mana-mana:

* **WHAT** — `require_view_permission` + `ModelPermission`;
* **WHERE** — `data_scope` + `DataScopeService` (per izin sejak 3A);
* **WHICH** — `data_subject` + `EmployeeDataPolicy`.

Ketiganya dideklarasikan **di viewset**, dan ditegakkan di
`filter_queryset()`. Itu benar untuk request yang datang ke viewset itu.
Yang tidak terjawab: pemanggil yang memegang **modelnya** dan perlu tahu
baris mana yang boleh dibaca seseorang — tanpa punya request, tanpa
punya viewset, dan tanpa boleh tahu apa pun tentang HR atau payroll.

Contoh yang membuatnya perlu: sebuah berkas lampiran. Yang menentukan
boleh tidaknya ia dibuka bukan berkasnya, melainkan **record yang
menunjuknya** — dan `apps/uploads` tidak boleh tahu bahwa record itu
kebetulan dokumen pegawai.

Kenapa membaca viewset, bukan daftar baru
-----------------------------------------
Karena daftar kedua adalah cara paling pasti untuk menyimpang. Peta
cakupan dan kelompok data sudah tertulis satu kali di viewset-nya;
menyalinnya ke registry lain berarti dua tempat yang harus tetap
sepakat, dan yang pertama menyimpang tidak akan berbunyi — ia cuma
memperlihatkan baris yang seharusnya tertutup.

Yang **tidak** dilakukan di sini: memutuskan apa yang terjadi kalau
sebuah model tidak punya viewset sama sekali. Itu dikembalikan sebagai
`None`, dan pemanggilnya yang memutuskan — karena jawabannya berbeda
menurut apa yang sedang ditanyakan.
"""

from __future__ import annotations

from django.db.models import QuerySet
from django.urls import get_resolver


def _all_subclasses(cls):
    found = []

    for subclass in cls.__subclasses__():
        found.append(subclass)
        found.extend(_all_subclasses(subclass))

    return found


def _viewsets_by_model() -> dict:
    """
    Peta `{model: [viewset]}`, dibangun sekali.

    `__subclasses__` hanya menemukan kelas yang **sudah diimpor**.
    Lewat HTTP itu selalu terpenuhi karena URLconf-nya termuat, tapi
    pemanggil lain — task, shell, test — bisa mendapat peta kosong, dan
    peta kosong di sini terbaca persis seperti "model ini tidak dijaga
    apa pun". Menyentuh resolver membuatnya pasti.
    """
    from rest_framework.viewsets import GenericViewSet

    from apps.framework.views.permissions import _model_of

    get_resolver().url_patterns

    mapping: dict = {}

    for view_class in _all_subclasses(GenericViewSet):
        if not view_class.__module__.startswith("apps."):
            continue

        model = _model_of(view_class)

        if model is None:
            continue

        mapping.setdefault(model, []).append(view_class)

    return mapping


def model_for_module(module: str):
    """
    Model di balik sebuah `framework_module`, atau `None`.

    `framework_module` adalah kunci yang sudah dipakai frontend untuk
    mencocokkan layar dengan endpoint-nya, dan yang dipakai
    `ImportJob.module` untuk menyebut sasaran importnya. Memakainya
    lagi di sini berarti tidak ada tabel pemetaan kedua yang harus
    dijaga tetap sepakat — dan tidak ada modul yang diam-diam kehilangan
    penjagaannya karena seseorang lupa mendaftarkannya.
    """
    from rest_framework.viewsets import GenericViewSet

    from apps.framework.views.permissions import _model_of

    get_resolver().url_patterns

    target = str(module or "").strip("/")

    if not target:
        return None

    for view_class in _all_subclasses(GenericViewSet):
        if not view_class.__module__.startswith("apps."):
            continue

        declared = str(getattr(view_class, "framework_module", "") or "")

        if declared.strip("/") != target:
            continue

        model = _model_of(view_class)

        if model is not None:
            return model

    return None


def may_read_model(model, user) -> bool:
    """
    Boleh `user` membaca resource ini **sama sekali** — pertanyaan
    WHAT saja, tanpa menyentuh baris mana.

    Dipakai pemanggil yang menilai sesuatu **tentang** sebuah resource
    alih-alih barisnya: riwayat import, misalnya. Yang tidak dijaga
    izin menjawab `True`, karena bacanya memang terbuka — menuntut izin
    di sini akan membuat catatan tentang sebuah tabel lebih rahasia
    daripada isi tabelnya sendiri.
    """
    from django.conf import settings

    from apps.accounts.permissions import view_permission_for

    if model is None:
        return False

    if user is None or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    declaration = declared_authority(model)

    if declaration is None:
        return False

    if not declaration["gated"]:
        return True

    if not getattr(settings, "ENFORCE_VIEW_PERMISSIONS", True):
        return True

    permission = view_permission_for(model)

    return bool(permission and user.has_perm(permission))


def declared_authority(model) -> dict | None:
    """
    Deklarasi otoritas baca sebuah model, atau `None` kalau tidak satu
    pun viewset memilikinya.

    Kalau sebuah model dilayani lebih dari satu viewset, yang dipakai
    yang **paling ketat** — viewset yang menuntut izin menang atas yang
    tidak, dan cakupan yang ada menang atas yang kosong. Melonggarkan
    karena ada satu pintu yang lebih longgar adalah kebalikan dari yang
    dimaksud lapisan ini.
    """
    views = _viewsets_by_model().get(model)

    if not views:
        return None

    gated = any(
        getattr(view, "require_view_permission", False) for view in views
    )

    scope = next(
        (
            getattr(view, "data_scope", None)
            for view in views
            if getattr(view, "data_scope", None)
        ),
        None,
    )

    subject = next(
        (
            str(getattr(view, "data_subject", "") or "")
            for view in views
            if getattr(view, "data_subject", None)
        ),
        "",
    )

    subject_path = next(
        (
            getattr(view, "data_subject_path", "employee")
            for view in views
            if getattr(view, "data_subject", None)
        ),
        "employee",
    )

    return {
        "gated": gated,
        "scope": scope,
        "subject": subject,
        "subject_path": subject_path,
    }


def readable_queryset(model, user) -> QuerySet | None:
    """
    Baris `model` yang boleh dibaca `user`.

    `None` = model ini tidak dilayani viewset mana pun, jadi tidak ada
    aturan baca yang bisa diturunkan. **Bukan** "boleh semua": yang
    memutuskan pemanggilnya.

    Ketiga lapis dipasang dengan urutan yang sama seperti di
    `BaseMasterViewSet.filter_queryset()` — izin dulu, lalu cakupan,
    lalu kelompok data — supaya jawabannya identik dengan yang
    dikirimkan endpoint model itu sendiri. Kalau berbeda, dua pintu ke
    baris yang sama akan menjawab berbeda, dan bedanya tidak terlihat
    siapa pun.
    """
    from django.conf import settings

    from apps.accounts.permissions import view_permission_for
    from apps.accounts.scoping import DataScopeService

    # Model yang menjawab sendiri.
    #
    # Sebagian resource tidak dilayani viewset sama sekali — `ImportJob`
    # dilayani sekumpulan `APIView` — jadi tidak ada deklarasi yang bisa
    # dibaca. Alih-alih menaruh daftar pengecualian di pemanggilnya
    # (yang berarti tiap pemanggil baru harus ingat memperbaruinya),
    # modelnya sendiri yang boleh menjawab lewat `readable_for(user)`.
    #
    # Itu yang membuat `apps/uploads` tidak perlu tahu apa pun tentang
    # import: lampiran menanyakan induknya, dan induknya menjawab.
    own_answer = getattr(model, "readable_for", None)

    if callable(own_answer):
        return own_answer(user)

    declaration = declared_authority(model)

    if declaration is None:
        return None

    manager = getattr(model, "objects", None)

    if manager is None:
        return None

    queryset = manager.all()

    if any(field.name == "is_deleted" for field in model._meta.get_fields()):
        queryset = queryset.filter(is_deleted=False)

    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()

    if getattr(user, "is_superuser", False):
        return queryset

    permission = None

    # WHAT — hanya untuk resource yang memang dijaga bacanya. Yang
    # tidak dijaga tetap terbuka, dan itu keadaan yang benar untuk
    # sekarang: penjagaan baca diluncurkan satu resource demi satu
    # resource, dan lapisan ini tidak boleh mendahuluinya.
    if declaration["gated"] and getattr(
        settings, "ENFORCE_VIEW_PERMISSIONS", True
    ):
        permission = view_permission_for(model)

        if permission and not user.has_perm(permission):
            return queryset.none()

    # WHERE
    if declaration["scope"]:
        queryset = DataScopeService.filter(
            queryset,
            declaration["scope"],
            user,
            required_permission=permission,
        )

    # WHICH
    if declaration["subject"]:
        from apps.hr.api.employee.visibility import EmployeeDataVisibility
        from apps.hr.models import Employee

        allowed = EmployeeDataVisibility.visible_employees_q(
            subject=declaration["subject"],
            user=user,
        )

        if allowed is not None:
            queryset = queryset.filter(**{
                f"{declaration['subject_path']}__in":
                    Employee.objects.filter(allowed),
            })

    return queryset
