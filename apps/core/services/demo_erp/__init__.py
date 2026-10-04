"""
Dataset peragaan **Meinova ERP** (GRP / MMN / MIN, EMP001–EMP040).

Sumbernya `docs/demo-data/Meinova_ERP_Demo_Data_Blueprint_UPDATED.xlsx`,
tapi workbook itu **data bisnis**, bukan spesifikasi. Setiap kolomnya
dipetakan ke arsitektur yang sudah ada; yang tidak punya tempat
dilaporkan, bukan dipaksakan. Keputusan DEMO-0 yang mengikat paket ini:

* **B1** — GRP/MMN/MIN adalah perusahaan baru. MNI/MMR/MLS tidak pernah
  disentuh, diganti nama, atau dijadikan pemetaan.
* **B2** — dicabut DEMO-1D: HR-DEMO-1..3 (HO/SGA/LOK/BOD) dan TRL dibuang dari `demo`;
  tenant hanya memuat EMP001–EMP040. Awalan itu tetap terlindung dari dataset
  ini. Reset hanya membongkar baris yang terbukti milik dataset
  ini lewat penanda kepemilikannya.
* **B3** — seed berhenti di jurnal DRAFT. Jurnal milik dataset ini yang
  sudah POSTED membuat reset **menolak** berjalan; tidak ada pembalikan
  otomatis.
* **B4** — alur approval yang dipakai adalah hasil resolusi mesin,
  bukan teks "Approval Route" di workbook.

Tahap DEMO-1A hanya membangun perencana. `--apply` sengaja belum
tersambung (`APPLY_ENABLED = False`), jadi tidak ada satu baris pun yang
ditulis ke tenant dari paket ini.
"""
