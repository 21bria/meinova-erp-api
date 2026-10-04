"""
Siapa boleh membuka sebuah berkas.

Keputusan
---------
**Berkas tidak memiliki otoritasnya sendiri.** Yang menentukan boleh
tidaknya sebuah lampiran dibuka adalah **record bisnis yang
menunjuknya** — dokumen pegawai, catatan medis, izin kehadiran, job
import. Mengetahui id, UUID, nama berkas, atau path penyimpanannya
bukan otoritas.

Sebelum ini `/api/uploads/` cuma `IsAuthenticated` dengan queryset
`UploadedFile.objects.active()` tanpa penyaringan apa pun: di tenant
peragaan **22 berkas terbaca seluruh 30 akun**, dan `download/`
melayani siapa pun yang memegang `public_id` — yang dibagikan endpoint
daftarnya sendiri. Penemuan itu sendiri informasi yang harus dijaga.

Bagaimana induknya ditemukan
----------------------------
Dari ORM, bukan dari daftar yang ditulis tangan: tiap field yang
menunjuk `UploadedFile` ditemukan lewat `_meta`. Jadi model baru yang
melampirkan berkas ikut terjaga sejak baris pertamanya ada — tanpa
seorang pun harus ingat memperbarui berkas ini. Yang sebaliknya —
daftar manual — akan gagal ke arah yang paling berbahaya: model yang
lupa didaftarkan bukan "tidak bisa dibaca", melainkan "tidak punya
induk", dan berkasnya jatuh ke aturan lain.

**Tujuh dari sembilan referensi memakai `related_name="+"`**, jadi
relasi baliknya tidak ada sama sekali; `berkas.employeedocument` bukan
atribut. Karena itu induknya dicari dari sisi bisnisnya
(`EmployeeDocument.objects.filter(uploaded_file=...)`), bukan dari sisi
berkasnya. Itu juga sebabnya tidak ada schema change di sini: yang
kurang cuma accessor-nya, bukan relasinya.

Otoritas induknya sendiri **tidak ditulis ulang di sini**.
`framework.authority.readable_queryset()` menjawabnya dari deklarasi
viewset model itu — izin, cakupan, dan kelompok data sekaligus — atau,
untuk model yang tidak dilayani viewset, dari `readable_for(user)`
milik model itu sendiri. Modul ini karena itu tidak tahu apa-apa
tentang HR, import, payroll, atau nama role mana pun, dan memang tidak
boleh tahu: **tidak ada satu pun nama model bisnis di berkas ini.**

Dua aturan, dan yang kedua yang perlu dibaca pelan
--------------------------------------------------
1. **Tertaut** → boleh dibaca kalau induknya boleh dibaca.
2. **Belum tertaut** → hanya pengunggahnya, dan hanya selama ia memang
   belum tertaut. Begitu berkasnya menempel ke record bisnis,
   otoritas record itulah yang berlaku — aturan sementara ini **tidak**
   jadi pintu belakang permanen bagi pengunggah.

Kalau satu berkas ditunjuk **lebih dari satu** induk, seluruhnya harus
boleh dibaca. Skema hari ini mengizinkan keadaan itu (tujuh
`OneToOneField` di model yang berbeda-beda menunjuk tabel yang sama),
meski datanya belum pernah memilikinya — nol berkas berinduk ganda di
tenant peragaan. Aturan "cukup satu induk yang boleh" akan membuat
induk yang paling longgar **menurunkan derajat** berkas yang menempel
di tempat paling rahasia: satu berkas yang juga terlampir di catatan
pelatihan akan terbaca meski catatan medisnya tertutup. Karena itu
yang dipakai irisannya, bukan gabungannya. Kalau suatu saat ada kasus
bisnis yang sah untuk berbagi satu berkas lintas konteks, aturan ini
yang harus diubah — sadar, bukan diam-diam.
"""

from __future__ import annotations

from django.db.models import Q


class FileAccessService:
    """Otoritas baca berkas, diturunkan dari induknya."""

    # ------------------------------------------------------------------
    # Peta referensi
    # ------------------------------------------------------------------

    @staticmethod
    def references() -> list[tuple]:
        """
        `[(model, nama_field)]` untuk tiap field yang menunjuk
        `UploadedFile`. Ditemukan dari `_meta`, bukan didaftar tangan.
        """
        from django.apps import apps

        from apps.uploads.models import UploadedFile

        found = []

        for model in apps.get_models():
            for field in model._meta.get_fields():
                if not getattr(field, "concrete", False):
                    continue

                if getattr(field, "related_model", None) is not UploadedFile:
                    continue

                found.append((model, field.name))

        return found

    # ------------------------------------------------------------------
    # Penyaringan
    # ------------------------------------------------------------------

    @classmethod
    def readable(cls, queryset, user):
        """
        Menyaring queryset `UploadedFile` ke yang boleh dibaca `user`.

        **Satu jalur untuk daftar dan untuk satu berkas.** `can_read()`
        memanggil fungsi ini juga, jadi tidak mungkin ada berkas yang
        tidak muncul di daftar tapi tetap bisa diunduh — kegagalan yang
        justru paling sering terjadi kalau keduanya ditulis terpisah.
        """
        from apps.framework.authority import readable_queryset

        if user is None or not getattr(user, "is_authenticated", False):
            return queryset.none()

        if getattr(user, "is_superuser", False):
            return queryset

        attached = Q(pk__in=[])
        allowed = Q(pk__in=[])
        blocked = Q(pk__in=[])

        for model, field_name in cls.references():
            linked = model.objects.filter(**{f"{field_name}__isnull": False})

            if any(
                field.name == "is_deleted" for field in model._meta.get_fields()
            ):
                linked = linked.filter(is_deleted=False)

            column = f"{field_name}_id"

            attached |= Q(pk__in=linked.values(column))

            parents = readable_queryset(model, user)

            if parents is None:
                # Tidak ada viewset = tidak ada aturan baca yang bisa
                # diturunkan. Ditutup, bukan dibuka.
                blocked |= Q(pk__in=linked.values(column))

                continue

            allowed |= Q(pk__in=parents.filter(
                **{f"{field_name}__isnull": False},
            ).values(column))

            blocked |= Q(pk__in=linked.exclude(
                pk__in=parents.values("pk"),
            ).values(column))

        # Berkas yang belum tertaut ke record mana pun: hanya
        # pengunggahnya, dan hanya selama itu. `~attached` yang membuat
        # aturan sementara ini berhenti berlaku sendiri begitu
        # berkasnya menempel — bukan penanda terpisah yang bisa lupa
        # dimatikan.
        own_draft = ~attached & Q(uploaded_by_id=user.pk)

        return queryset.filter(allowed | own_draft).exclude(blocked)

    # ------------------------------------------------------------------
    # Putusan
    # ------------------------------------------------------------------

    @classmethod
    def can_read(cls, user, uploaded_file) -> bool:
        """Boleh membuka isi berkas ini?"""
        from apps.uploads.models import UploadedFile

        if uploaded_file is None:
            return False

        return cls.readable(
            UploadedFile.objects.filter(pk=uploaded_file.pk),
            user,
        ).exists()

    @classmethod
    def can_download(cls, user, uploaded_file) -> bool:
        """
        Sama dengan `can_read`, dan sengaja bukan alias.

        Dinilai ulang **saat request unduh**, bukan diwarisi dari
        daftar yang dibuka semenit lalu: yang berubah di antaranya —
        role dicabut, dokumennya dihapus — harus berlaku pada unduhan
        berikutnya.
        """
        return cls.can_read(user, uploaded_file)

    @classmethod
    def can_write(cls, user, uploaded_file) -> bool:
        """
        Boleh **mengganti atau menghapus** berkas ini?

        Baca tidak otomatis berarti tulis, dan itu bukan kehati-hatian
        yang berlebihan: `uploaded_file` adalah `OneToOneField`
        ber-`on_delete=PROTECT` di tujuh model, jadi mengganti berkasnya
        mengubah isi dokumen orang lain tanpa menyentuh dokumennya.

        Yang **tidak** dilakukan di sini: menurunkan izin mutasi record
        induknya (`change_employeedocument` dan seterusnya). Itu perlu
        keputusan tersendiri — sebagian induk belum punya viewset,
        sebagian punya izin tulis yang tidak sepadan — dan menebaknya
        berarti menciptakan semantik izin baru. Selama itu belum
        diputuskan, yang berlaku aturan paling sempit yang jelas
        benar: **hanya berkas yang belum tertaut, dan hanya oleh
        pengunggahnya.** Berkas yang sudah menempel ke record bisnis
        tidak bisa diganti atau dihapus lewat `/api/uploads/` sama
        sekali; jalurnya lewat layar record itu.
        """
        from apps.uploads.models import UploadedFile

        if uploaded_file is None:
            return False

        if user is None or not getattr(user, "is_authenticated", False):
            return False

        if getattr(user, "is_superuser", False):
            return True

        if cls.is_attached(uploaded_file):
            return False

        return uploaded_file.uploaded_by_id == getattr(user, "pk", None)

    @classmethod
    def is_attached(cls, uploaded_file, *, exclude=None) -> bool:
        """
        Sudah ditunjuk setidaknya satu record bisnis?

        `exclude` mengeluarkan satu record dari perhitungan — dipakai
        saat menyunting dokumen yang **sudah** memegang berkas itu.
        Tanpa itu, menyimpan ulang dokumen tanpa mengganti lampirannya
        akan ditolak oleh aturannya sendiri.
        """
        for model, field_name in cls.references():
            queryset = model.objects.filter(
                **{field_name: uploaded_file},
            )

            if any(
                field.name == "is_deleted" for field in model._meta.get_fields()
            ):
                queryset = queryset.filter(is_deleted=False)

            if (
                exclude is not None
                and isinstance(exclude, model)
                and exclude.pk is not None
            ):
                queryset = queryset.exclude(pk=exclude.pk)

            if queryset.exists():
                return True

        return False

    # ------------------------------------------------------------------
    # Boleh ditempelkan ke dokumen?
    # ------------------------------------------------------------------

    @classmethod
    def attachment_problem(
        cls,
        *,
        uploaded_file,
        user,
        parent=None,
    ) -> str | None:
        """
        Alasan berkas ini **tidak** boleh ditempel — atau `None` kalau boleh.

        Satu aturan untuk seluruh modul, dan sengaja di sini bersama
        `can_read`/`can_write`: menempelkan berkas ke dokumen
        **memberikan hak baca** kepada semua orang yang boleh membaca
        dokumen itu (lihat `readable`). Jadi "boleh menempel" adalah
        pertanyaan otorisasi, bukan pertanyaan bentuk data, dan
        jawabannya tidak boleh tinggal di masing-masing serializer.

        Lubang yang ditutup, terbukti di tenant demo 17 Sep 2026: id
        `UploadedFile` berurutan dan mudah ditebak, dan draf milik siapa
        pun — termasuk superuser — bisa ditempel ke cuti sendiri oleh
        keempat jenis aktor. Yang menempel langsung mendapat hak baca,
        dan pengunggahnya kehilangan hak tulis atas berkasnya sendiri
        (`can_write` menolak berkas yang sudah tertaut).

        Tiga syarat, dan ketiganya menjawab hal yang berbeda:

        1. **Aktif** — berkas yang sudah dihapus tidak dihidupkan lagi
           dengan menempelkannya.
        2. **Milik yang menempel** — `uploaded_by` harus orangnya
           sendiri. **Tidak ada pengecualian HR**: kalau nanti HR memang
           perlu menempelkan berkas orang lain, itu kemampuan yang
           dinyatakan sendiri, bukan efek samping dari jabatan.
        3. **Belum dipakai dokumen lain** — kedua field yang dijaga
           (`EmployeeLeave.uploaded_file`, `AttendancePermission.
           supporting_document`) `OneToOneField`, jadi satu berkas satu
           dokumen memang sudah semantiknya.

        Superuser dilewatkan, sama seperti `can_write`: akun sistem
        memang jalur pemulihan, dan menutupnya di sini tidak menambah
        keamanan bagi siapa pun.
        """
        if uploaded_file is None:
            return None

        if user is None or not getattr(user, "is_authenticated", False):
            return (
                "Lampiran hanya bisa ditempelkan oleh akun yang "
                "mengunggahnya."
            )

        if getattr(user, "is_superuser", False):
            return None

        if getattr(uploaded_file, "is_deleted", False):
            return "Berkas ini sudah dihapus, jadi tidak bisa dilampirkan."

        if uploaded_file.uploaded_by_id != getattr(user, "pk", None):
            return (
                "Lampiran harus berkas yang Anda unggah sendiri. "
                "Unggah ulang dokumennya dari layar ini."
            )

        if cls.is_attached(uploaded_file, exclude=parent):
            return (
                "Berkas ini sudah dipakai dokumen lain. Unggah salinan "
                "tersendiri untuk dokumen ini."
            )

        return None

    @classmethod
    def can_attach(cls, user, uploaded_file, *, parent=None) -> bool:
        return cls.attachment_problem(
            uploaded_file=uploaded_file,
            user=user,
            parent=parent,
        ) is None
