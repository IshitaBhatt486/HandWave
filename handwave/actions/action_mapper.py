"""Cooldown-protected mapping from recognized gestures to local actions."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from handwave.actions.action_definition import ActionDefinition
from handwave.actions.action_executor import ActionExecutor
from handwave.config.gesture_config import (
    DEFAULT_ENABLED_GESTURES,
    default_gesture_bindings,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActionOutcome:
    """Why the most recent ``execute()`` call did or didn't fire an action."""

    gesture: str | None
    executed: bool
    action_description: str = "No action"
    blocked_reason: str | None = None


class ActionMapper:
    """Map gesture transitions to Windows media keys without rapid repeats."""

    def __init__(
        self,
        cooldown: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        pyautogui_module: Any = None,
        keyboard_module: Any = None,
        program_launcher: Callable[..., Any] | None = None,
        executor: ActionExecutor | None = None,
        dispatcher: Callable[[str, Callable[[], None]], None] | None = None,
        gesture_bindings: dict[str, object] | None = None,
        enabled_gestures: dict[str, bool] | None = None,
    ) -> None:
        if cooldown < 0:
            raise ValueError("Cooldown cannot be negative")
        self.cooldown = cooldown
        self._clock = clock
        self._dispatcher = dispatcher
        executor_options = {}
        if pyautogui_module is not None:
            executor_options["pyautogui_module"] = pyautogui_module
        if keyboard_module is not None:
            executor_options["keyboard_module"] = keyboard_module
        if program_launcher is not None:
            executor_options["program_launcher"] = program_launcher
        self._executor = executor or ActionExecutor(**executor_options)
        source_bindings = default_gesture_bindings() if gesture_bindings is None else gesture_bindings
        self._gesture_bindings = self._normalize_bindings(source_bindings)
        self._enabled_gestures = (
            DEFAULT_ENABLED_GESTURES.copy()
            if enabled_gestures is None
            else enabled_gestures.copy()
        )
        self._last_trigger_time = float("-inf")
        self._active_gesture: str | None = None
        self._registered_actions: dict[str, Callable[[], None]] = {}
        self._active_since: float | None = None
        self._active_executed = False
        self.last_outcome: ActionOutcome | None = None

    def apply_settings(
        self,
        cooldown: float | None = None,
        gesture_bindings: dict[str, object] | None = None,
        enabled_gestures: dict[str, bool] | None = None,
    ) -> None:
        """Swap in new bindings/cooldown in place (e.g. on profile switch).

        This never recreates the mapper, the action queue, or the executor, so a
        profile switch cannot interrupt in-flight recognition or queued actions.
        """
        if cooldown is not None:
            if cooldown < 0:
                raise ValueError("Cooldown cannot be negative")
            self.cooldown = cooldown
        if gesture_bindings is not None:
            self._gesture_bindings = self._normalize_bindings(gesture_bindings)
        if enabled_gestures is not None:
            self._enabled_gestures = dict(enabled_gestures)

    def register(self, gesture: str, action: Callable[[], None]) -> None:
        """Register or replace an action while retaining cooldown protection."""
        self._registered_actions[gesture] = action
        self._enabled_gestures[gesture] = True

    def execute(self, gesture: str | None) -> bool:
        """Execute once per gesture pose, subject to the global cooldown.

        Records the reason for a blocked or failed action on ``last_outcome``
        (e.g. for an action-history/diagnostics view), without changing this
        method's boolean return contract for existing callers.
        """
        action_definition = ActionDefinition.from_data(
            self._gesture_bindings.get(gesture or "", ActionDefinition())
        )
        description = action_definition.describe()
        registered = self._registered_actions.get(gesture or "")

        def blocked(reason: str) -> bool:
            self.last_outcome = ActionOutcome(gesture, False, description, reason)
            return False

        if not self._enabled_gestures.get(gesture or "", False):
            self._reset_active_gesture()
            return blocked("gesture disabled")
        if registered is None and action_definition.type == "none":
            self._reset_active_gesture()
            return blocked("no action bound")
        if gesture == self._active_gesture and self._active_executed:
            return blocked("gesture not re-armed")
        now = self._clock()
        if gesture != self._active_gesture:
            self._active_gesture = gesture
            self._active_since = now
            self._active_executed = False
        assert self._active_since is not None
        if now - self._active_since < action_definition.effective_hold_duration:
            return blocked("hold duration not met")
        effective_cooldown = self.cooldown if action_definition.cooldown is None else action_definition.cooldown
        if now - self._last_trigger_time < effective_cooldown:
            logger.debug("Action for %s suppressed by cooldown", gesture)
            return blocked("cooldown active")

        try:
            callback = registered or self._executor.callback_for(action_definition)
            if self._dispatcher is None:
                callback()
            else:
                self._dispatcher(description, callback)
            self._last_trigger_time = now
            self._active_executed = True
            logger.info("Accepted action for gesture %s", gesture)
            self.last_outcome = ActionOutcome(gesture, True, description, None)
            return True
        except Exception as exc:
            logger.exception("Action failed for gesture %s", gesture)
            return blocked(f"action failed: {exc}")

    @staticmethod
    def _normalize_bindings(bindings: dict[str, object]) -> dict[str, ActionDefinition]:
        """Validate configuration input at the action-system boundary."""
        return {
            gesture: ActionDefinition.from_data(action)
            for gesture, action in bindings.items()
        }

    def _reset_active_gesture(self) -> None:
        """Clear re-arm state when no eligible gesture remains."""
        self._active_gesture = None
        self._active_since = None
        self._active_executed = False
