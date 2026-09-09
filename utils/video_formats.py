"""Video containers supported by the upload flow and frame extraction worker."""

VIDEO_MIME_TYPES = {
    ".avi": ("video/x-msvideo", "video/avi", "video/msvideo"),
    ".mkv": ("video/x-matroska", "video/matroska"),
    ".mov": ("video/quicktime",),
    ".mp4": ("video/mp4", "application/mp4"),
    ".webm": ("video/webm",),
}
VIDEO_EXTENSIONS = set(VIDEO_MIME_TYPES)
GENERIC_MIME_TYPES = ("", "application/octet-stream")
