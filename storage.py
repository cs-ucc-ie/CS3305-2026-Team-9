import os
import tempfile
import zipfile
from flask import send_from_directory, Response

USE_CLOUD_STORAGE = os.getenv('USE_CLOUD_STORAGE', 'false').lower() == 'true'

_s3_client = None


def _get_s3_client():
    """Lazy-initialize and return the boto3 S3 client for R2."""
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client(
            's3',
            endpoint_url=os.getenv('R2_ENDPOINT_URL'),
            aws_access_key_id=os.getenv('R2_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('R2_SECRET_ACCESS_KEY'),
            region_name='auto',
        )
    return _s3_client


def _get_bucket():
    return os.getenv('R2_BUCKET_NAME', 'sharelink-files')


# ============================================================
# Public Interface
# ============================================================

def save_file(file_obj, saved_filename, upload_folder):
    """Save a single uploaded file. Returns file size in bytes."""
    if USE_CLOUD_STORAGE:
        return _cloud_save_file(file_obj, saved_filename)
    return _local_save_file(file_obj, saved_filename, upload_folder)


def save_zip(files, saved_filename, upload_folder):
    """Create a zip from multiple files and save it.
    files: list of (secure_filename, file_data_bytes) tuples.
    Returns file size in bytes.
    """
    if USE_CLOUD_STORAGE:
        return _cloud_save_zip(files, saved_filename)
    return _local_save_zip(files, saved_filename, upload_folder)


def get_file_response(saved_filename, original_filename, upload_folder,
                      as_attachment=True):
    """Return a Flask response that serves the file."""
    if USE_CLOUD_STORAGE:
        return _cloud_get_file_response(saved_filename, original_filename,
                                        as_attachment)
    return _local_get_file_response(saved_filename, original_filename,
                                    upload_folder, as_attachment)


def delete_file(saved_filename, upload_folder):
    """Delete a file from storage."""
    if USE_CLOUD_STORAGE:
        return _cloud_delete_file(saved_filename)
    return _local_delete_file(saved_filename, upload_folder)


# ============================================================
# Local Storage Implementation
# ============================================================

def _local_save_file(file_obj, saved_filename, upload_folder):
    filepath = os.path.join(upload_folder, saved_filename)
    file_obj.save(filepath)
    return os.path.getsize(filepath)


def _local_save_zip(files, saved_filename, upload_folder):
    zip_path = os.path.join(upload_folder, saved_filename)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for filename, file_data in files:
            zipf.writestr(filename, file_data)
    return os.path.getsize(zip_path)


def _local_get_file_response(saved_filename, original_filename,
                              upload_folder, as_attachment):
    if as_attachment:
        return send_from_directory(upload_folder, saved_filename,
                                   as_attachment=True,
                                   download_name=original_filename)
    return send_from_directory(upload_folder, saved_filename)


def _local_delete_file(saved_filename, upload_folder):
    file_path = os.path.join(upload_folder, saved_filename)
    if os.path.exists(file_path):
        os.remove(file_path)


# ============================================================
# Cloud (R2) Storage Implementation
# ============================================================

def _cloud_save_file(file_obj, saved_filename):
    """Upload a single file to R2. Returns file size."""
    client = _get_s3_client()
    bucket = _get_bucket()

    file_obj.seek(0)
    data = file_obj.read()
    file_size = len(data)

    client.put_object(Bucket=bucket, Key=saved_filename, Body=data)
    return file_size


def _cloud_save_zip(files, saved_filename):
    """Create a zip in a temp file, upload to R2, then clean up."""
    client = _get_s3_client()
    bucket = _get_bucket()

    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
        tmp_path = tmp.name
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for filename, file_data in files:
                zipf.writestr(filename, file_data)

    try:
        file_size = os.path.getsize(tmp_path)
        client.upload_file(tmp_path, bucket, saved_filename)
    finally:
        os.unlink(tmp_path)

    return file_size


def _cloud_get_file_response(saved_filename, original_filename, as_attachment):
    """Stream the file from R2 through Flask."""
    client = _get_s3_client()
    bucket = _get_bucket()

    r2_response = client.get_object(Bucket=bucket, Key=saved_filename)
    body = r2_response['Body']
    content_type = r2_response.get('ContentType', 'application/octet-stream')
    content_length = r2_response.get('ContentLength')

    headers = {}
    if as_attachment:
        headers['Content-Disposition'] = (
            f'attachment; filename="{original_filename}"'
        )
    if content_length:
        headers['Content-Length'] = str(content_length)

    def generate():
        for chunk in body.iter_chunks(chunk_size=8192):
            yield chunk

    return Response(generate(), content_type=content_type, headers=headers)


def _cloud_delete_file(saved_filename):
    """Delete an object from R2."""
    client = _get_s3_client()
    bucket = _get_bucket()
    client.delete_object(Bucket=bucket, Key=saved_filename)
