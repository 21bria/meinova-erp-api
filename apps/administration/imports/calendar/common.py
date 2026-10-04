"""
Bagian yang dipakai bersama importer Work Calendar dan Holiday.

Keduanya menjawab pertanyaan cakupan yang **sama** — GLOBAL tanpa
company, COMPANY wajib company, LOCATION wajib keduanya dan harus
konsisten — jadi aturannya ditulis sekali. Dua salinan aturan cakupan
adalah dua kesempatan salah satunya menerima baris yang seharusnya
ditolak.
"""

from __future__ import annotations

from typing import Any

from apps.administration.models import Company, Location


BOOLEAN_TRUE = {"1", "true", "yes", "y", "ya", "on", "aktif", "active"}
BOOLEAN_FALSE = {"0", "false", "no", "n", "tidak", "off", "nonaktif", "inactive"}


SCOPE_ALIASES = [
    "scope",
    "cakupan",
    "applies_to",
    "applies to",
    "berlaku",
]

COMPANY_ALIASES = [
    "company",
    "company_code",
    "company code",
    "perusahaan",
    "kode_perusahaan",
]

LOCATION_ALIASES = [
    "location",
    "location_code",
    "location code",
    "site",
    "site_code",
    "lokasi",
]

CODE_ALIASES = ["code", "kode"]

NAME_ALIASES = ["name", "nama", "description", "keterangan"]

ACTIVE_ALIASES = ["is_active", "is active", "active", "aktif", "status"]


def to_bool(value: Any, *, default: bool | None = None) -> bool | None:
    """
    Membaca kolom ya/tidak dari file yang ditulis manusia.

    Mengembalikan None kalau nilainya ada tapi **tidak dikenali** —
    dibedakan dari kolom kosong, yang mengambil `default`. Bedanya
    penting: "Y" salah ketik jadi "Ya benar" harus ditolak dengan
    pesan, bukan diam-diam dianggap tidak.
    """
    if value is None:
        return default

    text = str(value).strip().lower()

    if not text:
        return default

    if text in BOOLEAN_TRUE:
        return True

    if text in BOOLEAN_FALSE:
        return False

    return None


def normalize_scope(value: Any, *, allowed: set[str]) -> str | None:
    """
    Menyeragamkan tulisan cakupan. None kalau tidak dikenali.

    `NATIONAL` diterima sebagai sinonim `GLOBAL` untuk hari libur:
    itu kata yang dipakai orang saat menyiapkan filenya, dan menolaknya
    berarti setiap file libur nasional harus diterjemahkan lebih dulu.
    """
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")

    if not text:
        return None

    if text in {"NATIONAL", "ALL", "ALL_COMPANIES", "SEMUA"}:
        text = "GLOBAL"

    if text in {"SELECTED", "SELECTED_COMPANY", "MULTI_COMPANY"}:
        text = "SELECTED_COMPANIES"

    return text if text in allowed else None


def find_company(value: Any):
    """
    Kode lebih dulu, lalu nama. Urutannya penting: kode yang stabil
    adalah yang dimaksud file migrasi, dan nama perusahaan berubah
    lebih sering daripada kodenya.
    """
    text = str(value or "").strip()

    if not text:
        return None

    queryset = Company.objects.filter(is_deleted=False)

    return (
        queryset.filter(code__iexact=text).first()
        or queryset.filter(name__iexact=text).first()
    )


def find_location(value: Any, *, company=None):
    text = str(value or "").strip()

    if not text:
        return None

    queryset = Location.objects.filter(is_deleted=False)

    if company is not None:
        # Dipersempit ke perusahaan yang sudah disebut barisnya. Tanpa
        # ini, kode lokasi yang kebetulan sama di dua perusahaan akan
        # mendarat di perusahaan yang salah — dan barisnya tetap
        # tersimpan tanpa satu pun tanda.
        queryset = queryset.filter(company=company)

    return (
        queryset.filter(code__iexact=text).first()
        or queryset.filter(name__iexact=text).first()
    )


def resolve_scope_target(
    normalized: dict[str, Any],
    *,
    allowed_scopes: set[str],
    selected_scope: str | None = None,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """
    Membaca `scope`/`company`/`location` satu baris jadi objek relasi.

    Seluruh penolakan lahir di sini — bukan di `write()`. Yang ditolak
    di sini muncul di layar preview lengkap dengan nomor barisnya;
    yang jatuh di `write()` baru terbaca setelah job selesai, dan saat
    itu orangnya sudah menekan Confirm.
    """
    resolved: dict[str, Any] = {}
    errors: dict[str, list[str]] = {}

    def fail(field_name: str, message: str) -> None:
        errors.setdefault(field_name, []).append(message)

    raw_scope = normalized.get("scope")

    scope = normalize_scope(raw_scope, allowed=allowed_scopes)

    if scope is None:
        fail(
            "scope",
            f"Scope '{raw_scope}' tidak dikenali. Pilihannya: "
            f"{', '.join(sorted(allowed_scopes))}.",
        )

        # Tanpa cakupan yang sah, memeriksa company/location tidak ada
        # artinya — aturannya sendiri yang ditentukan cakupan.
        return resolved, errors

    resolved["scope"] = scope

    raw_company = str(normalized.get("company") or "").strip()
    raw_location = str(normalized.get("location") or "").strip()

    company = None
    location = None

    # Cakupan SELECTED_COMPANIES memakai kolom `company` sebagai
    # **daftar** dipisah koma, jadi ia tidak boleh ikut dicari sebagai
    # satu kode. Tanpa pengecualian ini, "MMR,MLS" dicari sebagai satu
    # perusahaan bernama persis itu, tidak ketemu, dan barisnya ditolak
    # dengan pesan yang menyebut kode yang tidak pernah diketik
    # siapa pun.
    is_selected = bool(selected_scope) and scope == selected_scope

    if raw_company and not is_selected:
        company = find_company(raw_company)

        if company is None:
            fail(
                "company",
                f"Company '{raw_company}' tidak ditemukan di master.",
            )

    if raw_location:
        location = find_location(raw_location, company=company)

        if location is None:
            fail(
                "location",
                f"Location '{raw_location}' tidak ditemukan"
                + (
                    f" pada company {raw_company}."
                    if raw_company
                    else " di master."
                ),
            )

    if scope == "GLOBAL":
        if raw_company:
            fail(
                "company",
                "Scope GLOBAL berlaku untuk seluruh company, jadi "
                "kolom company harus dikosongkan.",
            )

        if raw_location:
            fail(
                "location",
                "Scope GLOBAL tidak boleh menyebut location.",
            )

    elif scope == "COMPANY":
        if not raw_company:
            fail("company", "Scope COMPANY wajib menyebut company.")

        if raw_location:
            fail(
                "location",
                "Scope COMPANY berlaku untuk seluruh lokasi company "
                "itu. Untuk satu lokasi saja, pakai scope LOCATION.",
            )

    elif scope == "LOCATION":
        if not raw_company:
            fail("company", "Scope LOCATION wajib menyebut company.")

        if not raw_location:
            fail("location", "Scope LOCATION wajib menyebut location.")

        elif (
            location is not None
            and company is not None
            and location.company_id != company.id
        ):
            fail(
                "location",
                f"Location '{location.code}' bukan milik company "
                f"'{company.code}'.",
            )

    elif selected_scope and scope == selected_scope:
        if raw_location:
            fail(
                "location",
                "Scope SELECTED_COMPANIES tidak boleh menyebut "
                "location.",
            )

        # Daftar perusahaannya boleh ditulis dipisah koma di kolom
        # company — itu bentuk yang paling wajar di satu sel Excel.
        codes = [
            part.strip()
            for part in raw_company.split(",")
            if part.strip()
        ]

        if not codes:
            fail(
                "company",
                "Scope SELECTED_COMPANIES wajib menyebut daftar "
                "company, dipisah koma.",
            )

        companies = []

        for code in codes:
            found = find_company(code)

            if found is None:
                fail(
                    "company",
                    f"Company '{code}' tidak ditemukan di master.",
                )
            else:
                companies.append(found)

        resolved["companies"] = companies

        # Kolom `company` pada baris SELECTED_COMPANIES tetap kosong;
        # daftarnya yang menentukan. Ditegaskan di sini supaya `write()`
        # tidak perlu tahu cabang mana yang sedang dijalankan.
        resolved["company"] = None
        resolved["location"] = None

        return resolved, errors

    resolved["company"] = company if scope not in {"GLOBAL"} else None
    resolved["location"] = location if scope == "LOCATION" else None

    return resolved, errors
