"""
Riwayat kepegawaian satu pegawai.

Dirakit dari **`EmployeeAction` yang sudah APPLIED**, bukan dari model
riwayat tersendiri. Itu keputusan yang disengaja: dokumen yang
menerapkan perubahan sudah menyimpan nilai sebelum dan sesudahnya
(`values_before` / `values_after`), tanggal berlakunya, alasannya, dan
siapa yang menyetujuinya. Menyalinnya lagi ke tabel riwayat berarti dua
sumber untuk kejadian yang sama, dan yang satu cepat atau lambat berbeda
dari yang lain.

Baris tertua selalu **HIRE**, diturunkan dari `join_date` dan keadaan
awal yang tersimpan di `values_before` action tertua — supaya timeline
tidak dimulai dari perpanjangan kontrak pertama seolah orangnya muncul
begitu saja.

Riwayat lama tidak pernah berubah saat keadaan sekarang berubah: yang
dibaca di sini snapshot yang dibekukan, bukan relasi yang ikut bergerak.
"""

from __future__ import annotations

from apps.hr.models import EmployeeAction, EmployeeActionStatus


# Kolom yang ditampilkan per jenis action. Tanpa ini timeline
# memperlihatkan tiga puluh kolom yang sebagian besar `null` untuk tiap
# baris, dan yang benar-benar berubah tenggelam di antaranya.
HIGHLIGHT_FIELDS = {
    "contract_extension": ("contract_end", "contract_start"),
    "contract_change": (
        "contract_type",
        "contract_start",
        "contract_end",
    ),
    "employment_type_change": (
        "employment_type",
        "employee_group",
        "confirmation_date",
        "contract_end",
    ),
    "probation_change": (
        "probation_type",
        "probation_start",
        "probation_end",
    ),
    "status_change": ("employment_status",),
    "transfer": (
        "company",
        "branch",
        "location",
        "division",
        "department",
        "section",
        "position",
    ),
    "promotion": ("position", "job_level", "job_grade", "reports_to"),
    "demotion": ("position", "job_level", "job_grade", "reports_to"),
    "position_change": ("position", "job_level", "job_grade"),
    "salary_change": (
        "basic_salary",
        "salary_grade",
        "salary_level",
        "payroll_group",
    ),
    "resignation": ("employment_status", "termination_date"),
    "termination": (
        "employment_status",
        "termination_date",
        "termination_reason",
    ),
}


def _changes(action: EmployeeAction) -> list[dict]:
    """
    Kolom yang benar-benar berubah, dari → ke.

    Dibandingkan dari dua snapshot yang sama-sama dibekukan, jadi
    hasilnya tetap sama walau dibaca lima tahun lagi.
    """
    before = action.values_before or {}
    after = action.values_after or {}

    fields = HIGHLIGHT_FIELDS.get(
        action.action_type,
        tuple(sorted(set(before) | set(after))),
    )

    rows = []

    for field_name in fields:
        old = before.get(field_name)
        new = after.get(field_name)

        if old == new:
            continue

        rows.append(
            {
                "field": field_name,
                "label": field_name.replace("_", " ").title(),
                "from": old,
                "to": new,
            },
        )

    return rows


def employment_timeline(employee, *, viewer=None) -> list[dict]:
    """
    `viewer` = akun yang membuka layarnya.

    Dioper eksplisit, bukan diambil dari `CurrentRequestMiddleware`:
    pemanggil non-HTTP (perintah manajemen, task, test) harus
    berperilaku sama dengan jalur API, dan kerahasiaan yang bergantung
    pada variabel konteks gagal ke arah yang salah — terbuka, diam-diam.

    `viewer=None` berarti **tanpa penyaringan**. Itu benar untuk
    pemanggil internal yang memang tidak mewakili siapa pun; jalur API
    selalu mengopernya.
    """
    actions = (
        EmployeeAction.objects
        .filter(
            employee=employee,
            status=EmployeeActionStatus.APPLIED,
            is_deleted=False,
        )
        .select_related("applied_by")
        .order_by("effective_date", "id")
    )

    hidden_types: set[str] = set()
    hide_contract = False

    if viewer is not None:
        from apps.administration.models import EmployeeDataSubject
        from apps.hr.api.employee.visibility import EmployeeDataVisibility

        hidden_types = EmployeeDataVisibility.hidden_action_types(
            employee=employee,
            user=viewer,
        )

        hide_contract = not EmployeeDataVisibility.can_view(
            employee=employee,
            subject=str(EmployeeDataSubject.HISTORY_CONTRACT),
            user=viewer,
        )

    entries = []

    employment = getattr(employee, "employment", None)
    join_date = getattr(employment, "join_date", None)

    if join_date is not None:
        # Keadaan awal dibaca dari snapshot "sebelum" milik action
        # tertua — itu satu-satunya rekaman jenis kepegawaian dan
        # kontrak orang ini saat masuk. Kalau belum pernah ada action,
        # keadaan sekarang memang keadaan awalnya.
        first = actions.first()

        opening = (
            (first.values_before or {})
            if first is not None
            else {}
        )

        entries.append(
            {
                "id": "hire",
                "date": join_date,
                "type": "hire",
                "type_label": "Hire",
                "document_number": "",
                "reason": "",

                # Baris Hire **selalu** tampil — ia diturunkan dari
                # `join_date`, bukan dari `EmployeeAction`, dan tanggal
                # masuk bukan rahasia. Yang ikut disembunyikan cuma
                # rincian kontraknya: menampilkan Contract End di baris
                # ini sementara seluruh riwayat kontraknya dibatasi
                # membocorkannya lewat pintu belakang.
                "changes": [] if hide_contract else [
                    {
                        "field": field_name,
                        "label": field_name.replace("_", " ").title(),
                        "from": None,
                        "to": (
                            opening.get(field_name)
                            if first is not None
                            else _current_value(employment, field_name)
                        ),
                    }
                    for field_name in (
                        "employment_type",
                        "contract_type",
                        "contract_end",
                    )
                    if (
                        opening.get(field_name)
                        if first is not None
                        else _current_value(employment, field_name)
                    )
                ],
            },
        )

    for action in actions:
        # Dibuang dari payload, bukan ditandai. Satu baris "perubahan
        # disembunyikan" sudah memberi tahu bahwa ada kenaikan gaji,
        # dan itu setengah dari informasinya.
        if action.action_type in hidden_types:
            continue

        entries.append(
            {
                "id": action.pk,
                "date": action.effective_date,
                "type": action.action_type,
                "type_label": action.get_action_type_display(),
                "document_number": action.document_number,
                "reason": action.reason,
                "applied_at": action.applied_at,
                "applied_by": (
                    action.applied_by.get_full_name()
                    or action.applied_by.email
                    if action.applied_by_id
                    else None
                ),
                "changes": _changes(action),
            },
        )

    return entries


def _current_value(employment, field_name):
    value = getattr(employment, field_name, None)

    if value is None:
        return None

    name = getattr(value, "name", None)

    if name is not None:
        return name

    return value.isoformat() if hasattr(value, "isoformat") else str(value)
