"""
Menyalin satu baris master ke perusahaan lain.

Cakupan sebagian besar master di sistem ini memang **per company** —
kalender kerja, hari libur, aturan kehadiran, jatah cuti, deret nomor.
Itu keputusan yang benar: dua belas perusahaan dalam satu tenant memang
boleh berbeda. Tapi kenyataannya mereka lebih sering **sama**, dan
tanpa cara menyalin, menyiapkan tenant baru berarti mengetik angka yang
sama dua belas kali — lalu satu di antaranya salah ketik, dan tidak ada
yang menyadarinya sampai payroll bulan depan.

Yang **tidak** dilakukan di sini: mengubah konsep cakupannya. Tidak ada
"aturan lintas company", tidak ada pewarisan. Barisnya tetap satu per
perusahaan, tetap bisa disunting sendiri-sendiri sesudahnya. Yang
ditambahkan cuma cara membuatnya tanpa mengetik ulang.

Cara pakai
----------
Di service::

    class WorkCalendarService(CompanyCopyMixin, BaseMasterService):
        model = WorkCalendar
        copy_rule_fields = ["monday", "tuesday", ..., "is_default"]

Di viewset::

    class WorkCalendarViewSet(CompanyCopyViewSetMixin, BaseMasterViewSet):
        ...

Lalu satu `action.custom(...)` di schema-nya. Tidak ada lagi yang perlu
ditulis: pemetaan lokasi, kode unik, dan aturan "yang sudah ada
dilewati" sudah di sini.
"""

from __future__ import annotations

from django.db import transaction

from rest_framework.decorators import action as drf_action

from apps.core.responses.api import error_response, success_response


class CompanyCopyMixin:
    """
    Untuk `BaseMasterService` turunan yang modelnya punya FK `company`.
    """

    # Kolom yang isinya **disalin apa adanya**. Sasaran (company,
    # location, …), `code`, dan `name` tidak masuk sini — itu yang
    # justru berubah di salinannya.
    copy_rule_fields: list[str] = []

    # Kolom yang menentukan **untuk siapa** baris ini berlaku. Dipakai
    # dua hal: memetakan lokasi ke padanannya di company tujuan, dan
    # memeriksa apakah sasaran yang sama sudah punya barisnya sendiri.
    copy_scope_fields: list[str] = ["company", "location", "employee_group"]

    copy_code_field: str | None = "code"
    copy_name_field: str | None = "name"

    # Tabel anak yang ikut tersalin. Tanpa ini, master yang isinya
    # justru ada di barisnya — `RosterPolicy` dan tabel Travel Days by
    # POH-nya — menghasilkan salinan yang **kosong di bagian yang paling
    # penting**, dan gagalnya diam: jadwalnya tetap terbit, cuma tanpa
    # satu pun segmen travel.
    #
    # Bentuknya::
    #
    #     copy_children = [
    #         {
    #             "relation": "travel_days",     # related_name di induk
    #             "parent_field": "policy",      # FK balik di anaknya
    #             "fields": ["point_of_hire", "travel_out_days", ...],
    #         },
    #     ]
    #
    # Yang **tidak** boleh masuk sini: tabel penghitung. `DocumentSeries`
    # menyimpan nomor terakhir yang sudah terpakai, dan menyalinnya
    # berarti perusahaan baru memulai deretnya dari nomor milik
    # perusahaan lain.
    copy_children: list[dict] = []

    # Nilai yang **selalu** ditulis di salinannya, menimpa nilai sumber.
    # Untuk kolom yang tidak boleh ikut apa adanya: penghitung yang
    # harus mulai dari nol, atau status yang harus dibaca orang dulu
    # sebelum berlaku.
    copy_overrides: dict = {}

    # ------------------------------------------------------------------
    # Bantuan
    # ------------------------------------------------------------------

    @classmethod
    def _has_field(cls, name: str) -> bool:
        return any(
            field.name == name
            for field in cls.model._meta.get_fields()
        )

    @classmethod
    def _unique_code(cls, base: str) -> str:
        """
        Kode unik untuk salinannya.

        Hampir semua master ini menjaga `code` lewat UniqueConstraint,
        dan bentrok di sana gagal sebagai IntegrityError yang tidak
        menempel di kolom mana pun — pemakainya cuma melihat "gagal
        menyalin" tanpa tahu sebabnya.
        """
        field = cls.model._meta.get_field(cls.copy_code_field)

        limit = getattr(field, "max_length", None) or 50

        candidate = base[:limit]

        suffix = 2

        while cls.model.objects.filter(
            **{cls.copy_code_field: candidate},
            is_deleted=False,
        ).exists():
            tail = f"-{suffix}"

            candidate = f"{base[:limit - len(tail)]}{tail}"

            suffix += 1

        return candidate

    @staticmethod
    def _target_location(source_location, company):
        """
        Lokasi padanan di company tujuan, dicocokkan lewat **jenisnya**.

        Kodenya sengaja tidak dipakai sebagai kunci: kode hanya unik per
        company, dan tiap klien menamainya sendiri — "JKT" di satu
        perusahaan bisa "HO-JKT" di sebelahnya. Yang stabil lintas
        perusahaan adalah `LocationType`.

        Mengembalikan `(location, alasan_gagal)`. Yang tidak ketemu atau
        justru ketemu lebih dari satu **tidak ditebak** — baris master
        yang mendarat di lokasi yang salah tidak berbunyi sampai ada
        yang memeriksa akibatnya.
        """
        from apps.administration.models import Location

        if source_location is None:
            return None, None

        type_id = source_location.location_type_id

        if type_id is None:
            return None, (
                f"lokasi sumber ({source_location.name}) belum punya "
                f"Location Type, jadi padanannya tidak bisa dicari"
            )

        matches = list(
            Location.objects.filter(
                company=company,
                location_type_id=type_id,
                is_deleted=False,
            )[:2]
        )

        type_name = source_location.location_type.name

        if not matches:
            return None, f"tidak punya lokasi bertipe {type_name}"

        if len(matches) > 1:
            return None, (
                f"punya lebih dari satu lokasi bertipe {type_name} — "
                f"pilih sendiri lokasinya"
            )

        return matches[0], None

    @classmethod
    def _target_scope(cls, instance, company):
        """
        Nilai sasaran untuk salinannya: `(dict, alasan_gagal)`.

        `company` diganti tujuannya, `location` dipetakan lewat
        jenisnya, sisanya (mis. `employee_group`) ikut apa adanya —
        golongan pegawai adalah master global, jadi tidak perlu
        dipetakan.
        """
        scope: dict = {}

        for name in cls.copy_scope_fields:
            if not cls._has_field(name):
                continue

            if name == "company":
                scope["company"] = company

                continue

            if name == "location":
                location, reason = cls._target_location(
                    getattr(instance, "location", None),
                    company,
                )

                if reason:
                    return {}, reason

                scope["location"] = location

                continue

            # Sisanya boleh berupa relasi (`employee_group`, `role`)
            # maupun kolom biasa (`action_type`, `subject`). Yang kedua
            # penting: di beberapa master, identitas satu barisnya
            # bukan cuma sasarannya tapi juga **untuk hal apa** — dan
            # tanpa ikut diperiksa, "sudah punya baris untuk sasaran
            # yang sama" akan menolak salinan yang sebenarnya beda
            # urusan.
            field = cls.model._meta.get_field(name)

            if field.is_relation:
                scope[f"{name}_id"] = getattr(instance, f"{name}_id", None)
            else:
                scope[name] = getattr(instance, name, None)

        return scope, None

    @classmethod
    def _copy_children(cls, *, source, target, user=None) -> dict:
        """
        Menyalin tabel anak, mengembalikan `{relation: jumlah}`.

        Jumlahnya ikut dilaporkan ke pemanggil supaya "policy tersalin
        tapi tabel POH-nya kosong" terlihat di pesannya, bukan baru
        ketahuan saat ada yang membuka salinannya.
        """
        return cls._copy_relations(
            specs=cls.copy_children,
            source=source,
            target=target,
            user=user,
        )

    @classmethod
    def _copy_relations(cls, *, specs, source, target, user=None) -> dict:
        """
        Menyalin satu tingkat anak, lalu turun ke cucunya lewat kunci
        `children` pada spec.

        Bersarang karena kebutuhannya memang bersarang: `WorkflowStep`
        membawa rantai `WorkflowStepFallback`, dan step tanpa rantainya
        adalah lubang yang persis sama bentuknya dengan policy tanpa
        tabel POH — salinannya jadi, cuma kehilangan justru bagian yang
        menanganinya saat struktur organisasi tujuan belum lengkap.
        """
        counts: dict = {}

        for spec in specs:
            relation = spec["relation"]

            parent_field = spec["parent_field"]

            rows = getattr(source, relation).filter(is_deleted=False)

            written = 0

            for row in rows:
                values = {}

                for name in spec["fields"]:
                    field = row._meta.get_field(name)

                    if field.is_relation:
                        values[f"{name}_id"] = getattr(row, f"{name}_id")
                    else:
                        values[name] = getattr(row, name)

                values[parent_field] = target

                child = row.__class__(**values)

                if user is not None:
                    child.created_by = user
                    child.updated_by = user

                child.full_clean()
                child.save()

                written += 1

                for key, value in cls._copy_relations(
                    specs=spec.get("children") or [],
                    source=row,
                    target=child,
                    user=user,
                ).items():
                    counts[key] = counts.get(key, 0) + value

            counts[relation] = counts.get(relation, 0) + written

        return counts

    # ------------------------------------------------------------------
    # Salin
    # ------------------------------------------------------------------

    @classmethod
    def copy_preview(cls, *, instance, company) -> tuple[bool, str | None]:
        """
        Boleh disalin ke company ini atau tidak, plus alasannya.

        Dipakai daftar tujuan supaya penolakannya datang **sebelum**
        tombolnya ditekan. Daftar yang membiarkan semuanya bisa dipilih
        lalu menolak separuhnya membuat orang mengulang pekerjaannya.
        """
        scope, reason = cls._target_scope(instance, company)

        if reason:
            return False, reason

        if cls.model.objects.filter(is_deleted=False, **scope).exists():
            return False, "sudah punya baris untuk sasaran yang sama"

        return True, None

    @classmethod
    @transaction.atomic
    def copy_to_companies(
        cls,
        *,
        instance,
        company_ids: list,
        user=None,
    ) -> dict:
        """
        Menyalin ke beberapa company sekaligus.

        Yang gagal **tidak membatalkan yang berhasil**: tiap company
        berdiri sendiri, dan alasannya dikembalikan per baris. Menyalin
        ke dua belas perusahaan lalu membatalkan semuanya karena satu di
        antaranya belum punya lokasi yang cocok berarti pekerjaan
        sebelas perusahaan lain hilang tanpa sebab yang mereka lakukan.
        """
        from apps.administration.models import Company

        companies = (
            Company.objects
            .filter(pk__in=company_ids, is_deleted=False)
            .order_by("code")
        )

        created = []
        skipped = []

        for company in companies:
            scope, reason = cls._target_scope(instance, company)

            if reason:
                skipped.append({"company": company.name, "reason": reason})

                continue

            if cls.model.objects.filter(is_deleted=False, **scope).exists():
                skipped.append(
                    {
                        "company": company.name,
                        "reason": "sudah punya baris untuk sasaran yang sama",
                    },
                )

                continue

            payload = {
                name: getattr(instance, name)
                for name in cls.copy_rule_fields
                if cls._has_field(name)
            }

            payload.update(scope)

            if cls.copy_code_field and cls._has_field(cls.copy_code_field):
                source_code = getattr(instance, cls.copy_code_field)

                payload[cls.copy_code_field] = cls._unique_code(
                    f"{source_code}-{company.code}",
                )

            if cls.copy_name_field and cls._has_field(cls.copy_name_field):
                field = cls.model._meta.get_field(cls.copy_name_field)

                limit = getattr(field, "max_length", None) or 150

                source_name = getattr(instance, cls.copy_name_field)

                payload[cls.copy_name_field] = (
                    f"{source_name} — {company.name}"[:limit]
                )

            payload.update(cls.copy_overrides)

            copy = cls.model(**payload)

            if user is not None:
                copy.created_by = user
                copy.updated_by = user

            copy.full_clean()
            copy.save()

            children = cls._copy_children(
                source=instance,
                target=copy,
                user=user,
            )

            created.append(
                {
                    "id": copy.pk,
                    "code": getattr(copy, "code", None),
                    "company": company.name,
                    "location": getattr(
                        getattr(copy, "location", None),
                        "name",
                        None,
                    ),
                    "children": children,
                },
            )

        return {"created": created, "skipped": skipped}


class CompanyCopyViewSetMixin:
    """
    Dua endpoint untuk viewset yang service-nya memakai
    `CompanyCopyMixin`.
    """

    @drf_action(detail=True, methods=["get"], url_path="copy-targets")
    def copy_targets(self, request, pk=None):
        """
        Company tujuan yang mungkin, lengkap dengan yang **dimatikan
        beserta alasannya**.

        Yang tidak bisa disalin tetap ditampilkan, bukan dibuang dari
        daftar: daftar yang menyembunyikannya membuat orang mengira
        perusahaan itu belum pernah disiapkan, lalu mencarinya di
        tempat lain.
        """
        from apps.administration.models import Company

        instance = self.get_object()

        rows = []

        for company in (
            Company.objects
            .filter(is_deleted=False)
            .exclude(pk=getattr(instance, "company_id", None))
            .order_by("code")
        ):
            allowed, reason = self.service_class.copy_preview(
                instance=instance,
                company=company,
            )

            rows.append(
                {
                    "value": company.pk,
                    "label": (
                        company.name
                        if allowed
                        else f"{company.name} — {reason}"
                    ),
                    "already_copied": not allowed,
                },
            )

        return success_response(
            data=rows,
            message="Daftar company tujuan.",
        )

    @drf_action(detail=True, methods=["post"], url_path="copy-to-companies")
    def copy_to_companies(self, request, pk=None):
        instance = self.get_object()

        raw = request.data.get("company_ids") or []

        if not isinstance(raw, (list, tuple)):
            raw = [raw]

        company_ids = [value for value in raw if str(value).isdigit()]

        if not company_ids:
            return error_response(
                message="Pilih minimal satu company tujuan.",
                status_code=400,
            )

        result = self.service_class.copy_to_companies(
            instance=instance,
            company_ids=company_ids,
            user=request.user,
        )

        parts = [f"{len(result['created'])} baris disalin."]

        # Jumlah baris anak ikut disebut: salinan yang induknya jadi tapi
        # tabel anaknya kosong terbaca sebagai berhasil sepenuhnya, dan
        # yang kosong itu justru isi utamanya.
        totals: dict = {}

        for row in result["created"]:
            for relation, count in (row.get("children") or {}).items():
                totals[relation] = totals.get(relation, 0) + count

        for relation, count in totals.items():
            parts.append(f"{count} baris {relation}.")

        for row in result["skipped"]:
            parts.append(f"{row['company']}: {row['reason']}.")

        return success_response(data=result, message=" ".join(parts))
