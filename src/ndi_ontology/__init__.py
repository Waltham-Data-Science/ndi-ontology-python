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


# Map prefixes to provider class names (case-insensitive)
_PREFIX_MAP: dict[str, str] = {
    "CL": "CL",
    "OM": "OM",
    "NDIC": "NDIC",
    "NCIm": "NCIm",
    "CHEBI": "CHEBI",
    "NCBITaxon": "NCBITaxon",
    "taxonomy": "NCBITaxon",
    "WBStrain": "WBStrain",
    "SNOMED": "SNOMED",
    "RRID": "RRID",
    "EFO": "EFO",
    "PATO": "PATO",
    "PubChem": "PubChem",
    "EMPTY": "EMPTY",
}


def _load_prefix_map() -> dict[str, str]:
    """Load prefix mappings from ontology_list.json if available."""
    try:
        from .paths import ONTOLOGY_LIST_FILE

        json_path = ONTOLOGY_LIST_FILE
        if json_path.exists():
            with open(json_path) as f:
                data = json.load(f)
            for mapping in data.get("prefix_ontology_mappings", []):
                prefix = mapping.get("prefix", "")
                name = mapping.get("ontology_name", "")
                if prefix and name:
                    _PREFIX_MAP[prefix] = name
    except Exception:
        pass
    return _PREFIX_MAP


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
    """
    if lookup_string == "clear":
        _lookup_cache.clear()
        return OntologyResult()

    # Check cache
    if lookup_string in _lookup_cache:
        return _lookup_cache[lookup_string]

    # Parse prefix
    if ":" not in lookup_string:
        return OntologyResult()

    prefix, remainder = lookup_string.split(":", 1)

    # Load prefix map
    prefix_map = _load_prefix_map()

    # Case-insensitive prefix match
    provider_name = None
    for k, v in prefix_map.items():
        if k.lower() == prefix.lower():
            provider_name = v
            break

    if provider_name is None:
        return OntologyResult()

    # Get provider
    provider_cls = PROVIDER_REGISTRY.get(provider_name)
    if provider_cls is None:
        return OntologyResult()

    provider = provider_cls()
    try:
        result = provider.lookup_term(remainder, prefix)
    except Exception:
        result = OntologyResult()

    # Cache successes only. An empty result here is not a fact about the
    # ontology -- the providers answer a timeout or a 429 from a throttling
    # API with exactly the same empty OntologyResult they use for "term not
    # found" (see OLSProvider._search_ols, which ends `except Exception:
    # return OntologyResult()`). Caching it turns one transient blip into a
    # permanent wrong answer for that term for the life of the process, with
    # no way to retry short of clearCache().
    # MATLAB cannot have this bug: a failed lookup raises, so it never
    # reaches the cache write at ontology.m:330-336.
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


__all__ = ["OntologyResult", "lookup", "clearCache"]
