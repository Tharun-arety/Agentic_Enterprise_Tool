"""Revision letter sequencing, shared by parts and documents.

A, B, C … then AA. I, O and Q are skipped: handwritten or scanned onto a
drawing they read as 1, 0 and O, and a revision anyone can misread is a
revision two people can disagree about.
"""

from __future__ import annotations

REVISION_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"


def next_revision(current: str | None) -> str:
    if not current:
        return REVISION_LETTERS[0]
    last = current[-1].upper()
    index = REVISION_LETTERS.find(last)
    if index == -1 or index == len(REVISION_LETTERS) - 1:
        return current + REVISION_LETTERS[0]
    return current[:-1] + REVISION_LETTERS[index + 1]
