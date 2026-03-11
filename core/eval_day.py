"""
EvalDay — daily conversation review and memory update.

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
  5. Record ~/.amini/.last_eval with the current UTC timestamp.
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
    Schedules and runs the daily conversation review.

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

        if not conversations:
            logger.info("EvalDay: no conversations to review for %s", target_date)
            self._write_eval_marker()
            return None

        logger.info("EvalDay: evaluating %d conversation(s) for %s", len(conversations), target_date)
        summary = self._summarize(conversations)

        if summary:
            self._save_memory(target_date, summary, len(conversations))
            if self._update_soul:
                self._soul.append_daily_notes(summary, target_date)
            logger.info("EvalDay: evaluation complete for %s", target_date)

        if self._ally_agent is not None:
            try:
                self._ally_agent.daily_update(context=None)
            except Exception as exc:
                logger.warning("EvalDay: ally daily_update failed: %s", exc)

        self._write_eval_marker()
        return {"date": target_date.isoformat(), "summary": summary}

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def _scheduler_loop(self) -> None:
        while self._running:
            wait_sec = self._seconds_until_next_run()
            logger.debug("EvalDay: next scheduled run in %.0f s", wait_sec)

            # Sleep in short chunks so the thread exits promptly when stopped
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
            return 3, 0  # fallback: 03:00

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
