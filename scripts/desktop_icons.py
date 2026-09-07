"""Render the existing CETA SVG into explicit Windows ICO image frames.

Small frames use uncompressed 32-bit DIB pixels and a legacy AND mask. The
256-pixel frame uses PNG, as supported by the Windows icon resource format:
https://learn.microsoft.com/en-us/windows/win32/menurc/resource-file-formats
"""

from __future__ import annotations

from pathlib import Path
import struct
import zlib

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_DIRECTORY = struct.Struct("<BBBBHHII")
_BITMAP = struct.Struct("<IiiHHIIiiII")


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def _png(rgba: bytes, size: int) -> bytes:
    stride = size * 4
    rows = b"".join(b"\0" + rgba[y * stride:(y + 1) * stride] for y in range(size))
    return (_PNG_SIGNATURE
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(rows, level=9))
            + _chunk(b"IEND", b""))


def _dib(rgba: bytes, size: int) -> bytes:
    stride = size * 4
    mask_stride = ((size + 31) // 32) * 4
    pixels = bytearray()
    mask = bytearray(mask_stride * size)
    for row, y in enumerate(range(size - 1, -1, -1)):
        for x in range(size):
            red, green, blue, alpha = rgba[y * stride + x * 4:y * stride + x * 4 + 4]
            pixels.extend((blue, green, red, alpha))
            if alpha == 0:
                mask[row * mask_stride + x // 8] |= 0x80 >> (x % 8)
    header = _BITMAP.pack(40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    return header + pixels + mask


def _verify_png(frame: bytes, size: int) -> None:
    offset = 8
    kinds = []
    while offset < len(frame):
        if offset + 12 > len(frame):
            raise ValueError("Truncated ICO PNG chunk.")
        length = struct.unpack_from(">I", frame, offset)[0]
        kind = frame[offset + 4:offset + 8]
        end = offset + 8 + length
        if end + 4 > len(frame):
            raise ValueError("Truncated ICO PNG payload.")
        payload = frame[offset + 8:end]
        crc = struct.unpack_from(">I", frame, end)[0]
        if crc != zlib.crc32(kind + payload) & 0xFFFFFFFF:
            raise ValueError("ICO PNG checksum mismatch.")
        if not kinds and (kind != b"IHDR" or payload != struct.pack(
                ">IIBBBBB", size, size, 8, 6, 0, 0, 0)):
            raise ValueError("ICO PNG dimensions or pixel format mismatch.")
        kinds.append(kind)
        if kind == b"IEND" and (length or end + 4 != len(frame)):
            raise ValueError("Invalid ICO PNG ending.")
        offset = end + 4
    if kinds != [b"IHDR", b"IDAT", b"IEND"]:
        raise ValueError("ICO PNG must contain IHDR, IDAT and IEND.")


def _verify_dib(frame: bytes, size: int) -> None:
    pixel_bytes = size * size * 4
    mask_stride = ((size + 31) // 32) * 4
    if len(frame) != 40 + pixel_bytes + mask_stride * size:
        raise ValueError("ICO DIB pixel or AND-mask size mismatch.")
    expected = (40, size, size * 2, 1, 32, 0, pixel_bytes, 0, 0, 0, 0)
    if _BITMAP.unpack_from(frame) != expected:
        raise ValueError("ICO DIB dimensions or pixel format mismatch.")
    expected_mask = bytearray(mask_stride * size)
    for row in range(size):
        for x in range(size):
            if frame[40 + (row * size + x) * 4 + 3] == 0:
                expected_mask[row * mask_stride + x // 8] |= 0x80 >> (x % 8)
    if frame[40 + pixel_bytes:] != expected_mask:
        raise ValueError("ICO AND mask does not match pixel transparency.")


def _verify_bytes(raw: bytes) -> tuple[int, ...]:
    from PySide6.QtGui import QImage

    if len(raw) < 6 or struct.unpack_from("<HHH", raw) != (0, 1, len(ICON_SIZES)):
        raise ValueError("ICO must contain exactly the required nine icon frames.")
    offset = 6 + len(ICON_SIZES) * _DIRECTORY.size
    if len(raw) < offset:
        raise ValueError("Truncated ICO directory.")
    for index, size in enumerate(ICON_SIZES):
        entry = _DIRECTORY.unpack_from(raw, 6 + index * _DIRECTORY.size)
        length, position = entry[6:]
        encoded_size = size if size < 256 else 0
        if entry[:6] != (
                encoded_size, encoded_size, 0, 0, 1, 32):
            raise ValueError("ICO frame dimensions or directory format mismatch.")
        if position != offset or length <= 0 or position + length > len(raw):
            raise ValueError("ICO frame offsets overlap, escape or leave gaps.")
        frame = raw[position:position + length]
        if size == 256:
            if not frame.startswith(_PNG_SIGNATURE):
                raise ValueError("The 256-pixel ICO frame must use PNG.")
            _verify_png(frame, size)
        else:
            _verify_dib(frame, size)
        single = (struct.pack("<HHH", 0, 1, 1)
                  + _DIRECTORY.pack(*entry[:6], length, 22) + frame)
        decoded = QImage.fromData(single, "ICO")
        if decoded.isNull() or (decoded.width(), decoded.height()) != (size, size):
            raise ValueError("ICO frame cannot be decoded at its declared size.")
        offset += length
    if offset != len(raw):
        raise ValueError("Unexpected trailing ICO data.")
    return ICON_SIZES


def verify_ico(path: Path) -> tuple[int, ...]:
    """Validate all nine canonical frames; raise ValueError for invalid ICO data."""
    return _verify_bytes(Path(path).read_bytes())


def _render_frames(svg_path: Path) -> list[bytes]:
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(Path(svg_path).read_bytes()))
    if not renderer.isValid():
        raise ValueError("Invalid SVG icon artwork.")
    if renderer.animated():
        raise ValueError("Animated SVG cannot produce a deterministic icon.")
    frames = []
    for size in ICON_SIZES:
        image = QImage(size, size, QImage.Format_RGBA8888)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            renderer.render(painter)
        finally:
            painter.end()
        rgba = bytes(image.constBits())
        frames.append(_png(rgba, size) if size == 256 else _dib(rgba, size))
    return frames


def create_windows_icon(svg_path: Path, output_path: Path) -> Path:
    """Render CETA's vector artwork; exclusively create a new validated ICO file.

    The destination parent must already exist. Existing files and links are
    never replaced. All rendering and validation finish before file creation.
    """
    destination = Path(output_path)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing to overwrite icon: {destination}")
    frames = _render_frames(svg_path)
    offset = 6 + len(frames) * _DIRECTORY.size
    directory = bytearray(struct.pack("<HHH", 0, 1, len(frames)))
    for size, frame in zip(ICON_SIZES, frames):
        encoded_size = size if size < 256 else 0
        directory.extend(_DIRECTORY.pack(encoded_size, encoded_size, 0, 0, 1, 32,
                                         len(frame), offset))
        offset += len(frame)
    raw = bytes(directory) + b"".join(frames)
    _verify_bytes(raw)
    with destination.open("xb") as handle:
        handle.write(raw)
    return destination
