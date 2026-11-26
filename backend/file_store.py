"""Files kept by mAIPAL itself (for now: what is attached to a QR). In MongoDB (GridFS): saved with the rest of the
data, in the same backup, and the same for every copy of the server. Moving them to an object storage (S3) later
is another class with the same three methods.

What comes in is checked here: only a real image (re-encoded as JPEG, which also drops its EXIF - the phone's GPS
position - and anything hidden in it) or a real PDF. Never served as a web page (see server: nosniff)."""
import io
from typing import Optional, Tuple

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
IMAGE_MAX_DIM = 2400


class BadFile(ValueError):
    pass


def check_pdf(data: bytes) -> int:
    """A PDF that opens: its number of pages."""
    if not data.startswith(b"%PDF-"):
        raise BadFile("Il file non è un PDF valido")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise BadFile("Il PDF è protetto da password: caricane una copia senza password")
        return len(reader.pages)
    except BadFile:
        raise
    except Exception:
        raise BadFile("Il PDF non si apre: potrebbe essere danneggiato")


def image_to_jpeg(data: bytes, downscale) -> Tuple[bytes, int, int]:
    """A photo (JPG, PNG, HEIC, WebP...) -> JPEG at most 2400 px, without its metadata."""
    from PIL import Image
    try:
        out = downscale(data, max_dim=IMAGE_MAX_DIM, max_bytes=4 * 1024 * 1024)
        w, h = Image.open(io.BytesIO(out)).size
        return out, w, h
    except Exception:
        raise BadFile("L'immagine non si apre: prova con una foto JPG o PNG")


def kind_of(data: bytes, filename: str, content_type: Optional[str]) -> str:
    """'pdf' or 'image' from the content (the name and the declared type are not trusted alone)."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG") or head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc") \
            or (head.startswith(b"RIFF") and data[8:12] == b"WEBP") or head.startswith(b"GIF8"):
        return "image"
    raise BadFile("Si possono allegare solo foto (JPG, PNG, HEIC) e PDF")


class GridFSStore:
    def _bucket(self, db):
        from motor.motor_asyncio import AsyncIOMotorGridFSBucket
        return AsyncIOMotorGridFSBucket(getattr(db, "_raw", db), bucket_name="files")

    async def put(self, db, data: bytes, filename: str, metadata: dict) -> str:
        fid = await self._bucket(db).upload_from_stream(filename, data, metadata=metadata)
        return str(fid)

    async def get(self, db, file_id: str) -> Optional[bytes]:
        from bson import ObjectId
        from gridfs.errors import NoFile
        try:
            stream = await self._bucket(db).open_download_stream(ObjectId(file_id))
            return await stream.read()
        except (NoFile, Exception):
            return None

    async def delete(self, db, file_id: str) -> None:
        from bson import ObjectId
        try:
            await self._bucket(db).delete(ObjectId(file_id))
        except Exception:
            pass


class MemoryStore:
    """(tests)"""
    def __init__(self):
        self.files = {}

    async def put(self, db, data, filename, metadata):
        fid = f"{len(self.files) + 1:024x}"
        self.files[fid] = (data, filename, metadata)
        return fid

    async def get(self, db, file_id):
        return (self.files.get(file_id) or (None,))[0]

    async def delete(self, db, file_id):
        self.files.pop(file_id, None)


store = GridFSStore()
