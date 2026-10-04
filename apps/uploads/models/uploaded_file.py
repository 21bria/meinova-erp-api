from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import connection, models
from django.utils import timezone
from django.utils.text import get_valid_filename


def upload_category_folder(instance: "UploadedFile") -> str:
    """
    Nama folder untuk sebuah berkas, diambil dari `category`.

    Sebelum ini seluruh unggahan mendarat di satu folder yang sama:
    scan KTP pegawai, lampiran dokumen, berkas import, dan tangkapan
    layar panduan berjejer sebagai nama heksadesimal acak tanpa satu pun
    penanda milik siapa. Akibatnya bukan cuma soal kerapian —

    - **Media disajikan tanpa autentikasi.** Selama semuanya satu folder,
      "boleh dibuka siapa saja" dan "hanya untuk yang berhak" tidak punya
      batas yang bisa ditunjuk aturan server mana pun. Dipisah begini,
      `uploads/<schema>/content/` bisa dilayani terbuka sementara sisanya
      dipindah ke balik view berautentikasi tanpa menyentuh satu baris
      isi artikel pun
    - Berkas yatim bisa ditelusuri per keperluan. Di tenant demo, 43 dari
      55 baris menunjuk berkas yang sudah tidak ada; tanpa pemisahan
      tidak ada cara menjawab "yang hilang itu lampiran atau panduan"

    Nilai yang tidak dikenal jatuh ke `general`, bukan melempar: berkas
    yang gagal disimpan gara-gara kategori salah ketik jauh lebih
    merugikan daripada berkas yang mendarat di folder umum.
    """
    known = {value for value, _label in UploadedFile.Category.choices}
    category = getattr(instance, "category", None)

    return category if category in known else UploadedFile.Category.GENERAL


def uploaded_file_path(instance: "UploadedFile", filename: str) -> str:
    """
    Membuat lokasi penyimpanan file yang:

    - terpisah berdasarkan tenant/schema
    - terpisah berdasarkan kategori/keperluan
    - terorganisasi berdasarkan tahun dan bulan
    - menggunakan nama UUID agar tidak bentrok
    - tetap mempertahankan ekstensi file

    Berkas lama **tidak** ikut pindah: jalur tersimpan di kolom `file`,
    jadi yang sudah ada tetap dilayani dari tempatnya. Yang berubah cuma
    tujuan unggahan berikutnya.
    """
    original_name = get_valid_filename(Path(filename).name)
    extension = Path(original_name).suffix.lower()

    schema_name = getattr(connection, "schema_name", None) or "public"
    now = timezone.now()

    generated_name = f"{uuid.uuid4().hex}{extension}"

    return os.path.join(
        "uploads",
        schema_name,
        upload_category_folder(instance),
        str(now.year),
        f"{now.month:02d}",
        generated_name,
    )


def uploaded_thumbnail_path(instance: "UploadedFile", filename: str) -> str:
    """
    Thumbnail duduk di bawah folder kategori yang sama dengan aslinya.

    Bukan di satu cabang `thumbnails/` terpisah seperti dulu: kalau
    terpisah, satu awalan tidak lagi mencakup seluruh berkas sebuah
    keperluan — dan aturan penyajian yang membuka `content/` akan
    melewatkan justru thumbnail-nya.
    """
    schema_name = getattr(connection, "schema_name", None) or "public"
    now = timezone.now()

    generated_name = f"{instance.public_id.hex}.webp"

    return os.path.join(
        "uploads",
        schema_name,
        upload_category_folder(instance),
        "thumbnails",
        str(now.year),
        f"{now.month:02d}",
        generated_name,
    )

class UploadedFileQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_deleted=False)

    def deleted(self):
        return self.filter(is_deleted=True)

    def ready(self):
        return self.filter(status=UploadedFile.Status.READY)

    def processing(self):
        return self.filter(status=UploadedFile.Status.PROCESSING)

    def failed(self):
        return self.filter(status=UploadedFile.Status.FAILED)

    def public(self):
        return self.filter(is_public=True)


class UploadedFileManager(
    models.Manager.from_queryset(
        UploadedFileQuerySet,
    )
):
    pass



class UploadedFile(models.Model):
    class FileType(models.TextChoices):
        IMAGE = "image", "Image"
        PDF = "pdf", "PDF"
        DOCUMENT = "document", "Document"
        SPREADSHEET = "spreadsheet", "Spreadsheet"
        ARCHIVE = "archive", "Archive"
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        OTHER = "other", "Other"

    class Category(models.TextChoices):
        GENERAL = "general", "General"
        ATTACHMENT = "attachment", "Attachment"

        # Gambar yang disisipkan ke dalam isi tulisan lewat editor —
        # tangkapan layar panduan hari ini, pengumuman besok. Satu
        # kategori untuk seluruh editor, bukan satu per modul: yang
        # membedakan berkasnya adalah cara ia dipakai (tertanam di HTML,
        # dibaca siapa pun yang boleh membuka tulisannya), bukan modul
        # mana yang kebetulan memuatnya.
        CONTENT = "content", "Content"

        AVATAR = "avatar", "Avatar"
        # Selfie bukti tap Self Service. Hak bacanya tetap diturunkan
        # dari induknya (`AttendanceLog.photo`) lewat `FileAccessService`
        # — kategori ini cuma penanda maksud unggahan, bukan otoritas.
        ATTENDANCE_SELFIE = "attendance_selfie", "Attendance Selfie"
        SIGNATURE = "signature", "Signature"
        IMPORT = "import", "Import"
        EXPORT = "export", "Export"
        REPORT = "report", "Report"
        TEMPORARY = "temporary", "Temporary"

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        DELETED = "deleted", "Deleted"

    id = models.BigAutoField(primary_key=True)

    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )

    file = models.FileField(
        upload_to=uploaded_file_path,
        max_length=500,
    )

    thumbnail = models.ImageField(
        upload_to=uploaded_thumbnail_path,
        max_length=500,
        null=True,
        blank=True,
    )

    original_name = models.CharField(
        max_length=255,
        db_index=True,
    )

    stored_name = models.CharField(
        max_length=255,
        blank=True,
    )

    extension = models.CharField(
        max_length=30,
        blank=True,
        db_index=True,
    )

    mime_type = models.CharField(
        max_length=150,
        blank=True,
        db_index=True,
    )

    file_type = models.CharField(
        max_length=30,
        choices=FileType.choices,
        default=FileType.OTHER,
        db_index=True,
    )

    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.GENERAL,
        db_index=True,
    )

    size = models.PositiveBigIntegerField(default=0)

    checksum_sha256 = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )

    width = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    height = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    page_count = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    is_public = models.BooleanField(
        default=False,
        db_index=True,
    )

    description = models.TextField(
        blank=True,
        default="",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    download_count = models.PositiveIntegerField(
        default=0,
    )

    last_download_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.READY,
        db_index=True,
    )

    version = models.PositiveIntegerField(default=1)

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_files",
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_uploaded_files",
    )

    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_uploaded_files",
    )

    replaced_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    updated_at = models.DateTimeField(auto_now=True)

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
    )

    objects = UploadedFileManager()
    all_objects = models.Manager()


    class Meta:
        db_table = "uploads_uploaded_file"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "is_deleted"],
                name="upload_status_deleted_idx",
            ),
            models.Index(
                fields=["file_type", "created_at"],
                name="upload_type_created_idx",
            ),
            models.Index(
                fields=["uploaded_by", "created_at"],
                name="upload_user_created_idx",
            ),
            models.Index(
                fields=["category", "created_at"],
                name="upload_category_created_idx",
            ),
            models.Index(
                fields=["expires_at", "is_deleted"],
                name="upload_expiry_deleted_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.original_name or str(self.public_id)
    
    def save(self, *args, **kwargs):
        if self.file:
            self.stored_name = Path(self.file.name).name

            if not self.extension:
                self.extension = (
                    Path(self.file.name)
                    .suffix
                    .lower()
                )

        super().save(*args, **kwargs)

    @property
    def size_display(self) -> str:
        size = float(self.size or 0)

        units = ["B", "KB", "MB", "GB", "TB"]

        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(size)} {unit}"

                return f"{size:.2f} {unit}"

            size /= 1024

        return f"{self.size} B"

    @property
    def is_image(self) -> bool:
        return self.file_type == self.FileType.IMAGE

    @property
    def is_pdf(self) -> bool:
        return self.file_type == self.FileType.PDF

    @property
    def can_preview(self) -> bool:
        return self.file_type in {
            self.FileType.IMAGE,
            self.FileType.PDF,
            self.FileType.VIDEO,
            self.FileType.AUDIO,
        }

    @property
    def storage_path(self) -> str | None:
        if not self.file:
            return None

        return self.file.name
    
    @property
    def filename(self) -> str:
        if not self.file:
            return ""

        return Path(self.file.name).name
    
    @property
    def extension_display(self) -> str:
        return self.extension.replace(".", "").upper()
    
    def soft_delete(self, *, user=None, save: bool = True) -> None:
        self.is_deleted = True
        self.status = self.Status.DELETED
        self.deleted_at = timezone.now()
        self.deleted_by = user

        if save:
            self.save(
                update_fields=[
                    "is_deleted",
                    "status",
                    "deleted_at",
                    "deleted_by",
                    "updated_at",
                ]
            )

    def restore(self, *, user=None, save: bool = True) -> None:
        self.is_deleted = False
        self.status = self.Status.READY
        self.deleted_at = None
        self.deleted_by = None
        self.updated_by = user

        if save:
            self.save(
                update_fields=[
                    "is_deleted",
                    "status",
                    "deleted_at",
                    "deleted_by",
                    "updated_by",
                    "updated_at",
                ]
            )

    def delete_storage_files(self) -> None:
        """
        Menghapus file fisik dan thumbnail dari storage.

        Jangan dipanggil ketika soft delete biasa.
        Gunakan hanya untuk purge atau cleanup file orphan.
        """
        file_names = [
            self.file.name if self.file else None,
            self.thumbnail.name if self.thumbnail else None,
        ]

        for file_name in file_names:
            if file_name and default_storage.exists(file_name):
                default_storage.delete(file_name)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "public_id": str(self.public_id),
            "original_name": self.original_name,
            "stored_name": self.stored_name,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "file_type": self.file_type,
            "category": self.category,
            "size": self.size,
            "size_display": self.size_display,
            "checksum_sha256": self.checksum_sha256,
            "version": self.version,
            "is_public": self.is_public,
            "description": self.description,
            "download_count": self.download_count,
            "last_download_at": self.last_download_at,
            "expires_at": self.expires_at,
        }