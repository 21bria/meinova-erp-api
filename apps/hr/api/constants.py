# Kolom audit & soft-delete dari BaseModel. Selalu read-only: diisi
# service lewat `user=` yang dioper viewset, bukan dari payload klien.
AUDIT_READ_ONLY_FIELDS = [
    "id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "deleted_at",
    "deleted_by",
    "is_deleted",
]
