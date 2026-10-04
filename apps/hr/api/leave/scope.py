"""
Peta cakupan data dokumen cuti — **satu tempat, dua pembaca**.

Dipakai `EmployeeLeaveViewSet` untuk menyaring baris (cakupan data)
dan dipakai serializer untuk menjawab "boleh disunting orang ini atau
tidak" (`can_edit`). Dua salinan yang boleh berbeda berarti layar
menawarkan tombol simpan untuk baris yang API-nya akan menolak, atau
sebaliknya menguncinya untuk orang yang sebenarnya berhak — dan bedanya
tidak terlihat di layar mana pun.
"""

from __future__ import annotations


# Kolom organisasinya sudah tersimpan langsung di record cuti; `section`
# lewat penempatan pegawainya karena baris ini tidak menyimpannya.
LEAVE_DATA_SCOPE = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    "division": "employee__organization__division",
    "department": "employee__organization__department",
    "section": "employee__organization__section",
    "own": "employee__user_id",
}
