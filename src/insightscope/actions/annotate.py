"""Draw a finding onto the frame that proves it.

Plain OpenCV drawing, no model involved. The overlay is deliberately self-describing
(rule id, severity, subject, said/seen values) so a screenshot pasted into a review is
understandable without the database.

Hershey fonts are ASCII-only, so text is sanitised before drawing rather than silently
rendering boxes.
"""

from __future__ import annotations

from pathlib import Path

import cv2

from insightscope.domain.models import Finding

BANNER_HEIGHT = 54
_TEXT_LIMIT = 42


def ascii_text(value: str, limit: int = _TEXT_LIMIT) -> str:
    cleaned = value.encode("ascii", "ignore").decode("ascii")
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit]


def annotate_finding(image_path: Path, finding: Finding, output_path: Path) -> Path | None:
    """Write an annotated copy. Returns None when the source cannot be read."""
    image = cv2.imread(str(image_path))
    if image is None:
        return None

    height, width = image.shape[:2]
    banner_height = min(BANNER_HEIGHT, height)

    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (width, banner_height), (0, 0, 0), -1)
    image = cv2.addWeighted(overlay, 0.6, image, 0.4, 0)

    discrepancy = finding.discrepancy
    headline = (
        f"{discrepancy.rule_id}  {discrepancy.severity.upper()}  "
        f"{ascii_text(discrepancy.subject_id)}"
    )
    detail = (
        f"said: {ascii_text(discrepancy.said_value) or '-'}   "
        f"seen: {ascii_text(discrepancy.seen_value) or '-'}"
    )

    cv2.putText(
        image,
        headline,
        (10, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        image,
        detail,
        (10, 44),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (200, 220, 255),
        1,
        cv2.LINE_AA,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), image):
        return None
    return output_path
