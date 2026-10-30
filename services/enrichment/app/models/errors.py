class ProcessingError(Exception):
    """Safe, bounded reason codes, never include raw exception text or secret URLs."""
    def __init__(self, reason, *, transient=False, rejected=False, metadata=None):
        super().__init__(reason)
        self.reason = reason
        self.transient = transient
        self.rejected = rejected
        self.metadata = metadata or {}
