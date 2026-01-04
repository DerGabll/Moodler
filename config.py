"""Configuration constants for Moodler application."""

APP_NAME = "Moodler"
PROMPT_TEXT = (
    "Welche Antwortmöglichkeiten, glaubst du, sind richtig? "
    "Die Antwortmöglichkeiten sind mit Buchstaben geordnet. Schreibe in deiner Antwort "
    "nur Buchstaben mit einem Leerzeichen getrennt und nur Buchstaben, die die richtige Lösung beinhalten. "
    "Die Antwort sollte gut durchgedacht sein."
)
MODEL_NAME = "gpt-5"
TEMP_SCREENSHOT_NAME = "moodler_screenshot.png"

HOTKEYS = {
    "capture": "alt+t",
    "send": "alt+enter", 
    "reset": "alt+r",
    "quit": "alt+q",
}