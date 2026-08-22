class ExportSessionNotFound(Exception):
    pass


class ExportPending(Exception):
    """User hasn't finished the browser authorization step yet — not a failure, keep polling."""


class ExportExpired(Exception):
    """The device code expired before the user completed authorization."""


class ExportDenied(Exception):
    """The user declined authorization."""


class ExportOAuthError(Exception):
    """Any other OAuth error Google returned."""


class ExportProviderError(Exception):
    """The authorized provider rejected playlist creation or item insertion."""


class ExportCapacityReached(Exception):
    """The ephemeral export session store is full."""
