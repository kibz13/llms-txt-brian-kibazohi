"""
Domain exception hierarchy for llms.txt.

All exceptions carry a user_message suitable for display to end users.
Internal details are preserved in the exception args for logging.
"""


class LlmsTxtError(Exception):
    """Base class for all domain exceptions."""
    user_message: str = "An unexpected error occurred."


class CrawlError(LlmsTxtError):
    """Raised when the crawler fails to retrieve usable pages."""
    user_message = "We were unable to crawl this site."


class AntibotError(CrawlError):
    """Raised when the site actively blocks automated requests."""
    user_message = (
        "This site is blocking automated requests (antibot protection). "
        "We were unable to crawl any pages."
    )


class UnreachableError(CrawlError):
    """Raised when no pages could be fetched (network issue, redirect loop, etc.)."""
    user_message = (
        "No pages could be crawled from this site. "
        "It may be unreachable or blocking automated requests."
    )


class GenerationError(LlmsTxtError):
    """Raised when llms.txt generation fails after a successful crawl."""
    user_message = "We were unable to generate llms.txt for this site."


class JobCancelledError(LlmsTxtError):
    """Raised at a safe checkpoint when the job has been marked cancel_requested."""
    user_message = "Generation was cancelled."
