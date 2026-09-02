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
from typing import Any

import pydantic

from .providers import PROVIDER_REGISTRY

# ---------------------------------------------------------------------------
# Lookup result type
# ---------------------------------------------------------------------------


class OntologyResult:
    """Result from an ontology lookup."""

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

    # ndi_cache (with eviction)
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
