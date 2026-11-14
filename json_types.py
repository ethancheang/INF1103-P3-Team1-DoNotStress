"""Type aliases for the JSON-shaped check-in data shared by every layer."""

from collections.abc import Mapping, Sequence

# Sequence and Mapping are read-only, so they are covariant: a dict[str, int]
# or list[str] counts as a JSONValue. With list and dict (invariant) the type
# checker rejects every nested dict whose values are narrower than JSONValue.
type JSONValue = (
    str | int | float | bool | None
    | Sequence[JSONValue] | Mapping[str, JSONValue]
)
type JSONObject = dict[str, JSONValue]
