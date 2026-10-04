"""
Service bagan akun.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q

from apps.core.services.master import BaseMasterService
from apps.finance.models import Account, JournalLine


class AccountService(BaseMasterService):
    model = Account

    @staticmethod
    def list():
        return (
            Account.objects
            .filter(is_deleted=False)
            .select_related("company", "parent", "default_currency")
            .order_by("company_id", "code")
        )

    # ------------------------------------------------------------------
    # Jalur materialisasi
    # ------------------------------------------------------------------

    @classmethod
    def after_create(cls, *, instance, user=None, **kwargs):
        cls._materialize(instance)

        return instance

    @classmethod
    def after_update(cls, *, instance, user=None, **kwargs):
        cls._materialize(instance)

        return instance

    @classmethod
    def _materialize(cls, account: Account) -> None:
        """
        Menulis ulang `path`/`level` baris ini **dan seluruh
        keturunannya**.

        Keturunannya ikut karena memindahkan "Beban Usaha" ke induk lain
        mengubah jalur setiap akun di bawahnya; kalau tidak ikut,
        laporan "seluruh beban di bawah X" diam-diam kehilangan cabang
        yang baru saja dipindah — dan yang hilang justru cabang yang
        barusan disentuh orang.
        """
        old_path = account.path

        account.path = account.build_path()
        account.level = max(account.path.strip("/").count("/"), 0)

        Account.objects.filter(pk=account.pk).update(
            path=account.path,
            level=account.level,
        )

        if not old_path or old_path == account.path:
            return

        # Keturunan dikenali lewat jalur **lama**. Satu query untuk
        # seluruh cabang, bukan rekursi per baris.
        descendants = (
            Account.objects
            .filter(path__startswith=old_path)
            .exclude(pk=account.pk)
            .order_by("level")
        )

        for child in descendants:
            child.path = account.path + child.path[len(old_path):]
            child.level = max(child.path.strip("/").count("/"), 0)

            Account.objects.filter(pk=child.pk).update(
                path=child.path,
                level=child.level,
            )

    # ------------------------------------------------------------------
    # Penghapusan
    # ------------------------------------------------------------------

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        """
        Dua hal yang membuat sebuah akun tidak boleh dihapus, dan
        keduanya menolak dengan menyebut jumlahnya — "tidak bisa
        dihapus" tanpa angka memaksa orang menebak apa yang harus
        dibereskan lebih dulu.
        """
        children = (
            Account.objects
            .filter(parent=instance, is_deleted=False)
            .count()
        )

        if children:
            raise ValidationError({
                "parent": (
                    f"Akun ini masih menaungi {children} akun. Pindahkan "
                    "atau hapus dulu akun di bawahnya."
                ),
            })

        used = (
            JournalLine.objects
            .filter(account=instance, is_deleted=False)
            .count()
        )

        if used:
            raise ValidationError({
                "account": (
                    f"Akun ini sudah dipakai di {used} baris jurnal dan "
                    "tidak bisa dihapus — riwayat pembukuan tidak boleh "
                    "kehilangan nama perkiraannya. Nonaktifkan saja "
                    "lewat 'Active'."
                ),
            })

    # ------------------------------------------------------------------
    # Pohon
    # ------------------------------------------------------------------

    @classmethod
    def tree(cls, queryset=None) -> list[dict]:
        """
        Bagan akun sebagai pohon bersarang, **satu query**.

        Disusun di Python dari satu daftar rata, bukan lewat rekursi
        yang menanyakan anak per simpul: bagan akun sebuah perusahaan
        besar berisi ribuan baris, dan satu query per simpul berarti
        ribuan query untuk satu layar.
        """
        rows = list(
            (queryset if queryset is not None else cls.list())
            .annotate(
                journal_line_count=Count(
                    "journal_lines",
                    filter=Q(journal_lines__is_deleted=False),
                ),
            )
        )

        nodes: dict[int, dict] = {}

        for account in rows:
            nodes[account.pk] = {
                "id": account.pk,
                "code": account.code,
                "name": account.name,
                "label": f"{account.code} — {account.name}",
                "parent": account.parent_id,
                "account_type": account.account_type,
                "account_category": account.account_category,
                "normal_balance": account.effective_normal_balance,
                "posting_allowed": account.posting_allowed,
                "control_account": account.control_account,
                "reconciliation_required": account.reconciliation_required,
                "is_active": account.is_active,
                "level": account.level,
                "sort_order": account.sort_order,
                "has_entries": account.journal_line_count > 0,
                "children": [],
            }

        roots: list[dict] = []

        for account in rows:
            node = nodes[account.pk]

            parent = nodes.get(account.parent_id)

            # Induk yang tidak ada di daftar ini — karena tersaring
            # cakupan data, atau karena sudah dihapus — membuat simpulnya
            # naik jadi akar alih-alih hilang. Baris yang menghilang dari
            # pohon tanpa pesan adalah bagan akun yang terbaca seperti
            # data yang belum lengkap.
            if parent is None:
                roots.append(node)
            else:
                parent["children"].append(node)

        def sort(items: list[dict]) -> None:
            items.sort(key=lambda item: (item["sort_order"], item["code"]))

            for item in items:
                sort(item["children"])

        sort(roots)

        return roots

    # ------------------------------------------------------------------
    # Pemakaian oleh jurnal
    # ------------------------------------------------------------------

    @classmethod
    def assert_postable(cls, account: Account, *, company_id=None) -> None:
        """
        Pemeriksaan yang sama dengan `JournalLine.clean()`, dipanggil
        jalur yang tidak lewat `full_clean()` — importer, seed, dan
        penerbitan jurnal dari kejadian akuntansi.

        Sengaja duplikat **pesan**, bukan duplikat aturan: keduanya
        memanggil pemeriksaan yang sama lewat model, dan yang berbeda
        cuma tempat kesalahannya dilaporkan.
        """
        if account.is_deleted or not account.is_active:
            raise ValidationError({
                "account": f"Akun '{account.code}' sudah tidak aktif.",
            })

        if not account.posting_allowed:
            raise ValidationError({
                "account": (
                    f"'{account.code} — {account.name}' adalah akun grup "
                    "dan tidak menerima jurnal."
                ),
            })

        if company_id is not None and account.company_id != company_id:
            raise ValidationError({
                "account": (
                    f"Akun '{account.code}' milik perusahaan lain."
                ),
            })

    @classmethod
    @transaction.atomic
    def rebuild_tree(cls, *, company_id: int | None = None) -> int:
        """
        Membangun ulang `path`/`level` seluruh bagan akun.

        Dipakai perintah manajemen dan sesudah impor massal. Diurutkan
        dari akar ke bawah supaya induk selalu sudah punya jalurnya saat
        anaknya dihitung.
        """
        queryset = Account.objects.all()

        if company_id is not None:
            queryset = queryset.filter(company_id=company_id)

        pending = list(queryset.order_by("parent_id", "pk"))

        resolved: dict[int, str] = {}
        touched = 0

        # Beberapa lintasan, bukan rekursi: tiap lintasan menyelesaikan
        # semua simpul yang induknya sudah selesai. Berhenti sendiri
        # kalau ada rantai berputar — barisnya tertinggal, dan itu yang
        # dilaporkan, bukan proses yang menggantung.
        while pending:
            progressed = False
            remaining = []

            for account in pending:
                if account.parent_id is None:
                    path = f"/{account.pk}/"
                elif account.parent_id in resolved:
                    path = f"{resolved[account.parent_id]}{account.pk}/"
                else:
                    remaining.append(account)

                    continue

                resolved[account.pk] = path

                level = max(path.strip("/").count("/"), 0)

                if account.path != path or account.level != level:
                    Account.objects.filter(pk=account.pk).update(
                        path=path,
                        level=level,
                    )

                    touched += 1

                progressed = True

            if not progressed:
                raise ValidationError({
                    "parent": (
                        f"{len(remaining)} akun tidak bisa dihitung "
                        "jalurnya — ada rantai induk yang berputar. "
                        f"Id: {[a.pk for a in remaining[:10]]}"
                    ),
                })

            pending = remaining

        return touched
