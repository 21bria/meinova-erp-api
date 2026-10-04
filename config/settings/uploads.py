# =============================================================================
# Upload Framework
# =============================================================================

UPLOAD_MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
UPLOAD_MAX_MULTIPLE_FILES = 20

UPLOAD_ALLOWED_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",

    ".pdf",

    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".ppt",
    ".pptx",

    ".txt",
    ".rtf",

    ".zip",
)

UPLOAD_ALLOWED_MIME_TYPES = (
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",

    "application/pdf",

    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",

    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",

    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",

    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",

    "text/plain",
    "application/rtf",
    "text/rtf",

    "application/zip",
    "application/x-zip-compressed",
)

UPLOAD_GENERATE_IMAGE_THUMBNAIL = True
UPLOAD_GENERATE_PDF_THUMBNAIL = True

UPLOAD_THUMBNAIL_SIZE = (320, 320)
UPLOAD_THUMBNAIL_FORMAT = "WEBP"
UPLOAD_THUMBNAIL_QUALITY = 85

UPLOAD_DELETE_OLD_FILE_ON_REPLACE = True
UPLOAD_SOFT_DELETE = True