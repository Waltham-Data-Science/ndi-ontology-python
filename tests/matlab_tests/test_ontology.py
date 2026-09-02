"""
Port of MATLAB ndi.unittest.ontology.* tests.

MATLAB source files:
  +ontology/TestOntologyLookup.m -> TestOntologyLookup

Tests for:
- ndi_ontology.lookup() with mocked providers
- ndi_ontology.lookup() with live network (when available)
- ndi_ontology.OntologyResult
- ndi_ontology.clearCache()

The ontology tests REQUIRE network access for live tests.
Mocked tests run without network.
"""

import pytest
import requests

from ndi_ontology import (
    NDIOntologyLookupError,
    OntologyResult,
    clearCache,
    lookup,
)

# ---------------------------------------------------------------------------
# Network availability check
# ---------------------------------------------------------------------------


def _can_reach_network() -> bool:
    """Check whether the live ontology APIs are actually reachable.

    Probe with ``requests``, not a raw socket. A raw ``socket.create_connection``
    ignores HTTPS_PROXY and so reports success in any environment that routes
    outbound HTTPS through a proxy -- the connect to port 443 succeeds while
    every real lookup is refused by the proxy. The providers swallow that
    refusal and return an empty OntologyResult, which turns a missing network
    into a *failing* live test rather than a skipped one. Probing through the
    same stack the providers use makes the guard tell the truth.
    """
    try:
        resp = requests.get("https://www.ebi.ac.uk/ols4/api/ontologies", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


requires_network = pytest.mark.skipif(
    not _can_reach_network(),
    reason="No network access for ontology lookup",
)


# ===========================================================================
# TestOntologyResult
# ===========================================================================


class TestOntologyResult:
    """Test the OntologyResult data class."""

    def test_result_creation(self):
        """OntologyResult can be created with defaults."""
        result = OntologyResult()
        assert result.id == ""
        assert result.name == ""
        assert result.prefix == ""
        assert result.definition == ""
        assert result.synonyms == []

    def test_result_with_values(self):
        """OntologyResult stores provided values."""
        result = OntologyResult(
            id="NCBITaxon:10090",
            name="Mus musculus",
            prefix="NCBITaxon",
            definition="House mouse",
        )
        assert result.id == "NCBITaxon:10090"
        assert result.name == "Mus musculus"
        assert result.prefix == "NCBITaxon"

    def test_result_bool_empty(self):
        """Empty result is falsy."""
        result = OntologyResult()
        assert not result

    def test_result_bool_nonempty(self):
        """Result with id is truthy."""
        result = OntologyResult(id="CL:0000540")
        assert result

    def test_result_to_dict(self):
        """to_dict() returns a plain dict representation."""
        result = OntologyResult(id="CL:0000540", name="neuron")
        d = result.to_dict()
        assert isinstance(d, dict)
        assert d["id"] == "CL:0000540"
        assert d["name"] == "neuron"

    def test_result_repr(self):
        """repr includes id and name."""
        result = OntologyResult(id="CL:0000540", name="neuron")
        r = repr(result)
        assert "CL:0000540" in r
        assert "neuron" in r


# ===========================================================================
# TestOntologyLookup - Mocked
# ===========================================================================


class TestOntologyLookupMocked:
    """Port of ndi.unittest.ontology.TestOntologyLookup (mocked).

    Tests lookup() behavior without requiring network access.
    """

    def test_a_resolved_lookup_returns_an_ontology_result(self):
        """A lookup that resolves returns an OntologyResult.

        MATLAB equivalent: TestOntologyLookup.testLookupReturnType

        NDIC reads a file that ships inside the package, so this holds with no
        network -- and it is the only provider for which that is true.
        """
        result = lookup("NDIC:1")
        assert isinstance(result, OntologyResult)
        assert result.id and result.name

    def test_lookup_no_colon_raises(self):
        """MATLAB equivalent: TestOntologyLookup (edge case), which errors."""
        with pytest.raises(NDIOntologyLookupError):
            lookup("no_colon_here")

    def test_lookup_unknown_prefix_raises(self):
        """MATLAB equivalent: TestOntologyLookup (edge case), which errors."""
        with pytest.raises(NDIOntologyLookupError):
            lookup("UNKNOWNPREFIX:12345")

    def test_lookup_clear_cache(self):
        """lookup('clear') clears the internal cache.

        MATLAB equivalent: TestOntologyLookup.testClearCache
        """
        result = lookup("clear")
        assert isinstance(result, OntologyResult)
        assert not result  # clear returns empty result

    def test_clearCache_function(self):
        """clearCache() function clears the cache without error.

        MATLAB equivalent: TestOntologyLookup.testClearCache
        """
        clearCache()  # Should not raise


# ===========================================================================
# TestOntologyLookup - Live network
# ===========================================================================


class TestOntologyLookupLive:
    """Port of ndi.unittest.ontology.TestOntologyLookup (live network).

    These tests require network access and hit real ontology APIs.
    """

    @requires_network
    def test_lookup_ncbi_taxonomy(self):
        """Live: look up 'NCBITaxon:10090' (mouse).

        MATLAB equivalent: TestOntologyLookup.testNCBITaxon
        """
        # Clear cache first to ensure fresh lookup
        clearCache()

        result = lookup("NCBITaxon:10090")
        assert isinstance(result, OntologyResult)
        assert result  # should be truthy (found something)
        # The name should contain 'Mus musculus' or 'mouse'
        assert result.name, "Should have a non-empty name"

    @requires_network
    def test_lookup_cell_ontology(self):
        """Live: look up 'CL:0000540' (neuron).

        MATLAB equivalent: TestOntologyLookup.testCLLookup
        """
        clearCache()

        result = lookup("CL:0000540")
        assert isinstance(result, OntologyResult)
        assert result
        assert result.name, "Should have a non-empty name"

    @requires_network
    def test_lookup_invalid_term(self):
        """Live: a valid prefix with a non-existent id raises.

        MATLAB equivalent: TestOntologyLookup.testInvalidTerm, which asserts
        ``verifyError(funcToTest, ?MException)`` for every failure case. This
        test previously asserted the opposite -- that the lookup "should not
        raise" -- which was a port of Python's old empty-result divergence
        rather than of the MATLAB test it names.
        """
        clearCache()

        with pytest.raises(NDIOntologyLookupError) as excinfo:
            lookup("CL:9999999")

        assert "CL:9999999" in str(excinfo.value)

    @requires_network
    def test_lookup_caching(self):
        """Live: second lookup uses cached result.

        MATLAB equivalent: TestOntologyLookup.testCaching
        """
        clearCache()

        result1 = lookup("NCBITaxon:10090")
        result2 = lookup("NCBITaxon:10090")

        # Both should return the same data
        assert result1.id == result2.id
        assert result1.name == result2.name
