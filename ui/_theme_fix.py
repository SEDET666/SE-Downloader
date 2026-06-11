"""
Helper to apply transparent background to ScrollArea and its viewport/container.
Must be called after the widget is constructed.
"""
from PySide6.QtWidgets import QScrollArea, QWidget


def make_transparent(scroll: QScrollArea, container: QWidget = None):
    """Make scroll area and its contents fully transparent for theme compat."""
    scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget { background: transparent; border: none; }")
    if scroll.viewport():
        scroll.viewport().setStyleSheet("background: transparent;")
    if container:
        container.setStyleSheet("background: transparent;")
        container.setAutoFillBackground(False)
