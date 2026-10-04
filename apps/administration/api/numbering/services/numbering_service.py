from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.administration.models import NumberingSequence, DocumentSeries
from apps.framework.services.company_copy import CompanyCopyMixin


class NumberingSequenceService(CompanyCopyMixin):
    model = NumberingSequence

    # `module` + `document_type` ikut jadi kunci sasaran, bukan cuma
    # company: satu perusahaan punya banyak deret, dan tanpa keduanya
    # menyalin deret Cuti ditolak dengan alasan "sudah punya baris untuk
    # sasaran yang sama" — padahal yang ada di sana deret Travel Request.
    copy_scope_fields = [
        "company",
        "module",
        "document_type",
    ]

    copy_rule_fields = [
        "prefix",
        "suffix",
        "separator",
        "padding",
        "year_digits",
        "reset_yearly",
        "reset_monthly",
        "is_active",
    ]

    # Penghitungnya **tidak pernah** ikut. `current_number` dan tabel
    # anak `DocumentSeries` menyimpan nomor terakhir yang sudah terpakai
    # — menyalinnya berarti perusahaan baru memulai deretnya dari nomor
    # milik perusahaan lain, dan nomor dokumen yang melompat baru
    # ketahuan setelah tercetak.
    copy_overrides = {"current_number": 0}

    copy_children: list[dict] = []

    @staticmethod
    def list():
        return NumberingSequence.objects.select_related("company").order_by(
            "module",
            "document_type",
        )


class DocumentSeriesService:
    @staticmethod
    def list():
        return DocumentSeries.objects.select_related("sequence").order_by(
            "-year",
            "-month",
        )


class DocumentNumberService:
    """
    Mengambil satu nomor berikutnya dari `NumberingSequence`.

    Nomor urutnya disimpan di `DocumentSeries`, bukan di sequence-nya:
    satu pola bisa punya beberapa deret berjalan sekaligus (2025 dan 2026
    di masa pergantian tahun), dan menaruh penghitungnya di master berarti
    reset tahunan menghapus jejak nomor terakhir tahun lalu.
    """

    @classmethod
    def resolve_sequence(
        cls,
        *,
        module: str,
        document_type: str,
        company=None,
    ) -> NumberingSequence | None:
        """
        Pola milik company dipakai lebih dulu, baru pola global.

        Company yang belum punya pola sendiri ikut pola global — itu yang
        membuat seed satu baris cukup untuk seluruh tenant, dan klien yang
        menuntut format sendiri tinggal menambah satu baris tanpa
        menyentuh yang lain.
        """
        # Sengaja Q, bukan `company__in=[company, None]`: SQL `IN (NULL)`
        # tidak pernah cocok, jadi bentuk itu diam-diam membuang pola
        # global — dan dokumennya terbit tanpa nomor.
        scope = Q(company__isnull=True)

        if company is not None:
            scope |= Q(company=company)

        candidates = (
            NumberingSequence.objects
            .filter(
                module=module,
                document_type=document_type,
                is_deleted=False,
            )
            .filter(scope)
            # Company lebih spesifik, jadi didahulukan. NULL diurutkan
            # terakhir oleh PostgreSQL pada ASC.
            .order_by("company_id")
        )

        return candidates.first()

    @classmethod
    @transaction.atomic
    def next(
        cls,
        *,
        module: str,
        document_type: str,
        company=None,
        when: date | None = None,
    ) -> str:
        """
        Mengembalikan nomor berikutnya, atau string kosong kalau pola
        untuk dokumen itu belum diseed.

        Sengaja tidak melempar error: dokumen yang tidak jadi tersimpan
        hanya karena master penomoran belum diisi adalah kegagalan yang
        salah tempat. Nomornya tetap bisa diisi tangan.
        """
        sequence = cls.resolve_sequence(
            module=module,
            document_type=document_type,
            company=company,
        )

        if sequence is None:
            return ""

        when = when or timezone.localdate()

        resets = sequence.reset_yearly or sequence.reset_monthly

        # Deret yang tidak pernah reset tetap butuh satu baris penampung;
        # tahun 0 dipakai sebagai kuncinya supaya constraint uniknya tetap
        # jalan tanpa kolom tambahan.
        year = when.year if resets else 0
        month = when.month if sequence.reset_monthly else None

        # Dikunci di baris **master**, bukan langsung di baris deret.
        #
        # Mengunci deretnya saja tidak cukup, dan kegagalannya diam:
        # baris deret dibuat lewat `get_or_create`, dan constraint
        # uniknya `(sequence, year, month)` tidak menjaga apa-apa saat
        # `month` NULL — PostgreSQL menganggap dua NULL berbeda, jadi
        # deret tanpa reset bulanan boleh punya baris kembar sebanyak
        # yang sempat dibuat. Delapan permintaan bersamaan pada deret
        # yang barisnya belum ada menghasilkan delapan baris, semuanya
        # bernomor 1 — dan nomor dokumen yang kembar baru ketahuan saat
        # constraint unik di tabel dokumennya meledak, kalau ada.
        #
        # Penguncian di master menutup jendela itu: pembuatan baris
        # deret dan penambahan angkanya jadi satu bagian yang tidak bisa
        # disela. Butirannya tetap per deret — dua dokumen dari modul
        # berbeda memakai baris master berbeda dan tidak saling
        # menunggu.
        sequence = (
            NumberingSequence.objects
            .select_for_update()
            .get(pk=sequence.pk)
        )

        series = (
            DocumentSeries.objects
            .filter(
                sequence=sequence,
                year=year,
                month=month,
            )
            # Baris kembar peninggalan sebelum penguncian ini ada tetap
            # mungkin tersisa di tenant lama. Yang tertua yang dipakai,
            # bukan yang kebetulan terbaca duluan — kalau tidak,
            # nomornya bisa mundur dari satu panggilan ke panggilan
            # berikutnya.
            .order_by("pk")
            .first()
        )

        if series is None:
            series = DocumentSeries.objects.create(
                sequence=sequence,
                year=year,
                month=month,
                last_number=0,
            )

        series.last_number += 1
        series.save(update_fields=["last_number", "updated_at"])

        # Disalin ke master hanya sebagai tampilan "nomor terakhir" di
        # layar setting. Yang jadi acuan tetap baris deret.
        NumberingSequence.objects.filter(pk=sequence.pk).update(
            current_number=series.last_number,
        )

        return cls.format(
            sequence=sequence,
            number=series.last_number,
            year=year,
            month=month,
        )

    @staticmethod
    def format(
        *,
        sequence: NumberingSequence,
        number: int,
        year: int,
        month: int | None,
    ) -> str:
        parts: list[str] = []

        if sequence.prefix:
            parts.append(sequence.prefix)

        # Tahun dua digit dipakai nomor pegawai (KW260001); empat digit
        # tetap bawaan dan itu yang dipakai seluruh deret dokumen yang
        # sudah berjalan. Dipotong dari kanan supaya 2026 → 26.
        digits = getattr(sequence, "year_digits", 4) or 4

        printable_year = str(year)[-digits:] if year else ""

        if month:
            parts.append(f"{printable_year}{month:02d}")
        elif year:
            parts.append(printable_year)

        parts.append(str(number).zfill(sequence.padding or 1))

        if sequence.suffix:
            parts.append(sequence.suffix)

        return (sequence.separator or "").join(parts)
