"""Whether the live ontology APIs are reachable, and whether that may be skipped.

One probe, shared. Both live suites used to carry their own copy: this module's
retried version in test_shared_cases.py, and a single-attempt one with a 5s
timeout in matlab_tests/test_ontology.py. The short one was the more fragile of
the two and guarded the tests nobody was watching, which is how a stale
assertion in test_lookup_invalid_term survived a full local run and first
failed on CI.

On the MATLAB side there is no equivalent of any of this. TestOntologyLookup.m
has no assumeTrue, no assumeFail, no skip of any kind -- only a class comment,
"Requires an active internet connection to query external APIs." Run it without
one and it fails. Skipping is a Python-side affordance for local development,
so `NDI_ONTOLOGY_REQUIRE_LIVE` is what restores MATLAB's actual guarantee
wherever it is set: unreachable APIs are then a failed run, not a quiet one.
"""

from __future__ import annotations

import os
import time
from functools import lru_cache

import requests

# OLS4 backs CL, OM, CHEBI, Uberon, PATO, EFO and STATO -- the largest group of
# providers behind one host, so its reachability is the best single proxy for
# "the live suites can run".
PROBE_URL = "https://www.ebi.ac.uk/ols4/api/ontologies"

# Attempt delays. Retried because this one request decides whether an entire
# live suite runs, and it is often made moments after that same API was asked
# for 46 lookups. A single probe once turned the parity job into "6 passed, 61
# skipped in 6.56s" -- green, having checked nothing.
PROBE_DELAYS_S = (0.0, 3.0, 9.0)


@lru_cache(maxsize=1)
def network_available() -> bool:
    """True if the live ontology APIs answer, retried, computed once per session.

    Probe with ``requests``, not a raw socket. ``socket.create_connection``
    ignores HTTPS_PROXY and so reports success in any environment that routes
    outbound HTTPS through a proxy: the connect to port 443 succeeds while every
    real lookup is refused. Probing through the stack the providers themselves
    use makes the guard tell the truth.

    Cached, so importing both live suites costs one probe rather than two.
    """
    for delay in PROBE_DELAYS_S:
        if delay:
            time.sleep(delay)
        try:
            if requests.get(PROBE_URL, timeout=10).status_code == 200:
                return True
        except requests.RequestException:
            continue
    return False


# Skipping live tests is a convenience for a developer with no network. In CI it
# is a lie: the job reports success having verified nothing. NDI-python solved
# the same problem for its symmetry suite with NDI_SYMMETRY_STRICT=1 -- "a
# symmetry check that could not run counts as a failure" (issue #90) -- so this
# is that gate, under the matching name.
REQUIRE_LIVE = os.environ.get("NDI_ONTOLOGY_REQUIRE_LIVE", "").strip().lower() in {
    "1",
    "true",
    "yes",
}


def reachability_failure_message(what: str) -> str:
    """The message for a REQUIRE_LIVE run whose APIs did not answer."""
    return (
        f"NDI_ONTOLOGY_REQUIRE_LIVE is set, but the ontology APIs are unreachable "
        f"after {len(PROBE_DELAYS_S)} attempts, so {what} would skip and this job "
        f"would pass without checking anything. Treat this as a failed run."
    )
