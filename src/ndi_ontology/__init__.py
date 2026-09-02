"""
ndi_ontology - Ontology lookup system.

MATLAB equivalent: ndi-ontology-matlab, src/ndi/+ndi/ontology.m and
src/ndi/+ndi/+ontology/*.m

Unified interface for looking up terms across multiple biomedical ontologies.

Usage::

    from ndi_ontology import lookup
    result = lookup('CL:0000540')  # Cell Ontology: neuron
    result = lookup('NDIC:1')      # NDI Controlled Vocabulary

NDI-python re-exports this package as ``ndi.ontology``, so
``from ndi.ontology import lookup`` keeps working there and keeps the name
aligned with MATLAB's ``ndi.ontology``. See ndi_matlab_python_bridge.yaml
for why the distribution is named ndi_ontology rather than ndi.ontology.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pydantic

from .providers import PROVIDER_REGISTRY

# ---------------------------------------------------------------------------
# Lookup result type
# ---------------------------------------------------------------------------


class NDIOntologyLookupError(Exception):
    """A lookup did not resolve to a term.

    MATLAB's ndi.ontology.lookup raises on every failure -- an unknown prefix,
    a term that is not in the ontology, an API that did not answer -- with
    assorted identifiers (ndi:ontology:NDIC:IDNotFound,
    ndi:ontology:EDAM:LookupFailed, and so on) that callers catch as one
    MException. This is that single type.

    It replaces an empty OntologyResult, which could not be told apart from a
    resolved term with blank fields and, worse, was returned for a throttled
    request as readily as for a term that genuinely does not exist. Four of
    the defects found while porting this namespace reached production behind
    exactly that ambiguity: three providers returning nothing because their
    data source 404'd or their query was malformed, and a cache that made a
    transient failure permanent. Each was invisible because "no result" was a
    valid-looking answer.

    The message names the lookup string and what went wrong. The originating
    error, when there is one, is chained (`raise ... from`), so a transport
    failure is still diagnosable even though it is not separately typed.
    """


class OntologyResult:
    """Result from an ontology lookup.

    Supports both access styles, deliberately:

        result = lookup('CL:0000540')
        result.id                                   # attribute access
        id, name, prefix, definition, syn, short = lookup('CL:0000540')
        id, name, *_ = lookup('CL:0000540')         # MATLAB-shaped, first N

    MATLAB's ndi.ontology.lookup declares six separate output arguments
    (ontology.m:125), and the porting guide's section 5 requires those to
    become a Python tuple in declaration order. Returning a single object
    satisfied neither, and it cost something: NDI-python wrote
    ``ont_id, name = lookup(...)`` at three call sites, which raised
    TypeError into an ``except Exception`` and silently fell back to using
    the input string as both id and name. Species, Strain and
    biological-sex lookups had never resolved.

    Note the one place Python cannot follow MATLAB: MATLAB lets a caller
    request fewer outputs than are declared, while Python unpacking demands
    an exact count. ``id, name = lookup(...)`` still raises -- now
    ValueError rather than TypeError -- so the MATLAB-shaped read spells the
    remainder explicitly as ``id, name, *_``.
    """

    #: MATLAB's output order, from `[id, name, prefix, definition, synonyms,
    #: shortName] = lookup(...)` at ontology.m:125. __iter__ yields these by
    #: reading __slots__, so the tuple order cannot drift from the field list;
    #: test_iteration_order_matches_matlab pins it to the MATLAB declaration.
    __slots__ = ("id", "name", "prefix", "definition", "synonyms", "short_name")

    def __init__(
        self,
        id: str = "",
        name: str = "",
        prefix: str = "",
        definition: str = "",
        synonyms: list[str] | None = None,
        short_name: str = "",
    ):
        self.id = id
        self.name = name
        self.prefix = prefix
        self.definition = definition
        self.synonyms = synonyms or []
        self.short_name = short_name

    def __repr__(self) -> str:
        return f"OntologyResult(id={self.id!r}, name={self.name!r})"

    def __bool__(self) -> bool:
        return bool(self.id or self.name)

    def __iter__(self) -> Iterator[Any]:
        """Yield the six fields in MATLAB's declared output order."""
        return iter([getattr(self, field) for field in OntologyResult.__slots__])

    def __len__(self) -> int:
        """Number of output arguments, matching MATLAB's six."""
        return len(OntologyResult.__slots__)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "prefix": self.prefix,
            "definition": self.definition,
            "synonyms": self.synonyms,
            "short_name": self.short_name,
        }


# ---------------------------------------------------------------------------
# Prefix registry
# ---------------------------------------------------------------------------


#: Cached prefix -> ontology-name map, read from ontology_list.json.
_prefix_map_cache: dict[str, str] | None = None


def _load_prefix_map() -> dict[str, str]:
    """Return the prefix -> ontology name map from ontology_list.json.

    ontology_list.json is the single source. There used to be a fourteen-entry
    literal here that the JSON was merged *into*, and the two were free to
    disagree: the JSON registered `Uberon` and `NCIT` while PROVIDER_REGISTRY
    had neither, so `lookup('UBERON:0000948')` resolved a prefix to a provider
    that did not exist and answered with an empty result. Registering an
    ontology now means editing this file and adding a provider class -- which
    is what NDI-python#98 asked for.

    A missing or unreadable file raises rather than silently yielding an empty
    map. The file ships inside the package, so its absence is a broken install,
    and an empty map would turn every lookup into a silent miss -- the failure
    mode this namespace has already produced four times.
    """
    global _prefix_map_cache
    if _prefix_map_cache is not None:
        return _prefix_map_cache

    from .paths import ONTOLOGY_LIST_FILE

    with open(ONTOLOGY_LIST_FILE) as f:
        data = json.load(f)

    mapping: dict[str, str] = {}
    for entry in data.get("prefix_ontology_mappings", []):
        prefix = entry.get("prefix", "")
        ontology_name = entry.get("ontology_name", "")
        if prefix and ontology_name:
            mapping[prefix] = ontology_name

    if not mapping:
        raise RuntimeError(
            f"no prefix mappings in {ONTOLOGY_LIST_FILE}; the packaged ontology "
            f"registry is empty or malformed, so every lookup would miss"
        )

    _prefix_map_cache = mapping
    return _prefix_map_cache


# ---------------------------------------------------------------------------
# Main lookup (with LRU cache)
# ---------------------------------------------------------------------------

_lookup_cache: dict[str, OntologyResult] = {}
_CACHE_MAX = 100


@pydantic.validate_call
def lookup(lookup_string: str) -> OntologyResult:
    """Look up a term in the appropriate ontology.

    MATLAB equivalent: ndi.ontology.lookup (ndi-ontology-matlab)

    Args:
        lookup_string: Prefixed string like ``'CL:0000540'`` or ``'NDIC:1'``.
            Use ``'clear'`` to flush the cache.

    Returns:
        OntologyResult with id, name, prefix, definition, synonyms.

    Raises:
        NDIOntologyLookupError: if the string carries no prefix, the prefix is
            not registered, the term is not in the ontology, or the provider
            could not answer. MATLAB raises in all four cases; this is the
            single Python type standing in for its assorted identifiers.
    """
    if lookup_string == "clear":
        # MATLAB's clearCache calls ndi.ontology.lookup('clear'); the sentinel
        # is not a lookup and does not raise.
        _lookup_cache.clear()
        return OntologyResult()

    # Check cache
    if lookup_string in _lookup_cache:
        return _lookup_cache[lookup_string]

    # Parse prefix
    if ":" not in lookup_string:
        raise NDIOntologyLookupError(
            f"{lookup_string!r} has no ontology prefix; expected 'PREFIX:term'"
        )

    prefix, remainder = lookup_string.split(":", 1)

    prefix_map = _load_prefix_map()

    # Case-insensitive prefix match
    provider_name = None
    for k, v in prefix_map.items():
        if k.lower() == prefix.lower():
            provider_name = v
            break

    if provider_name is None:
        raise NDIOntologyLookupError(
            f"unknown ontology prefix {prefix!r} in {lookup_string!r}; "
            f"known prefixes: {', '.join(sorted(prefix_map))}"
        )

    provider_cls = PROVIDER_REGISTRY.get(provider_name)
    if provider_cls is None:
        # A prefix registered in ontology_list.json with no provider behind it.
        # test_every_registered_prefix_has_a_provider exists to stop this
        # reaching a user, so treat it as the packaging error it is.
        raise NDIOntologyLookupError(
            f"ontology {provider_name!r} is registered for prefix {prefix!r} but "
            f"has no provider class; this is a defect in ndi_ontology, not in "
            f"{lookup_string!r}"
        )

    provider = provider_cls()
    try:
        result = provider.lookup_term(remainder, prefix)
    except Exception as exc:
        # Providers answer "not found" with an empty result and let genuine
        # errors escape. Chain the original so a transport failure stays
        # diagnosable even though it is not separately typed.
        raise NDIOntologyLookupError(f"lookup of {lookup_string!r} failed: {exc}") from exc

    if not result:
        raise NDIOntologyLookupError(f"{lookup_string!r} not found in ontology {provider_name}")

    # Only resolved terms reach here now, so the cache cannot hold a failure --
    # the same guarantee MATLAB gets from raising before its cache write at
    # ontology.m:330-336. The `if result` guard is kept as a belt-and-braces
    # against a provider returning something falsy through a path that does not
    # raise.
    if result:
        if len(_lookup_cache) >= _CACHE_MAX:
            # Remove oldest entry
            oldest = next(iter(_lookup_cache))
            del _lookup_cache[oldest]
        _lookup_cache[lookup_string] = result

    return result


def clearCache() -> None:
    """Clear all ontology caches.

    MATLAB equivalent: ndi.ontology.clearCache (ndi-ontology-matlab)
    """
    _lookup_cache.clear()


__all__ = ["NDIOntologyLookupError", "OntologyResult", "lookup", "clearCache"]
