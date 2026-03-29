"""
SoulSectionManager — document model for soul.md.

Parses soul.md into an ordered list of SoulSection objects (one per markdown
heading, plus an optional preamble), supports CRUD and reorder operations,
and serializes back to markdown with full round-trip fidelity.

Any heading level is supported (# through ######). The Ally chooses levels;
this class imposes no structure.

Usage::

    ssm = SoulSectionManager()
    sections = ssm.parse(soul_text)
    sections = ssm.update(sections, "Purpose", "New purpose text.")
    sections = ssm.add(sections, "Growth Notes", "First note.", after="Purpose")
    soul_text = ssm.serialize(sections)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Matches any ATX heading: one or more # chars, a space, then the heading text.
_HEADING_RE = re.compile(r"^(#{1,6}) (.+)$", re.MULTILINE)


@dataclass
class SoulSection:
    """One section of soul.md."""
    heading: Optional[str]   # None = preamble content before first heading
    level: int               # 1–6; 0 for preamble
    content: str             # raw text after the heading line (includes leading \n)


class SoulSectionManager:
    """
    Parse, manipulate, and serialize soul.md sections.

    All mutation methods return a new list; they do not mutate in place.
    """

    # ------------------------------------------------------------------
    # Parse / serialize
    # ------------------------------------------------------------------

    def parse(self, text: str) -> list[SoulSection]:
        """
        Parse soul.md text into an ordered list of SoulSection objects.

        A preamble SoulSection (heading=None, level=0) is prepended when
        content exists before the first heading. Empty preambles are omitted.
        """
        sections: list[SoulSection] = []
        matches = list(_HEADING_RE.finditer(text))

        if not matches:
            if text:
                sections.append(SoulSection(heading=None, level=0, content=text))
            return sections

        # Preamble — text before the first heading
        preamble = text[: matches[0].start()]
        if preamble:
            sections.append(SoulSection(heading=None, level=0, content=preamble))

        for i, m in enumerate(matches):
            level = len(m.group(1))
            heading = m.group(2).strip()
            content_start = m.end()
            content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[content_start:content_end]
            sections.append(SoulSection(heading=heading, level=level, content=content))

        return sections

    def serialize(self, sections: list[SoulSection]) -> str:
        """
        Reconstruct soul.md text from a list of SoulSection objects.

        Round-trips cleanly with parse() as long as section content is not
        modified externally.
        """
        parts: list[str] = []
        for s in sections:
            if s.heading is None:
                parts.append(s.content)
            else:
                prefix = "#" * s.level
                parts.append(f"{prefix} {s.heading}{s.content}")
        return "".join(parts)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_headings(self, sections: list[SoulSection]) -> list[str]:
        """Return ordered list of heading strings (preamble excluded)."""
        return [s.heading for s in sections if s.heading is not None]

    def find(self, sections: list[SoulSection], heading: str) -> Optional[SoulSection]:
        """Return the section with the given heading (case-insensitive), or None."""
        target = heading.strip().lower()
        for s in sections:
            if s.heading is not None and s.heading.lower() == target:
                return s
        return None

    # ------------------------------------------------------------------
    # Mutate — all return a new list
    # ------------------------------------------------------------------

    def update(
        self,
        sections: list[SoulSection],
        heading: str,
        content: str,
    ) -> list[SoulSection]:
        """
        Replace the content of an existing section.

        If the section does not exist, it is appended at the end (same as add).
        The level of the existing section is preserved.
        """
        target = heading.strip().lower()
        normalized = self._normalize_content(content)
        result = list(sections)
        for i, s in enumerate(result):
            if s.heading is not None and s.heading.lower() == target:
                result[i] = SoulSection(
                    heading=s.heading, level=s.level, content=normalized
                )
                return result
        # Not found — append
        return self.add(sections, heading, content)

    def add(
        self,
        sections: list[SoulSection],
        heading: str,
        content: str,
        level: int = 2,
        after: Optional[str] = None,
        position: Optional[int] = None,
    ) -> list[SoulSection]:
        """
        Insert a new section.

        Priority:
          1. ``after`` — insert immediately after the named heading.
          2. ``position`` — insert at the given index (0 = before preamble would
             displace preamble; preamble is always kept first).
          3. Default: append at end.

        The preamble (heading=None) is always kept as the first element.
        """
        normalized = self._normalize_content(content)
        new_sec = SoulSection(heading=heading.strip(), level=level, content=normalized)
        result = list(sections)

        if after is not None:
            target = after.strip().lower()
            for i, s in enumerate(result):
                if s.heading is not None and s.heading.lower() == target:
                    result.insert(i + 1, new_sec)
                    return result
            # Named section not found — fall through to append

        if position is not None:
            # Clamp: never insert before the preamble
            preamble_count = sum(1 for s in result if s.heading is None)
            idx = max(preamble_count, position)
            result.insert(idx, new_sec)
            return result

        result.append(new_sec)
        return result

    def remove(
        self,
        sections: list[SoulSection],
        heading: str,
    ) -> list[SoulSection]:
        """Remove the section with the given heading. No-op if not found."""
        target = heading.strip().lower()
        return [
            s for s in sections
            if not (s.heading is not None and s.heading.lower() == target)
        ]

    def reorder(
        self,
        sections: list[SoulSection],
        new_order: list[str],
    ) -> list[SoulSection]:
        """
        Reorder sections according to ``new_order`` (list of heading strings).

        - The preamble (heading=None) is always kept first.
        - Sections in ``new_order`` appear in that order.
        - Sections not mentioned in ``new_order`` are appended at the end in
          their original relative order.
        """
        preamble = [s for s in sections if s.heading is None]
        named = {
            s.heading.lower(): s
            for s in sections
            if s.heading is not None
        }
        seen: set[str] = set()
        result: list[SoulSection] = list(preamble)

        for heading in new_order:
            key = heading.strip().lower()
            if key in named:
                result.append(named[key])
                seen.add(key)

        # Append unmentioned sections in original order
        for s in sections:
            if s.heading is not None and s.heading.lower() not in seen:
                result.append(s)

        return result

    def append_line(
        self,
        sections: list[SoulSection],
        heading: str,
        line: str,
        level: int = 2,
    ) -> list[SoulSection]:
        """
        Append a single line of text to an existing section's content.

        If the section does not exist, creates it with ``line`` as its content.
        Does not normalize (strip) the existing content — preserves accumulated
        entries such as bullet-point journal headlines.
        """
        target = heading.strip().lower()
        result = list(sections)
        for i, s in enumerate(result):
            if s.heading is not None and s.heading.lower() == target:
                new_content = s.content.rstrip("\n") + "\n" + line.strip() + "\n"
                result[i] = SoulSection(
                    heading=s.heading, level=s.level, content=new_content
                )
                return result
        # Not found — create
        return self.add(sections, heading, line, level=level)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_content(content: str) -> str:
        """Ensure section content starts with \\n and ends with \\n\\n."""
        stripped = content.strip()
        if not stripped:
            return "\n"
        return "\n" + stripped + "\n\n"
