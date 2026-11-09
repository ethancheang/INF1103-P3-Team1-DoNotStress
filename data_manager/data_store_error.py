"""DataStoreError: the record store could not be read or written."""


class DataStoreError(Exception):
    """Raised when saved records cannot be loaded or a record cannot be saved.

    Examples: the records file is corrupt (it is then never overwritten, so
    no saved check-in is lost), the folder is not writable, or a record that
    was not processed by the AI is refused. Callers catch this one type and
    show a calm "please try again" message instead of crashing.
    """
