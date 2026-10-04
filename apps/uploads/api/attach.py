"""
Penjagaan lampiran di batas API.

Aturannya sendiri tinggal di `FileAccessService.attachment_problem()` —
satu tempat bersama `can_read`/`can_write`, karena menempelkan berkas
memang memberi hak baca. Yang ada di sini cuma penerjemahnya ke bentuk
galat DRF, supaya pesannya menempel pada kolom yang salah isi dan bukan
pada `detail` yang tidak bisa ditunjukkan di formulir.

Dipasang di **serializer**, bukan di service: jalur turunan yang
memanggil service langsung (importir, seed, konversi presensi) tidak
memilih berkasnya dari daftar milik orang lain — yang perlu dijaga
adalah request yang menyebut id berkas.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.uploads.services.access_service import FileAccessService


def attachment_error(*, uploaded_file, user, parent=None) -> str | None:
    """Alasan penolakan, atau `None` kalau boleh ditempel."""
    return FileAccessService.attachment_problem(
        uploaded_file=uploaded_file,
        user=user,
        parent=parent,
    )


def assert_attachable(*, field: str, uploaded_file, user, parent=None) -> None:
    """Melempar `ValidationError` pada kolom `field` kalau tidak boleh."""
    problem = attachment_error(
        uploaded_file=uploaded_file,
        user=user,
        parent=parent,
    )

    if problem is None:
        return

    raise serializers.ValidationError({field: [problem]})


def guard_attachment(serializer, field: str, attrs: dict) -> None:
    """
    Versi siap pakai untuk `Serializer.validate()`.

    Mengambil pemakainya dari `context["request"]` dan dokumen induknya
    dari `serializer.instance`, jadi menyunting dokumen yang sudah
    memegang berkas itu tidak ditolak oleh aturannya sendiri.

    Tanpa `request` di context — jalur internal yang memakai serializer
    sebagai pemeriksa bentuk — tidak menjaga apa pun. Itu memang benar:
    yang dijaga di sini pilihan **pemakai**, dan di jalur itu tidak ada
    pemakai yang memilih.
    """
    if field not in attrs:
        return

    request = serializer.context.get("request")

    if request is None:
        return

    assert_attachable(
        field=field,
        uploaded_file=attrs.get(field),
        user=getattr(request, "user", None),
        parent=serializer.instance,
    )
