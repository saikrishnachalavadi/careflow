from typing import Tuple

NON_MEDICAL_PATTERNS = [
    "weather", "sports", "politics", "recipe", "movie",
    "game", "joke", "story", "homework"
]


def check_medical_scope(message: str) -> Tuple[bool, str]:
    """
    Check if message is within medical scope.
    Returns (is_valid, warning_message)
    """
    message_lower = message.lower()

    for pattern in NON_MEDICAL_PATTERNS:
        if pattern in message_lower:
            return False, f"CareFlow is a medical-only platform. I can't help with {pattern}-related questions."

    return True, ""


def check_abuse_strikes(user_strikes: int) -> Tuple[bool, str]:
    """
    Check abuse strike status.
    Returns (is_allowed, message)
    """
    if user_strikes >= 3:
        return False, "Your account has been suspended due to repeated non-medical queries."
    elif user_strikes == 2:
        return True, "Final warning: One more non-medical query will suspend your account."
    elif user_strikes == 1:
        return True, "Please keep questions medical-related."
    return True, ""