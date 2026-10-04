"""
Lookup Finance.

Nama lookup **global lintas domain** di registry ini, jadi `fiscal-years`
dan `posting-periods` sengaja tidak lagi berdiri di Administration —
dua pendaftar untuk satu nama membuat yang terdaftar belakangan menang,
diam-diam.
"""

from __future__ import annotations

from django.db.models import Q

from apps.framework.lookup import BaseLookup, register_lookup

from apps.finance.models import (
    Account,
    AccountingDimension,
    AccountingPeriod,
    AccountingPolicy,
    FiscalYear,
)


class BaseAccountLookup(BaseLookup):
    """
    Bagian yang sama untuk kedua dropdown akun.

    Yang membedakan turunannya cuma satu baris — `posting_allowed` —
    dan itu dinyatakan sebagai atribut, bukan lewat `get_queryset()`
    yang saling menimpa. Rantai `super()` di antara dua lookup yang
    keduanya menyaring akan menyulitkan dibaca tepat di tempat yang
    paling perlu jelas: dropdown akun yang salah menawarkan akun grup
    menghasilkan penolakan yang baru muncul saat Simpan.
    """

    model = Account

    value_field = "id"
    label_field = "name"

    search_fields = ["code", "name"]
    filter_fields = ["company_id", "account_type", "account_category"]
    ordering = ["code"]

    # Bagan akun milik satu perusahaan. Tanpa cakupan, dropdown akun
    # memperlihatkan seluruh perkiraan setiap badan usaha di tenant —
    # dan dropdown adalah jalur bocor yang paling gampang terlewat.
    data_scope = {"company": "company"}

    # `True` = hanya akun posting, `False` = hanya akun grup.
    posting_allowed = True

    @classmethod
    def get_queryset(cls):
        return super().get_queryset().filter(
            posting_allowed=cls.posting_allowed,
        )

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            # Kode ikut di label: akuntan mencari lewat nomor perkiraan,
            # bukan lewat namanya.
            "label": f"{instance.code} — {instance.name}",
            "code": instance.code,
            "name": instance.name,
            "company": instance.company_id,
            "account_type": instance.account_type,
            "normal_balance": instance.effective_normal_balance,
            "default_currency": instance.default_currency_id,
        }


@register_lookup
class AccountLookup(BaseAccountLookup):
    """
    Akun yang **menerima jurnal**.

    Akun grup sengaja dibuang di sini, bukan di sisi form: dropdown yang
    menawarkan akun grup lalu ditolak saat Simpan memindahkan penolakan
    ke titik terjauh dari tempat orang memilihnya.
    """

    name = "accounts"

    posting_allowed = True


@register_lookup
class AccountGroupLookup(BaseAccountLookup):
    """
    Kebalikannya: hanya akun **grup**.

    Dipakai pemilih induk di form Chart of Accounts — hanya akun grup
    yang boleh punya anak.
    """

    name = "account-groups"

    posting_allowed = False


@register_lookup
class FinanceFiscalYearLookup(BaseLookup):
    name = "fiscal-years"

    model = FiscalYear

    search_fields = ["code", "name"]
    filter_fields = ["company_id", "status"]
    ordering = ["-start_date"]

    data_scope = {"company": "company"}

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": instance.name,
            "code": instance.code,
            "company": instance.company_id,
            "start_date": instance.start_date,
            "end_date": instance.end_date,
            "status": instance.status,
            "is_current": instance.is_current,
        }


@register_lookup
class AccountingPeriodLookup(BaseLookup):
    name = "accounting-periods"

    model = AccountingPeriod

    search_fields = ["code", "name"]
    filter_fields = ["fiscal_year_id", "status"]
    ordering = ["fiscal_year__start_date", "period_number"]

    # Periode tidak menyimpan company sendiri — ia milik tahun bukunya.
    data_scope = {"company": "fiscal_year__company"}

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": instance.name,
            "code": instance.code,
            "fiscal_year": instance.fiscal_year_id,
            "start_date": instance.start_date,
            "end_date": instance.end_date,
            "status": instance.status,
        }


@register_lookup
class AccountingPolicyLookup(BaseLookup):
    name = "accounting-policies"

    model = AccountingPolicy

    search_fields = ["code", "name", "event_type"]
    filter_fields = ["company_id", "event_type"]
    ordering = ["event_type", "code"]

    # Kosong = berlaku untuk semua perusahaan, jadi baris ber-company
    # NULL harus tetap terlihat.
    data_scope = {"company": "company"}
    data_scope_allow_null = True

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": f"{instance.code} — {instance.name}",
            "event_type": instance.event_type,
            "company": instance.company_id,
        }


@register_lookup
class AccountingDimensionLookup(BaseLookup):
    name = "accounting-dimensions"

    model = AccountingDimension

    search_fields = ["code", "name"]
    filter_fields = ["data_type", "is_required"]
    ordering = ["sort_order", "name"]

    @classmethod
    def serialize(cls, instance):
        return {
            "value": instance.pk,
            "label": instance.name,
            "code": instance.code,
            "data_type": instance.data_type,
            "is_core": instance.is_core,
            "is_required": instance.is_required,
            "lookup_endpoint": instance.lookup_endpoint,
        }
