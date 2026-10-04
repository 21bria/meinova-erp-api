from apps.uploads.models import UploadedFile
from apps.uploads.services.thumbnail_service import (
    generate_thumbnail,
)


def generate_upload_thumbnail(
    uploaded_file_id: int,
) -> bool:
    try:
        instance = UploadedFile.all_objects.get(
            pk=uploaded_file_id
        )
    except UploadedFile.DoesNotExist:
        return False

    if instance.is_deleted:
        return False

    return generate_thumbnail(instance)