"""
ndi_ontology.name_utils - Name conversion utilities.

MATLAB equivalent: ndi-ontology-matlab
src/ndi/+ndi/+ontology/name2variableName.m

ndi-ontology-matlab carries its own copy of name2variableName, byte-identical
to NDI-matlab's +ndi/+fun/name2variableName.m, so that the ontology toolbox
stands alone. This module mirrors that: NDI-python keeps ndi.fun.name_utils
for +ndi/+fun, and this package keeps its own copy for +ndi/+ontology.

Provides utilities for converting human-readable names into
programming-safe variable names (PascalCase with underscores).
"""

from __future__ import annotations

import re


def name2variableName(name: str) -> str:
    """Convert a human-readable name to a PascalCase variable name.

    MATLAB equivalent: ndi.ontology.name2variableName

    Algorithm (matching MATLAB):
      1. Replace ``:`` and ``-`` with ``_``
      2. Replace other non-alphanumeric chars (except ``_``) with spaces
      3. Split into words, capitalize the first letter of each
      4. Join without spaces
      5. Prepend ``var_`` if result doesn't start with a letter
      6. Remove any remaining invalid characters

    Examples::

        >>> name2variableName("treatment: food restriction onset time")
        'Treatment_FoodRestrictionOnsetTime'
        >>> name2variableName("Optogenetic Tetanus Stimulation Target Location")
        'OptogeneticTetanusStimulationTargetLocation'
        >>> name2variableName("elevated plus maze: test duration")
        'ElevatedPlusMaze_TestDuration'

    Args:
        name: Human-readable name string.

    Returns:
        PascalCase variable-safe string.
    """
    if not name or name.isspace():
        return ""

    # Step 1: Replace ':' and '-' with '_'
    s = name.replace(":", "_").replace("-", "_")

    # Step 2: Replace non-alphanumeric (except '_') with spaces
    s = re.sub(r"[^a-zA-Z0-9_]", " ", s)

    # Step 3-4: Split, capitalize first letter of each word, join
    words = s.split()
    capitalized = []
    for w in words:
        if w:
            capitalized.append(w[0].upper() + w[1:])
    result = "".join(capitalized)

    # Step 5: Ensure starts with a letter
    if result and not result[0].isalpha():
        result = "var_" + result

    # Step 6: Final cleanup — keep only letters, digits, underscores
    result = re.sub(r"[^a-zA-Z0-9_]", "", result)

    return result


# Backward-compatible alias
name_to_variable_name = name2variableName
