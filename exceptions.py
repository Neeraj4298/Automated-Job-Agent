"""
exceptions.py — Custom exceptions for the Autonomous Job Application System.
"""

class JobAgentError(Exception):
    """Base class for exceptions in this project."""
    pass

class LoginError(JobAgentError):
    """Raised when login to a job portal fails."""
    pass

class BotDetectionError(JobAgentError):
    """Raised when CAPTCHA or bot detection blocks progress."""
    pass

class ElementNotFoundError(JobAgentError):
    """Raised when a critical DOM element cannot be located."""
    pass

class ApplicationSubmissionError(JobAgentError):
    """Raised when clicking the final apply/submit button fails."""
    pass
