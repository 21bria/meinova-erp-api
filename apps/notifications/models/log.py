"""
Log pengiriman.

Tanpa ini, "kenapa saya tidak dapat emailnya" tidak punya jawaban di
mana pun kecuali log server — dan log server tidak bisa dibuka orang HR
yang menanyakannya. Satu baris per (penerima, kanal), bukan per event:
email bisa gagal sementara belnya berhasil, dan menyatukannya berarti
salah satu keadaan itu hilang.

Sekaligus penjaga idempotensi. `dedup_key` yang sama tidak pernah
dikirim dua kali — itu yang membuat pengingat harian aman dijalankan
tiap hari tanpa mengisi kotak masuk orang dengan tiga puluh salinan
pemberitahuan kontrak yang sama.

**Bukan turunan `BaseModel`.** Ini catatan kejadian, bukan master: tidak
ada yang menyuntingnya, dan soft delete pada baris log berarti bukti
pengiriman bisa disembunyikan. Pola yang sama dengan `WorkflowApproval`
dan `AuditTrail`.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from ..constants import Channel, DeliveryStatus


class NotificationLog(models.Model):
    event = models.CharField(max_length=100, db_index=True)

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notification_logs",
    )

    # Alamat disimpan terpisah dari FK penerima, dan itu disengaja:
    # akun bisa dihapus atau alamatnya diganti, sementara pertanyaan
    # yang dijawab log ini adalah "ke alamat mana email itu dikirim
    # waktu itu". FK yang jadi NULL menyisakan baris tanpa penerima.
    recipient_email = models.CharField(
        max_length=254,
        blank=True,
        default="",
    )

    recipient_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    channel = models.CharField(
        max_length=20,
        choices=Channel.choices,
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        db_index=True,
    )

    subject = models.CharField(max_length=255, blank=True, default="")

    # Isi yang **sudah dirender**, sebagai teks biasa — bukan HTML dan
    # bukan sumber templatenya.
    #
    # Dua alasan menyimpan yang sudah dirender: (1) worker tinggal
    # mengirim, tidak perlu merender ulang dengan konteks yang harus
    # dioper lewat antrean dan berisiko berbeda; (2) log ini jadi
    # menjawab "apa persisnya yang dikirim ke orang itu". Template bisa
    # disunting besok, dan log yang cuma menyimpan kode event lalu
    # merender ulang saat dibaca akan memperlihatkan kalimat yang tidak
    # pernah diterima siapa pun.
    #
    # Teks, bukan HTML, karena HTML-nya cuma pembungkus yang dihasilkan
    # saat kirim — dan karena layar log ini dibaca orang: satu kolom
    # berisi tabel bergaya inline tidak bisa dibaca siapa pun.
    body = models.TextField(blank=True, default="")

    # Alamat penuh tujuan tombol di dalam email. Disimpan supaya baris
    # ini bisa dikirim ulang apa adanya tanpa menghitung ulang base_url
    # tenant — yang bisa saja sudah berubah.
    action_url = models.CharField(max_length=500, blank=True, default="")

    # Dokumen/objek yang memicunya. String, bukan GenericForeignKey —
    # alasan yang sama dengan `WorkflowInstance`: engine notifikasi
    # tidak boleh perlu mengenal model modul mana pun.
    module = models.CharField(max_length=50, blank=True, default="", db_index=True)
    object_type = models.CharField(max_length=100, blank=True, default="")
    object_id = models.CharField(max_length=100, blank=True, default="")

    # Kunci idempotensi. Dibentuk pemanggil, mis.
    # `hr.contract_end:154:2026-09-30:30` — event, dokumen, tanggal
    # sasaran, dan tonggak pengingatnya. Kosong = tidak pernah didedup;
    # itu benar untuk kejadian yang memang bisa berulang (dokumen yang
    # sama diajukan ulang setelah ditarik).
    dedup_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    # Alasan `SKIPPED` atau pesan kegagalan. Satu kolom untuk keduanya:
    # yang dicari orang saat membuka baris yang tidak terkirim adalah
    # kalimatnya, bukan jenis kalimatnya.
    detail = models.TextField(blank=True, default="")

    attempts = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification_log"
        ordering = ["-created_at", "-id"]

        constraints = [
            # Idempotensi ditegakkan database, bukan cuma diperiksa di
            # Python. Dua worker yang memproses task yang sama
            # bersamaan akan sama-sama membaca "belum pernah dikirim"
            # sebelum salah satunya sempat menulis barisnya — pola yang
            # sama persis dengan `applied_at` di RosterAdjustment.
            #
            # `dedup_key` kosong dikecualikan: constraint yang ikut
            # menjaga string kosong akan membuat seluruh event tanpa
            # dedup saling menghalangi.
            models.UniqueConstraint(
                fields=["dedup_key", "recipient", "channel"],
                condition=~models.Q(dedup_key=""),
                name="uniq_notification_log_dedup",
            ),
        ]

        indexes = [
            models.Index(fields=["event", "status"]),
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.event} → {self.recipient_email or self.recipient_id} ({self.status})"
