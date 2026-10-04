"""
Izin tulis per resource, untuk dibaca frontend.

Penjagaannya sendiri sudah lama ada (`ModelPermission`), tapi layarnya
tidak pernah tahu: tidak satu pun modul hasil generate memakai
`useAccess()`, jadi pegawai tetap melihat tombol **Add** dan **Edit**
yang selalu berakhir 403. Penolakannya benar, cuma diberikan setelah
orangnya mengisi seluruh form.

**Dikunci pada endpoint, bukan pada nama modul.** Yang dipegang
`CrudConfig` di frontend adalah `endpoint`; `framework_module` boleh
berbeda dari path URL-nya (lihat catatan soal `administration/security/*`
yang API-nya di bawah `/api/accounts/`), jadi memakainya sebagai kunci
akan meleset persis di modul yang paling gampang salah.

**Dihitung di backend, bukan disimpulkan frontend dari `/auth/me`.**
Dua hal yang tidak terlihat dari sana: viewset ber-`enforce_model_permissions
= False` (mis. `WorkflowDelegationViewSet`) dan saklar
`ENFORCE_MODEL_PERMISSIONS`. Kalau frontend menyimpulkannya sendiri,
tombol yang seharusnya ada justru hilang — dan hilangnya tanpa pesan.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import get_resolver

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.framework.views.master import BaseMasterViewSet


def _all_subclasses(cls):
    subclasses = []

    for subclass in cls.__subclasses__():
        subclasses.append(subclass)
        subclasses.extend(_all_subclasses(subclass))

    return subclasses


def _model_of(view_class):
    """
    Model milik sebuah viewset, **tanpa menjalankan querysetnya**.

    `ModelPermission._model` sengaja tidak dipakai di sini: ia menerima
    *instance* dan jatuh ke `get_queryset()`, sementara di sini yang ada
    cuma kelasnya. Memanggilnya pada kelas membuat `get_queryset()`
    dijalankan tanpa `self` → `TypeError` → tertangkap `except` → `None`
    untuk **semua** viewset, dan hasilnya daftar izin kosong yang
    terbaca persis seperti "semua tombol boleh".

    Tiga sumber, dari yang paling murah:
    `queryset` → `service_class.model` → `serializer_class.Meta.model`.
    Tidak satu pun menyentuh database.
    """
    queryset = getattr(view_class, "queryset", None)

    model = getattr(queryset, "model", None)

    if model is not None:
        return model

    service = getattr(view_class, "service_class", None)

    model = getattr(service, "model", None)

    if model is not None:
        return model

    serializer = getattr(view_class, "serializer_class", None)

    return getattr(getattr(serializer, "Meta", None), "model", None)


def _endpoint_of(view_class) -> str | None:
    schema = getattr(view_class, "schema", None) or {}

    endpoint = schema.get("endpoint") if isinstance(schema, dict) else None

    return str(endpoint).strip() if endpoint else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def framework_permissions_view(request):
    """
    `{"<endpoint>": {"model": ..., "create": bool, "update": bool, "delete": bool}}`

    Satu request untuk seluruh resource, bukan satu per tabel: layar
    mana pun bisa memuat beberapa tabel sekaligus, dan menembak satu
    request per tabel membuat halaman pertama jauh lebih lambat demi
    jawaban yang sama.
    """
    # `_all_subclasses` hanya menemukan kelas yang **sudah diimpor**.
    # Lewat HTTP itu selalu terpenuhi karena URLconf-nya termuat, tapi
    # pemanggil lain (shell, test, task) bisa mendapat daftar kosong —
    # dan daftar kosong di sini berarti "semua tombol boleh", persis
    # kebalikan dari yang dimaksud. Menyentuh resolver membuatnya pasti.
    get_resolver().url_patterns

    user = request.user

    enforced = getattr(settings, "ENFORCE_MODEL_PERMISSIONS", True)

    # Saklar terpisah, dibaca terpisah: mematikan penjagaan baca tidak
    # boleh ikut melaporkan tombol tulis sebagai boleh.
    read_enforced = getattr(settings, "ENFORCE_VIEW_PERMISSIONS", True)

    result: dict[str, dict] = {}

    for view_class in _all_subclasses(BaseMasterViewSet):
        endpoint = _endpoint_of(view_class)

        if not endpoint:
            continue

        model = _model_of(view_class)

        if model is None:
            continue

        meta = model._meta

        model_key = f"{meta.app_label}.{meta.model_name}"

        # Viewset yang memang tidak dijaga izin model menjawab "boleh"
        # untuk ketiganya — sama seperti yang dilakukan `ModelPermission`
        # saat request-nya benar-benar datang.
        unguarded = (
            not enforced
            or not getattr(view_class, "enforce_model_permissions", True)
        )

        def allowed(verb: str) -> bool:
            if unguarded:
                return True

            return user.has_perm(f"{meta.app_label}.{verb}_{meta.model_name}")

        # Baca ikut dilaporkan, tapi hanya untuk resource yang memang
        # dijaga bacanya (`require_view_permission`). Untuk yang lain
        # nilainya `True` — bukan karena diperiksa, melainkan karena
        # bacanya memang terbuka, dan itu jawaban yang benar untuk
        # pertanyaan yang ditanyakan frontend: "boleh saya buka layar
        # ini?"
        #
        # Tanpa ini layar payroll milik orang yang tidak berizin tetap
        # muncul di menu lalu menjawab 403 begitu dibuka — penolakan
        # yang benar, diberikan pada saat yang paling tidak berguna.
        read_guarded = (
            not unguarded
            and read_enforced
            and getattr(view_class, "require_view_permission", False)
        )

        result[endpoint] = {
            "model": model_key,
            "read": (
                user.has_perm(f"{meta.app_label}.view_{meta.model_name}")
                if read_guarded
                else True
            ),
            "create": allowed("add"),
            "update": allowed("change"),
            "delete": allowed("delete"),
        }

    return Response(result)
