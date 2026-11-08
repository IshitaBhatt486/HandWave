"""Local execution backend for validated action definitions."""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from typing import Any

import pyautogui

from handwave.actions.action_definition import ActionDefinition, MacroStep, parse_hotkey
from handwave import platforms

try:
    import keyboard
except ImportError:  # not installed on macOS (it needs root there)
    keyboard = None

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Execute one validated action locally without invoking a command shell."""

    SAFE_NAVIGATION_INPUTS = {
        ("key", "esc"),
        ("hotkey", "alt+tab"),
        ("hotkey", "win+tab"),
        ("hotkey", "win+ctrl+left"),
        ("hotkey", "win+ctrl+right"),
        # macOS defaults (Spaces, Mission Control, app switcher)
        ("hotkey", "ctrl+left"),
        ("hotkey", "ctrl+right"),
        ("hotkey", "ctrl+up"),
        ("hotkey", "command+tab"),
    }
    # Windows key names → macOS key names, so shared bindings still work.
    MAC_KEY_NAMES = {"win": "command", "alt": "option"}

    def __init__(
        self,
        pyautogui_module: Any = pyautogui,
        keyboard_module: Any = keyboard,
        program_launcher: Callable[..., Any] = subprocess.Popen,
        sleep: Callable[[float], None] = time.sleep,
        macos: bool | None = None,
        media_key_poster: Callable[[str], None] | None = None,
    ) -> None:
        self._pyautogui = pyautogui_module
        self._macos = platforms.is_macos() if macos is None else macos
        # The ``keyboard`` package needs root on macOS and is unreliable there;
        # pyautogui (Quartz events) is used instead.
        self._keyboard = None if self._macos else keyboard_module
        if media_key_poster is None and self._macos:
            from handwave.platforms.macos import post_media_key as media_key_poster
        self._media_key_poster = media_key_poster
        self._program_launcher = program_launcher
        self._sleep = sleep
        self._pyautogui.FAILSAFE = True

    def callback_for(self, action: ActionDefinition) -> Callable[[], None]:
        """Create the callback placed on the existing action queue."""
        return lambda: self.execute(action)

    def execute(self, action: ActionDefinition) -> None:
        if action.type == "none":
            return
        if action.type == "media":
            self._safe_input(action, lambda: self._execute_media(str(action.value)))
        elif action.type == "key":
            self._safe_input(action, lambda: self._execute_key(str(action.value)))
        elif action.type == "hotkey":
            self._safe_input(action, lambda: self._execute_hotkey(str(action.value)))
        elif action.type == "mouse":
            self._safe_input(action, lambda: self._execute_mouse(str(action.value)))
        elif action.type == "text":
            self._pyautogui.write(str(action.value))
        elif action.type == "macro":
            self.execute_macro(action.value)
        elif action.type == "command":
            # A validated argv sequence and shell=False avoid shell-string execution.
            argv = list(action.value)
            if self._macos:
                from handwave.platforms.macos import open_application_command

                argv = open_application_command(argv)
            self._program_launcher(argv, shell=False)
        else:  # Defensive guard if an object bypassed ActionDefinition validation.
            raise ValueError(f"Unsupported action type: {action.type}")

    def execute_macro(self, steps: tuple[MacroStep, ...]) -> None:
        """Replay macro steps in order on the action worker thread.

        Runs off the recognition thread (see ActionQueue), so waits never
        delay gesture recognition. A failing step stops the macro, so later
        steps never run against an unexpected state.
        """
        for step in steps:
            if step.type == "wait":
                self._sleep(int(step.value) / 1000.0)
            elif step.type == "text":
                self._pyautogui.write(step.value)
            else:
                self.execute(ActionDefinition(step.type, step.value))

    @staticmethod
    def _safe_input(action: ActionDefinition, callback: Callable[[], None]) -> None:
        """Fail closed when Windows input injection is unavailable.

        Navigation bindings are ordinary, configurable key/hotkey actions. If
        the OS rejects input (for example on a locked desktop), logging and a
        no-op are safer than interrupting the recognition worker or launching
        an application-specific fallback.
        """
        try:
            callback()
        except Exception as exc:
            if (action.type, str(action.value)) not in ActionExecutor.SAFE_NAVIGATION_INPUTS:
                raise
            logger.warning("Local input action unavailable (%s): %s", action.describe(), exc)

    def _mac_keys(self, keys):
        return [self.MAC_KEY_NAMES.get(key, key) for key in keys] if self._macos else list(keys)

    def _execute_key(self, value: str) -> None:
        value = self._mac_keys([value])[0]
        try:
            self._pyautogui.press(value)
        except Exception:
            if self._keyboard is None:
                raise
            logger.info("PyAutoGUI key injection failed; using keyboard fallback")
            self._keyboard.send(value)

    def _execute_hotkey(self, value: str) -> None:
        keys = self._mac_keys(parse_hotkey(value))
        try:
            self._pyautogui.hotkey(*keys)
        except Exception:
            if self._keyboard is None:
                raise
            logger.info("PyAutoGUI hotkey injection failed; using keyboard fallback")
            self._keyboard.send("+".join(keys))

    def _execute_media(self, value: str) -> None:
        if self._media_key_poster is not None:
            # macOS: post real media-key events (controls the Now Playing app).
            self._media_key_poster(value)
            return
        pyautogui_keys = {
            "play_pause": "playpause",
            "volume_up": "volumeup",
            "volume_down": "volumedown",
            "mute": "volumemute",
        }
        if value in pyautogui_keys:
            self._pyautogui.press(pyautogui_keys[value])
            return
        keyboard_keys = {"next_track": "next track", "previous_track": "previous track"}
        if self._keyboard is not None:
            self._keyboard.send(keyboard_keys[value])
        else:
            fallback = {"next_track": "nexttrack", "previous_track": "prevtrack"}
            logger.warning("The 'keyboard' package is unavailable; using PyAutoGUI fallback")
            self._pyautogui.press(fallback[value])

    def _execute_mouse(self, value: str) -> None:
        if value.endswith("_click"):
            self._pyautogui.click(button=value.removesuffix("_click"))
        else:
            self._pyautogui.scroll(1 if value == "scroll_up" else -1)
