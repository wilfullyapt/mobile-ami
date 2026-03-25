"""
EvalDay — daily conversation review, journal writing, and soul snapshot update.

Runs at 03:00 local time by default (configurable via ally.eval_day_time).
On every boot, performs an overdue-check: if the last eval ran more than
24 hours ago AND there are conversations on disk, triggers an immediate
background evaluation before the next scheduled run.

Process:
  1. Collect all conversation log entries from ~/.amini/conversations/ for
     the target date (or since last eval if crossing midnight).
  2. Ask the LLM to summarise: key topics, owner mentions, action items.
  3. Save the summary JSON to ~/.amini/memory/<YYYY-MM-DD>.json.
  4. Optionally append a dated section to soul.md (update_soul_on_eval).
  5. Run the journal session: LLM writes today's journal entry via tool call.
  6. Update the journal snapshot in soul.md:
       - Nightly (default): append today's one-liner headline to the snapshot section.
       - Reorganize day (every soul_reorganize_interval_days): full LLM pass that
         rewrites the snapshot section from journal metadata.
  7. Delegate to ally_agent.daily_update() → on_daily_reflect() hook.
  8. Record ~/.amini/.last_eval with the current UTC timestamp.
"""

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.ami_paths import AmiPaths
    from core.ally.soul import SoulManager

logger = logging.getLogger(__name__)

_EVAL_SYSTEM_PROMPT = """\
You are reviewing conversation logs from a personal AI voice assistant device.
Summarise the day's interactions in 3–5 concise bullet points. Focus on:
- Key topics discussed and questions asked
- Things the owner or family mentioned that are worth remembering
- Any recurring themes, mood, or emotional tone
- Action items, plans, or follow-ups mentioned
- Anything unusual or notable

Be specific but brief. These notes will inform the assistant's future responses.
Format as plain bullet points (no markdown headers).
"""


class EvalDay:
    """
    Schedules and runs the daily conversation review and journal update.

    Thread model:
      - One long-running daemon thread (_scheduler_thread) sleeps until the
        configured eval time, then calls run_now().
      - An optional second daemon thread runs the boot-check immediately.
      - run_now() is safe to call from any thread.
    """

    def __init__(
        self,
        paths: "AmiPaths",
        orchestrator,
        soul_manager: "SoulManager",
        ally_config: dict,
        ally_agent=None,
    ):
        self._paths = paths
        self._orch = orchestrator
        self._soul = soul_manager
        self._eval_time_str: str = ally_config.get("eval_day_time", "03:00")
        self._update_soul: bool = ally_config.get("update_soul_on_eval", False)
        self._journal_summary_last_n: int = int(ally_config.get("journal_summary_last_n", 100))
        self._soul_reorganize_interval_days: int = int(
            ally_config.get("soul_reorganize_interval_days", 30)
        )
        self._journal_snapshot_section: str = ally_config.get(
            "journal_snapshot_section", "Journal Entry Snapshot"
        )
        self._ally_agent = ally_agent
        self._running = False
        self._scheduler_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background scheduler and run a boot overdue-check."""
        self._running = True
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="eval-day-scheduler",
        )
        self._scheduler_thread.start()

        if self._is_overdue():
            logger.info("EvalDay: boot check — evaluation overdue, running now")
            threading.Thread(
                target=self.run_now,
                daemon=True,
                name="eval-day-boot",
            ).start()

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def run_now(self, target_date: Optional[date] = None) -> Optional[dict]:
        """
        Run a complete evaluation immediately.

        Returns a dict ``{date, summary}`` on success, or None if there are
        no conversations to review or the LLM is unavailable.
        """
        target_date = target_date or date.today()
        conversations = self._collect_conversations(target_date)
        date_str = target_date.isoformat()

        if not conversations:
            logger.info("EvalDay: no conversations to review for %s", date_str)
            self._write_eval_marker()
            return None

        logger.info(
            "EvalDay: evaluating %d conversation(s) for %s", len(conversations), date_str
        )
        summary = self._summarize(conversations)

        if summary:
            self._save_memory(target_date, summary, len(conversations))
            if self._update_soul:
                self._soul.append_daily_notes(summary, target_date)
            logger.info("EvalDay: conversation summary complete for %s", date_str)

        # --- Journal session ---
        if self._ally_agent is not None:
            self._run_journal_session(
                conversations=conversations,
                summary=summary or "",
                target_date=target_date,
            )

        # --- Snapshot update (nightly append OR periodic reorganize) ---
        self._update_journal_snapshot(target_date)

        # --- Daily reflection hook ---
        if self._ally_agent is not None:
            try:
                self._ally_agent.daily_update(context=None)
            except Exception as exc:
                logger.warning("EvalDay: ally daily_update failed: %s", exc)

        self._write_eval_marker()
        return {"date": date_str, "summary": summary}

    # ------------------------------------------------------------------
    # Journal session
    # ------------------------------------------------------------------

    def _run_journal_session(
        self,
        conversations: list[dict],
        summary: str,
        target_date: date,
    ) -> None:
        """Ask the ally agent's LLM to write today's journal entry via tool call."""
        if not hasattr(self._ally_agent, "run_journal_session"):
            return

        # Format ambient notes for today from disk
        notes_text = self._load_ambient_notes_text(target_date)

        try:
            self._ally_agent.run_journal_session(
                conversations_text=summary,
                notes_text=notes_text,
                date_str=target_date.isoformat(),
            )
        except Exception as exc:
            logger.warning("EvalDay: journal session failed: %s", exc)

    def _load_ambient_notes_text(self, target_date: date) -> str:
        """Load today's AmbientNote files and return formatted text."""
        notes_dir = self._paths.ally_notes_dir
        if not notes_dir.exists():
            return ""
        today_prefix = target_date.isoformat().replace("-", "")
        lines: list[str] = []
        for note_file in sorted(notes_dir.glob(f"{today_prefix}*.json")):
            try:
                from core.ally.ambient_note import AmbientNote
                note = AmbientNote.from_json(note_file.read_text())
                lines.append(note.formatted_text())
            except Exception as exc:
                logger.warning("EvalDay: could not load note %s: %s", note_file, exc)
        return "\n\n---\n\n".join(lines)

    # ------------------------------------------------------------------
    # Journal snapshot update
    # ------------------------------------------------------------------

    def _update_journal_snapshot(self, target_date: date) -> None:
        """
        Update the journal snapshot section in soul.md.

        Nightly: append a one-liner headline for today (no LLM call).
        Reorganize day: full LLM pass that rewrites the snapshot section.
        """
        snapshot_section = self._journal_snapshot_section

        if self._is_reorganize_day(target_date):
            logger.info("EvalDay: running journal snapshot reorganize")
            try:
                if self._ally_agent is not None and hasattr(
                    self._ally_agent, "run_journal_reorganize"
                ):
                    self._ally_agent.run_journal_reorganize(
                        snapshot_section=snapshot_section,
                        last_n=self._journal_summary_last_n,
                    )
                    self._write_reorg_marker(target_date)
            except Exception as exc:
                logger.warning("EvalDay: journal reorganize failed: %s", exc)
        else:
            self._append_journal_headline(target_date, snapshot_section)

    def _is_reorganize_day(self, target_date: date) -> bool:
        """True if enough days have passed since the last snapshot reorganization."""
        marker = self._paths.journal_reorg_marker_path
        if not marker.exists():
            return True  # First ever run — do a full reorganize
        try:
            last_reorg = date.fromisoformat(marker.read_text().strip())
            days_since = (target_date - last_reorg).days
            return days_since >= self._soul_reorganize_interval_days
        except (ValueError, OSError):
            return True

    def _append_journal_headline(self, target_date: date, snapshot_section: str) -> None:
        """Append a one-liner entry to the soul snapshot section (no LLM call)."""
        if self._ally_agent is None or self._ally_agent._journal_manager is None:
            return
        try:
            entry = self._ally_agent._journal_manager.read_date(target_date.isoformat())
            if entry is None:
                return
            topics = ", ".join(entry.topics[:3]) if entry.topics else "(no topics)"
            headline = f"- {target_date.isoformat()}: {topics}"
            self._soul.append_to_section(snapshot_section, headline)
            logger.info("EvalDay: appended journal headline for %s", target_date.isoformat())
        except Exception as exc:
            logger.warning("EvalDay: could not append journal headline: %s", exc)

    def _write_reorg_marker(self, target_date: date) -> None:
        marker = self._paths.journal_reorg_marker_path
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(target_date.isoformat())

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def _scheduler_loop(self) -> None:
        while self._running:
            wait_sec = self._seconds_until_next_run()
            logger.debug("EvalDay: next scheduled run in %.0f s", wait_sec)

            elapsed = 0.0
            while self._running and elapsed < wait_sec:
                chunk = min(60.0, wait_sec - elapsed)
                time.sleep(chunk)
                elapsed += chunk

            if self._running:
                logger.info("EvalDay: running scheduled evaluation")
                try:
                    self.run_now(date.today())
                except Exception as exc:
                    logger.error("EvalDay: scheduled evaluation failed: %s", exc)

    def _seconds_until_next_run(self) -> float:
        now = datetime.now()
        h, m = self._parse_eval_time()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    def _parse_eval_time(self) -> tuple[int, int]:
        try:
            h_str, m_str = self._eval_time_str.split(":")
            return int(h_str), int(m_str)
        except (ValueError, AttributeError):
            return 3, 0

    def _is_overdue(self) -> bool:
        """True if last eval was >24h ago and conversations exist."""
        marker = self._paths.eval_marker_path
        if not marker.exists():
            return self._has_any_conversations()
        try:
            raw = marker.read_text().strip()
            last_eval = datetime.fromisoformat(raw)
            if not last_eval.tzinfo:
                last_eval = last_eval.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - last_eval).total_seconds() / 3600
            return age_h >= 24 and self._has_any_conversations()
        except (ValueError, OSError):
            return self._has_any_conversations()

    # ------------------------------------------------------------------
    # Conversation collection
    # ------------------------------------------------------------------

    def _collect_conversations(self, target_date: date) -> list[dict]:
        """
        Gather all conversation log entries from ~/.amini/conversations/
        whose filename starts with the target date (YYYY-MM-DD).
        """
        convs_dir = self._paths.conversations_dir
        if not convs_dir.exists():
            return []

        results: list[dict] = []
        date_prefix = target_date.isoformat()

        for agent_dir in convs_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            for log_file in agent_dir.glob(f"{date_prefix}*.json"):
                try:
                    data = json.loads(log_file.read_text())
                    entries = data if isinstance(data, list) else [data]
                    for entry in entries:
                        entry.setdefault("agent", agent_dir.name)
                        results.append(entry)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("EvalDay: could not read %s: %s", log_file, exc)

        results.sort(key=lambda e: e.get("timestamp", ""))
        return results

    def _has_any_conversations(self) -> bool:
        convs_dir = self._paths.conversations_dir
        if not convs_dir.exists():
            return False
        return any(
            any(d.glob("*.json"))
            for d in convs_dir.iterdir()
            if d.is_dir()
        )

    # ------------------------------------------------------------------
    # LLM summarisation
    # ------------------------------------------------------------------

    def _summarize(self, conversations: list[dict]) -> Optional[str]:
        try:
            from core.models.registry import ModelRole
            llm = self._orch.get(ModelRole.LLM)
        except Exception as exc:
            logger.warning("EvalDay: LLM unavailable: %s", exc)
            return None

        lines: list[str] = []
        for c in conversations:
            ts = c.get("timestamp", "")[:16]
            agent = c.get("agent", "?")
            user_text = c.get("user", c.get("transcript", "")).strip()
            ai_text = c.get("response", c.get("assistant", "")).strip()
            if user_text:
                lines.append(f"[{ts} {agent}] User: {user_text}")
            if ai_text:
                lines.append(f"[{ts} {agent}] AI: {ai_text}")

        messages = [
            {"role": "system", "content": _EVAL_SYSTEM_PROMPT},
            {"role": "user", "content": "Conversations:\n\n" + "\n".join(lines)},
        ]
        try:
            return llm.chat(messages)
        except Exception as exc:
            logger.error("EvalDay: LLM summarisation failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_memory(self, target_date: date, summary: str, count: int) -> None:
        mem_dir = self._paths.memory_dir
        mem_dir.mkdir(parents=True, exist_ok=True)
        mem_path = mem_dir / f"{target_date.isoformat()}.json"
        mem_path.write_text(json.dumps({
            "date": target_date.isoformat(),
            "conversation_count": count,
            "summary": summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2))
        logger.info("EvalDay: memory saved → %s", mem_path)

    def _write_eval_marker(self) -> None:
        self._paths.eval_marker_path.parent.mkdir(parents=True, exist_ok=True)
        self._paths.eval_marker_path.write_text(datetime.now(timezone.utc).isoformat())
