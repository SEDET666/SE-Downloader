"""
Cross-platform file type icon provider.

- Windows: uses SHGetFileInfo (Shell API) to get the real system icon
- macOS:   uses NSWorkspace
- Linux:   uses QFileIconProvider (themed icon)

Returns a QPixmap scaled to the requested size.
Falls back to a generic document icon on any error.
"""

import os, sys, tempfile
from functools import lru_cache

from PySide6.QtGui import QPixmap, QImage, QIcon
from PySide6.QtWidgets import QFileIconProvider
from PySide6.QtCore import QFileInfo, Qt


@lru_cache(maxsize=128)
def get_file_icon(extension: str, size: int = 32) -> QPixmap:
    """
    Return a QPixmap of the system icon for the given file extension.
    extension: e.g. ".zip", "zip", ".exe"  (case-insensitive)
    size: pixel size of the returned square icon
    """
    ext = extension.lower().lstrip(".")
    if not ext:
        ext = "bin"

    if sys.platform == "win32":
        px = _win_icon(ext, size)
    elif sys.platform == "darwin":
        px = _mac_icon(ext, size)
    else:
        px = _qt_icon(ext, size)

    if px is None or px.isNull():
        px = _qt_icon(ext, size)
    if px is None or px.isNull():
        px = _fallback(size)
    return px


# ── Windows ───────────────────────────────────────────────────────────────────

def _win_icon(ext: str, size: int) -> QPixmap:
    try:
        import ctypes
        from ctypes import wintypes

        # Create a dummy filename with the extension
        dummy = f"file.{ext}"

        SHGFI_ICON       = 0x000000100
        SHGFI_USEFILEATTRIBUTES = 0x000000010
        SHGFI_SMALLICON  = 0x000000001
        SHGFI_LARGEICON  = 0x000000000
        FILE_ATTRIBUTE_NORMAL = 0x00000080

        icon_flag = SHGFI_LARGEICON if size >= 32 else SHGFI_SMALLICON

        class SHFILEINFO(ctypes.Structure):
            _fields_ = [
                ("hIcon",      wintypes.HICON),
                ("iIcon",      ctypes.c_int),
                ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", ctypes.c_wchar * 260),
                ("szTypeName",  ctypes.c_wchar * 80),
            ]

        info = SHFILEINFO()
        shell32 = ctypes.windll.shell32
        ret = shell32.SHGetFileInfoW(
            dummy, FILE_ATTRIBUTE_NORMAL, ctypes.byref(info),
            ctypes.sizeof(info),
            SHGFI_ICON | SHGFI_USEFILEATTRIBUTES | icon_flag
        )
        if not ret or not info.hIcon:
            return None

        # Convert HICON → QPixmap via bitmap
        px = _hicon_to_pixmap(info.hIcon, size)
        ctypes.windll.user32.DestroyIcon(info.hIcon)
        return px

    except Exception:
        return None


def _hicon_to_pixmap(hicon, size: int) -> QPixmap:
    """Convert a Windows HICON handle to a QPixmap."""
    try:
        import ctypes
        from ctypes import wintypes

        user32  = ctypes.windll.user32
        gdi32   = ctypes.windll.gdi32

        # Get icon dimensions
        class ICONINFO(ctypes.Structure):
            _fields_ = [
                ("fIcon",    wintypes.BOOL),
                ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD),
                ("hbmMask",  wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP),
            ]

        # Use DrawIconEx to a memory DC → DIBSection
        BITMAPINFOHEADER_SIZE = 40

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize",          ctypes.c_uint32),
                ("biWidth",         ctypes.c_int32),
                ("biHeight",        ctypes.c_int32),
                ("biPlanes",        ctypes.c_uint16),
                ("biBitCount",      ctypes.c_uint16),
                ("biCompression",   ctypes.c_uint32),
                ("biSizeImage",     ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed",       ctypes.c_uint32),
                ("biClrImportant",  ctypes.c_uint32),
            ]

        W = H = size
        hdc     = user32.GetDC(0)
        hmem_dc = gdi32.CreateCompatibleDC(hdc)

        bmi = BITMAPINFOHEADER()
        bmi.biSize      = BITMAPINFOHEADER_SIZE
        bmi.biWidth     = W
        bmi.biHeight    = -H  # top-down
        bmi.biPlanes    = 1
        bmi.biBitCount  = 32
        bmi.biCompression = 0  # BI_RGB

        bits = ctypes.c_void_p()
        hbm  = gdi32.CreateDIBSection(hmem_dc, ctypes.byref(bmi), 0,
                                       ctypes.byref(bits), None, 0)
        gdi32.SelectObject(hmem_dc, hbm)

        # Clear to transparent
        DI_NORMAL = 3
        user32.DrawIconEx(hmem_dc, 0, 0, hicon, W, H, 0, None, DI_NORMAL)

        # Read pixels
        buf = (ctypes.c_uint8 * (W * H * 4))()
        ctypes.memmove(buf, bits, W * H * 4)

        # BGRA → RGBA
        data = bytearray(buf)
        for i in range(0, len(data), 4):
            data[i], data[i+2] = data[i+2], data[i]

        img = QImage(bytes(data), W, H, W * 4, QImage.Format.Format_RGBA8888)
        px  = QPixmap.fromImage(img)

        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hmem_dc)
        user32.ReleaseDC(0, hdc)
        return px

    except Exception:
        return None


# ── macOS ─────────────────────────────────────────────────────────────────────

def _mac_icon(ext: str, size: int) -> QPixmap:
    try:
        import subprocess, base64
        script = f'''
import AppKit, sys
ws = AppKit.NSWorkspace.sharedWorkspace()
icon = ws.iconForFileType_("{ext}")
icon.setSize_(({{0}}, {{0}}))
rep = icon.TIFFRepresentation()
bmp = AppKit.NSBitmapImageRep.imageRepWithData_(rep)
png = bmp.representationUsingType_properties_(AppKit.NSPNGFileType, None)
sys.stdout.buffer.write(png)
'''.format(size)
        data = subprocess.check_output([sys.executable, "-c", script],
                                        timeout=3)
        img = QImage()
        img.loadFromData(data, "PNG")
        return QPixmap.fromImage(img).scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        return None


# ── Linux / Qt fallback ───────────────────────────────────────────────────────

def _qt_icon(ext: str, size: int) -> QPixmap:
    try:
        # Create a temp file with the right extension so QFileIconProvider
        # can look up the themed icon
        fd, path = tempfile.mkstemp(suffix=f".{ext}")
        os.close(fd)
        try:
            provider = QFileIconProvider()
            icon     = provider.icon(QFileInfo(path))
            return icon.pixmap(size, size)
        finally:
            try: os.remove(path)
            except: pass
    except Exception:
        return None


def _fallback(size: int) -> QPixmap:
    try:
        from qfluentwidgets import FluentIcon
        return FluentIcon.DOCUMENT.icon().pixmap(size, size)
    except Exception:
        px = QPixmap(size, size)
        px.fill(Qt.transparent)
        return px


def ext_from_filename(filename: str) -> str:
    """Extract extension from filename, e.g. 'file.zip' → 'zip'."""
    _, ext = os.path.splitext(filename)
    return ext.lstrip(".").lower() if ext else "bin"
