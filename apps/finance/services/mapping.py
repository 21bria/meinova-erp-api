"""
Penentuan akun: `mapping_key` → `Account`.

Satu aturan yang menentukan seluruh perilakunya: **pemenangnya yang
paling khusus, dan seri ditolak.** Memilih salah satu dari dua
konfigurasi yang sama-sama cocok berarti uang mendarat di akun yang
ditentukan urutan `id` — dan itu keputusan yang tidak pernah diambil
siapa pun, tidak tercatat di mana pun, dan tidak terlihat janggal di
laporan mana pun.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.core.services.master import BaseMasterService
from apps.finance.models import Account, AccountMapping


# Bobot tiap syarat. Menurun mengikuti seberapa sempit syaratnya
# mempersempit — cost center menyebut satu unit biaya, company menyebut
# seluruh perusahaan. Bentuknya sama dengan
# `WorkflowDefinition.specificity`, dan angkanya sengaja berjarak
# cukup jauh supaya kombinasi syarat lemah tidak pernah menyamai satu
# syarat kuat.
WEIGHTS = {
    "cost_center": 16,
    "department": 8,
    "location": 4,
    "company": 2,
    "event_type": 1,
}

# Bobot tiap pasangan di `selectors`. Dijumlahkan di atas yang di atas,
# jadi aturan yang menyebut `component_type` menang atas aturan yang
# cuma menyebut perusahaan — dan itu memang yang dimaksud orang yang
# menuliskannya.
SELECTOR_WEIGHT = 32


class MappingNotFound(ValidationError):
    """Tidak ada pemetaan yang cocok."""


class MappingAmbiguous(ValidationError):
    """Lebih dari satu pemetaan sama-sama cocok dan sama-sama khusus."""


@dataclass(frozen=True)
class MappingContext:
    """
    Keadaan yang dipakai memilih pemetaan.

    `selectors` datang dari payload kejadian (jenis komponen gaji,
    kategori barang); sisanya dari dimensi baris yang sedang disusun.
    """

    company_id: int
    event_type: str = ""
    location_id: int | None = None
    department_id: int | None = None
    cost_center_id: int | None = None
    selectors: dict | None = None
    on_date: date | None = None


class AccountMappingService(BaseMasterService):
    model = AccountMapping

    @staticmethod
    def list():
        return (
            AccountMapping.objects
            .filter(is_deleted=False)
            .select_related(
                "company", "account", "location", "department", "cost_center",
            )
            .order_by("mapping_key", "-specificity", "code")
        )

    # ------------------------------------------------------------------
    # Skor kekhususan
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(cls, *, data, user=None, **kwargs):
        data["specificity"] = cls.score(data)

        return data

    @classmethod
    def prepare_update_data(cls, *, instance, data, user=None, **kwargs):
        merged = {
            "company": data.get("company", instance.company),
            "event_type": data.get("event_type", instance.event_type),
            "location": data.get("location", instance.location),
            "department": data.get("department", instance.department),
            "cost_center": data.get("cost_center", instance.cost_center),
            "selectors": data.get("selectors", instance.selectors),
        }

        data["specificity"] = cls.score(merged)

        return data

    @staticmethod
    def score(data: dict) -> int:
        """
        Skor dihitung, **tidak pernah diketik**.

        Kalau ia kolom yang bisa diisi orang, dua baris akan diberi
        prioritas yang tidak menggambarkan syaratnya — dan aturan yang
        lebih umum bisa mengalahkan yang lebih khusus tanpa ada yang
        bisa menjelaskan kenapa.
        """
        total = 0

        for field, weight in WEIGHTS.items():
            value = data.get(field)

            if field == "event_type":
                if value:
                    total += weight

                continue

            if value:
                total += weight

        selectors = data.get("selectors") or {}

        if isinstance(selectors, dict):
            total += SELECTOR_WEIGHT * len(selectors)

        return min(total, 32767)

    # ------------------------------------------------------------------
    # Pencarian
    # ------------------------------------------------------------------

    @classmethod
    def resolve(cls, *, mapping_key: str, context: MappingContext) -> Account:
        candidates = cls.candidates(
            mapping_key=mapping_key,
            context=context,
        )

        if not candidates:
            raise MappingNotFound({
                "account_mapping": (
                    f"Tidak ada pemetaan akun untuk '{mapping_key}' pada "
                    f"kejadian '{context.event_type or '—'}'. Tambahkan "
                    "barisnya di Finance → Setup → Account Mapping. "
                    "Jurnalnya sengaja tidak diterbitkan: menebak akun "
                    "lebih berbahaya daripada tidak membukukan sama "
                    "sekali."
                ),
            })

        best = candidates[0]

        tied = [
            row for row in candidates
            if row.specificity == best.specificity
        ]

        if len(tied) > 1:
            codes = ", ".join(sorted(row.code for row in tied))

            raise MappingAmbiguous({
                "account_mapping": (
                    f"Pemetaan akun untuk '{mapping_key}' ambigu — "
                    f"{len(tied)} baris sama-sama cocok dan sama-sama "
                    f"khusus: {codes}. Pertajam salah satunya (sebutkan "
                    "site, department, atau syarat tambahan) atau "
                    "nonaktifkan yang tidak dipakai. Memilih salah satu "
                    "secara acak akan membukukan uang ke akun yang "
                    "ditentukan kebetulan."
                ),
            })

        return best.account

    @classmethod
    def candidates(
        cls,
        *,
        mapping_key: str,
        context: MappingContext,
    ) -> list[AccountMapping]:
        """
        Baris yang cocok, paling khusus di depan.

        Penyempitan organisasi disaring **di database** — baris yang
        menyebut cost center lain tidak pernah dimuat. `selectors`
        disaring di Python karena ia JSON bebas: kecocokannya "setiap
        pasangan di baris ini ada dan sama di konteks", dan itu bukan
        operasi yang bisa diindeks.
        """
        key = (mapping_key or "").strip().upper()

        if not key:
            raise ValidationError({
                "mapping_key": "Kunci pemetaan akun kosong.",
            })

        queryset = (
            AccountMapping.objects
            .filter(is_deleted=False, is_active=True, mapping_key=key)
            .filter(
                # Kosong = berlaku untuk semua. `Q`, bukan
                # `field__in=[x, None]`: `IN (NULL)` tidak pernah cocok
                # di SQL, dan baris umumnya hilang diam-diam — jebakan
                # yang sama sudah kena di `DocumentSeries` dan
                # `WorkflowDefinition`.
                Q(company_id=context.company_id) | Q(company__isnull=True)
            )
            .filter(Q(event_type=context.event_type) | Q(event_type=""))
            .filter(
                Q(location_id=context.location_id)
                | Q(location__isnull=True)
            )
            .filter(
                Q(department_id=context.department_id)
                | Q(department__isnull=True)
            )
            .filter(
                Q(cost_center_id=context.cost_center_id)
                | Q(cost_center__isnull=True)
            )
            .select_related("account")
            .order_by("-specificity", "code")
        )

        on_date = context.on_date
        supplied = context.selectors or {}

        matched = []

        for row in queryset:
            if on_date and not row.applies_on(on_date):
                continue

            if not cls._selectors_match(row.selectors, supplied):
                continue

            matched.append(row)

        return matched

    @staticmethod
    def _selectors_match(required: dict | None, supplied: dict) -> bool:
        """
        Cocok kalau **setiap** syarat baris ada dan sama di konteks.

        Konteks boleh membawa kunci lain — itu yang membuat satu baris
        pemetaan melayani kejadian yang payload-nya terus bertambah.
        Kunci yang **tidak ada** di konteks berarti tidak cocok, bukan
        diabaikan: baris yang menyebut `component_type` dimaksudkan
        hanya untuk kejadian yang punya komponen.
        """
        if not required:
            return True

        if not isinstance(required, dict):
            return False

        for key, value in required.items():
            if key not in supplied:
                return False

            left = supplied[key]

            if left == value:
                continue

            if str(left).strip().casefold() != str(value).strip().casefold():
                return False

        return True

    # ------------------------------------------------------------------
    # Pemeriksaan konfigurasi
    # ------------------------------------------------------------------

    @classmethod
    def detect_conflicts(cls, *, company_id: int | None = None) -> list[dict]:
        """
        Mendaftar pemetaan yang berpotensi ambigu, **sebelum** ada
        jurnal yang gagal karenanya.

        Constraint unik sudah menangkap baris yang syarat organisasinya
        persis sama; yang lolos darinya adalah baris yang `selectors`-nya
        berbeda urutan kunci atau berbeda huruf besar-kecil — JSON tidak
        punya urutan kunci yang stabil, jadi database tidak bisa
        menilainya sama. Yang di sini menutup sisa itu.

        Dipakai layar Account Mapping dan `manage.py tenant_command
        audit_finance_mapping`. Tidak menolak apa pun — ia melaporkan,
        karena konfigurasi yang ambigu untuk kombinasi yang tidak pernah
        terjadi tidak merugikan siapa pun.
        """
        queryset = AccountMapping.objects.filter(
            is_deleted=False, is_active=True,
        )

        if company_id is not None:
            queryset = queryset.filter(
                Q(company_id=company_id) | Q(company__isnull=True)
            )

        buckets: dict[tuple, list[AccountMapping]] = {}

        for row in queryset.select_related("account"):
            selectors = row.selectors or {}

            signature = (
                row.mapping_key,
                row.company_id,
                row.event_type,
                row.location_id,
                row.department_id,
                row.cost_center_id,
                # Dinormalkan: urut dan huruf kecil. Itu yang tidak bisa
                # dilakukan constraint database.
                tuple(sorted(
                    (str(k).casefold(), str(v).casefold())
                    for k, v in selectors.items()
                )),
            )

            buckets.setdefault(signature, []).append(row)

        conflicts = []

        for signature, rows in buckets.items():
            if len(rows) < 2:
                continue

            accounts = {row.account_id for row in rows}

            conflicts.append({
                "mapping_key": signature[0],
                "codes": sorted(row.code for row in rows),
                "count": len(rows),
                # Dua baris yang menunjuk akun yang **sama** ambigu
                # secara teknis tapi tidak merugikan — hasilnya sama apa
                # pun yang menang. Dibedakan supaya daftar peringatannya
                # tidak tenggelam oleh yang tidak perlu ditindaklanjuti.
                "same_account": len(accounts) == 1,
            })

        return sorted(conflicts, key=lambda item: item["mapping_key"])
