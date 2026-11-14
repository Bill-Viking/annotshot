"""The pages where users can report a bug or suggest an improvement."""
import platform
from urllib.parse import urlencode

from . import __version__

CHOOSER_URL = "https://github.com/Bill-Viking/annotshot/issues/new/choose"
EMAIL = None  # Add the Stet Software feedback email when a mailbox exists.


def bug_url() -> str:
    """A bug form with the app version and operating system filled in."""
    query = urlencode({"template": "bug.yml", "version": __version__,
                       "os": f"{platform.system()} {platform.release()}"})
    return CHOOSER_URL.removesuffix("/choose") + "?" + query
