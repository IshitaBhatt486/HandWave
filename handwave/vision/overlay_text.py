"""Legible on-frame text for the camera overlay, on any background."""

from __future__ import annotations

import cv2

TEXT_COLOR = (223, 231, 236)  # BGR ivory, matching the app theme
OUTLINE_COLOR = (18, 16, 14)  # BGR near-black


def put_text(frame, text: str, origin: tuple[int, int], scale: float = 0.6, thickness: int = 1) -> None:
    """Draw ivory text over a soft dark outline so it reads on light and dark scenes."""
    cv2.putText(frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, OUTLINE_COLOR, thickness + 3, cv2.LINE_AA)
    cv2.putText(frame, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, TEXT_COLOR, thickness, cv2.LINE_AA)
