"""
`EmployeeDataPolicy` — pemetaan kelompok data ke jenis Employee Action.

`SimpleTestCase`, tanpa database: yang dijaga di sini konstanta, dan
test yang tidak perlu menyiapkan tenant selesai dalam milidetik.

Yang dijaga bukan detail implementasi, melainkan satu invarian yang
gagalnya **tidak berbunyi**: jenis action yang tidak masuk kelompok mana
pun tidak bisa dibatasi sama sekali. Tidak ada error, tidak ada log —
barisnya cuma tetap terlihat oleh semua orang. Menambah jenis action
baru tanpa memetakannya di sini adalah cara paling mudah membuka
kebocoran tanpa ada yang menyadarinya.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.administration.models.references.employee_data_policy import (
    SUBJECT_ACTION_TYPES,
    EmployeeDataSubject,
    subject_for_action,
)
from apps.hr.models import EmployeeActionType


class SubjectMappingTests(SimpleTestCase):
    def test_every_action_type_belongs_to_a_subject(self):
        mapped = {
            action_type
            for types in SUBJECT_ACTION_TYPES.values()
            for action_type in types
        }

        known = {str(value) for value, _ in EmployeeActionType.choices}

        missing = known - mapped

        self.assertEqual(
            missing,
            set(),
            "Jenis action ini tidak masuk kelompok mana pun, jadi tidak "
            f"bisa dibatasi `EmployeeDataPolicy`: {sorted(missing)}",
        )

    def test_no_unknown_action_type_is_mapped(self):
        """Salah ketik di peta gagal ke arah sebaliknya: aturannya
        menyembunyikan jenis yang tidak pernah ada."""
        mapped = {
            action_type
            for types in SUBJECT_ACTION_TYPES.values()
            for action_type in types
        }

        known = {str(value) for value, _ in EmployeeActionType.choices}

        self.assertEqual(mapped - known, set())

    def test_action_type_belongs_to_exactly_one_subject(self):
        """Satu jenis di dua kelompok membuat hasilnya bergantung pada
        urutan iterasi dict."""
        seen: dict[str, str] = {}

        for subject, types in SUBJECT_ACTION_TYPES.items():
            for action_type in types:
                self.assertNotIn(
                    action_type,
                    seen,
                    f"'{action_type}' ada di {seen.get(action_type)} "
                    f"dan {subject}",
                )

                seen[action_type] = str(subject)

    def test_subject_for_action(self):
        self.assertEqual(
            subject_for_action("salary_change"),
            str(EmployeeDataSubject.HISTORY_SALARY),
        )

        # Jenis yang tidak dikenal tidak boleh melempar: pemanggilnya
        # memakai `None` sebagai "tidak bisa dibatasi".
        self.assertIsNone(subject_for_action("tidak_ada"))
