"""Run ndi-ontology-matlab's own test-case table against the Python port.

`ndi-ontology-matlab` drives `TestOntologyLookup.m` from
`tests/+ndi/+unittest/+ontology/ontology_lookup_tests.json`: 66 cases across 15
ontologies, each naming a lookup string and the exact `expected_id` and
`expected_name` it must produce. That file is language-neutral, so this module
reads the *same* file and asserts the same things about `ndi_ontology.lookup`.

This is the ontology namespace's symmetry test, and it is a better one than the
artifact-exchange machinery NDI-python uses elsewhere. That machinery exists
because those outputs -- sessions, documents, binary files -- cannot be written
down as literals, so MATLAB has to *produce* an artifact for Python to read
back. A lookup's output is two strings. When the expected output can be stated
in the fixture, both implementations can be checked against the fixture
directly, with no artifact to build, exchange, version, or keep in sync.

The file is not vendored. A second copy of it here would drift from MATLAB's
exactly as `ontology_list.json` did (17 registered prefixes against 22) before
the split, and drift in a *test* fixture is worse: it makes the suite agree
with a stale expectation and report parity that is not there. CI checks out
ndi-ontology-matlab and points NDI_ONTOLOGY_MATLAB_DIR at it.

To run locally::

    git clone https://github.com/Waltham-Data-Science/ndi-ontology-matlab.git
    NDI_ONTOLOGY_MATLAB_DIR=./ndi-ontology-matlab pytest tests/test_shared_cases.py

Without it the module skips rather than fails: an absent sibling checkout is a
missing tool, not a defect in this package.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
import requests

from ndi_ontology import lookup
from ndi_ontology.providers import PROVIDER_REGISTRY, NDICProvider

CASE_FILE_RELPATH = Path("tests/+ndi/+unittest/+ontology/ontology_lookup_tests.json")

# MATLAB's TestOntologyLookup pauses 1s between cases to stay friendly to OLS,
# NCBI and PubChem. Same courtesy here; without it 47 live lookups arrive as a
# burst and the far end starts answering with rate-limit errors, which the
# providers swallow into empty results and this suite reports as mismatches.
INTER_CASE_DELAY_S = 1.0


def _find_matlab_repo() -> Path | None:
    """Locate a ndi-ontology-matlab checkout, or None."""
    env = os.environ.get("NDI_ONTOLOGY_MATLAB_DIR")
    candidates = [Path(env)] if env else []
    here = Path(__file__).resolve().parent.parent
    candidates += [here.parent / "ndi-ontology-matlab", here / "ndi-ontology-matlab"]
    for root in candidates:
        if (root / CASE_FILE_RELPATH).is_file():
            return root
    return None


def _load_cases() -> list[dict]:
    root = _find_matlab_repo()
    if root is None:
        return []
    with open(root / CASE_FILE_RELPATH) as f:
        return json.load(f).get("ontology_lookup_tests", [])


CASES = _load_cases()

requires_case_file = pytest.mark.skipif(
    not CASES,
    reason=(
        "ndi-ontology-matlab checkout not found; set NDI_ONTOLOGY_MATLAB_DIR "
        "to one to run the shared case table"
    ),
)


def _can_reach_network() -> bool:
    """Probe through `requests`, for the reason given in tests/matlab_tests."""
    try:
        return (
            requests.get("https://www.ebi.ac.uk/ols4/api/ontologies", timeout=5).status_code == 200
        )
    except requests.RequestException:
        return False


NETWORK_AVAILABLE = _can_reach_network()


def _provider_for(lookup_string: str):
    """Resolve a case's prefix the way lookup() does, or None if unported.

    Deliberately routed through the same prefix map and registry the real
    dispatcher uses, rather than a hand-kept list of what is ported. A provider
    landing in PROVIDER_REGISTRY un-skips its cases with no edit here.
    """
    from ndi_ontology import _load_prefix_map

    if ":" not in lookup_string:
        return None
    prefix = lookup_string.split(":", 1)[0]
    prefix_map = _load_prefix_map()
    for k, v in prefix_map.items():
        if k.lower() == prefix.lower():
            return PROVIDER_REGISTRY.get(v)
    return None


# ---------------------------------------------------------------------------
# Known divergences from MATLAB
# ---------------------------------------------------------------------------
# Marked xfail(strict=True) rather than asserted away: strict means the day one
# starts passing, CI fails until the marker is removed, so a fixed divergence
# cannot quietly persist here as a lie about what is being checked.
#
# Do not add to this list to make a red case go away. A new mismatch is a port
# defect until it has been read against the MATLAB source and found to be a
# deliberate, recorded divergence.

# Currently empty. The one divergence this table found on its first run --
# Python returning 'NDIC:8' where MATLAB returns '8' -- was a port defect, so
# it was fixed rather than marked. NCIm and PubChem carried the same defect and
# were fixed with it: MATLAB returns a bare concept code (NCIm.m:138) and a bare
# CID (PubChem.m:148). Every other ontology in the table does keep its canonical
# prefix, so this is per-provider, not a blanket rule.
KNOWN_DIVERGENCES: dict[str, str] = {}


def _known_divergence(case: dict) -> str | None:
    """Return the reason this case is a known, recorded divergence, or None."""
    return KNOWN_DIVERGENCES.get(case.get("lookup_string", ""))


def _as_param(case: dict):
    reason = _known_divergence(case)
    marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
    return pytest.param(case, marks=marks)


def _case_id(case: dict) -> str:
    outcome = "ok" if case.get("should_succeed") else "fail"
    return f"{case.get('ontology', '?')}-{outcome}-{case.get('lookup_string', '?')}"


@requires_case_file
@pytest.mark.live
@pytest.mark.parametrize("case", [_as_param(c) for c in CASES], ids=[_case_id(c) for c in CASES])
def test_matlab_case_table(case: dict) -> None:
    """One case from ndi-ontology-matlab's ontology_lookup_tests.json."""
    lookup_string = case["lookup_string"]

    provider = _provider_for(lookup_string)
    if provider is None and ":" in lookup_string:
        pytest.skip(
            f"no provider for {lookup_string!r}: ontology not ported yet "
            f"(Waltham-Data-Science/NDI-python#98)"
        )

    # NDIC reads NDIC.txt from inside this package, so its cases are the ones
    # that hold with no network at all -- and, since that file is this
    # repository's to ship, the ones most worth checking here. Gate only the
    # cases that actually call out.
    # A case with no prefix at all (the table has one: "275") never reaches a
    # provider -- it is testing that an unprefixed string is rejected -- so it
    # needs neither a provider nor the network. Skipping it as "not ported"
    # would have been a lie about why it did not run.
    if provider is not None and provider is not NDICProvider:
        if not NETWORK_AVAILABLE:
            pytest.skip("no network access; this case queries a live ontology API")
        time.sleep(INTER_CASE_DELAY_S)

    if case["should_succeed"]:
        result = lookup(lookup_string)
        assert result.id == case["expected_id"], (
            f"id mismatch for {lookup_string!r}: "
            f"expected {case['expected_id']!r}, got {result.id!r}"
        )
        # MATLAB compares names with strcmpi, so case-insensitively.
        assert result.name.lower() == case["expected_name"].lower(), (
            f"name mismatch for {lookup_string!r}: "
            f"expected {case['expected_name']!r}, got {result.name!r}"
        )
    else:
        # MATLAB asserts an error here (verifyError(..., ?MException)). Python
        # returns an empty OntologyResult instead -- the known divergence that
        # is the first item of NDI-python#98. Accept either, so this suite
        # reports the mismatches it exists to catch rather than re-reporting
        # that one already-tracked difference on every failure case, and so it
        # keeps passing unchanged once #98 makes lookup() raise.
        try:
            result = lookup(lookup_string)
        except Exception:
            return
        assert not result, (
            f"expected no result for {lookup_string!r}, got "
            f"id={result.id!r} name={result.name!r}"
        )


@requires_case_file
def test_case_table_covers_every_ported_provider() -> None:
    """Every ported provider should have at least one shared case.

    A provider with no case in the table is one whose parity with MATLAB
    nothing checks. This does not run any lookup, so it holds offline.
    """
    covered = set()
    for case in CASES:
        provider = _provider_for(case["lookup_string"])
        if provider is not None:
            covered.add(provider)

    uncovered = sorted(name for name, cls in PROVIDER_REGISTRY.items() if cls not in covered)
    # WBStrain, SNOMED and EFO are ported here but absent from MATLAB's table.
    # Recorded rather than asserted away: the fix belongs upstream, as cases
    # added to ndi-ontology-matlab, not as a weaker assertion here.
    known_gaps = {"WBStrain", "SNOMED", "EFO"}
    unexpected = set(uncovered) - known_gaps
    assert not unexpected, (
        f"ported providers with no case in ndi-ontology-matlab's table: " f"{sorted(unexpected)}"
    )
