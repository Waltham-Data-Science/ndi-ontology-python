"""Tests for ndi_ontology — ontology lookup system with providers."""

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# OntologyResult tests
# ---------------------------------------------------------------------------


class TestOntologyResult:
    """Tests for OntologyResult dataclass."""

    def test_default_empty(self):
        from ndi_ontology import OntologyResult

        r = OntologyResult()
        assert r.id == ""
        assert r.name == ""
        assert r.prefix == ""
        assert r.definition == ""
        assert r.synonyms == []
        assert r.short_name == ""

    def test_with_values(self):
        from ndi_ontology import OntologyResult

        r = OntologyResult(
            id="CL:0000540",
            name="neuron",
            prefix="CL",
            definition="A cell of the nervous system",
            synonyms=["nerve cell"],
            short_name="CL_0000540",
        )
        assert r.id == "CL:0000540"
        assert r.name == "neuron"
        assert r.prefix == "CL"
        assert r.definition == "A cell of the nervous system"
        assert r.synonyms == ["nerve cell"]
        assert r.short_name == "CL_0000540"

    def test_bool_false_when_empty(self):
        from ndi_ontology import OntologyResult

        r = OntologyResult()
        assert not r

    def test_bool_true_with_id(self):
        from ndi_ontology import OntologyResult

        r = OntologyResult(id="CL:1")
        assert r

    def test_bool_true_with_name(self):
        from ndi_ontology import OntologyResult

        r = OntologyResult(name="neuron")
        assert r

    def test_repr(self):
        from ndi_ontology import OntologyResult

        r = OntologyResult(id="CL:1", name="neuron")
        s = repr(r)
        assert "CL:1" in s
        assert "neuron" in s

    def test_to_dict(self):
        from ndi_ontology import OntologyResult

        r = OntologyResult(id="X:1", name="test", prefix="X")
        d = r.to_dict()
        assert d["id"] == "X:1"
        assert d["name"] == "test"
        assert d["prefix"] == "X"
        assert d["definition"] == ""
        assert d["synonyms"] == []
        assert d["short_name"] == ""

    def test_synonyms_default_not_shared(self):
        from ndi_ontology import OntologyResult

        r1 = OntologyResult()
        r2 = OntologyResult()
        r1.synonyms.append("x")
        assert r2.synonyms == []


# ---------------------------------------------------------------------------
# Lookup dispatch
# ---------------------------------------------------------------------------


class TestLookup:
    """Tests for the lookup() function."""

    def setup_method(self):
        from ndi_ontology import clearCache

        clearCache()

    def test_no_colon_returns_empty(self):
        from ndi_ontology import lookup

        r = lookup("neuron")
        assert not r

    def test_unknown_prefix_returns_empty(self):
        from ndi_ontology import lookup

        r = lookup("UNKNOWN:12345")
        assert not r

    def test_clear_cache_string(self):
        from ndi_ontology import lookup

        r = lookup("clear")
        assert not r

    def test_cache_hit(self):
        from ndi_ontology import OntologyResult, _lookup_cache, lookup

        # Pre-populate cache
        cached = OntologyResult(id="CL:999", name="cached")
        _lookup_cache["CL:999"] = cached
        result = lookup("CL:999")
        assert result.name == "cached"

    def test_cache_eviction(self):
        from ndi_ontology import _CACHE_MAX, OntologyResult, _lookup_cache, lookup

        _lookup_cache.clear()
        # Fill cache to max
        for i in range(_CACHE_MAX):
            _lookup_cache[f"TEST:{i}"] = OntologyResult(id=f"TEST:{i}")
        assert len(_lookup_cache) == _CACHE_MAX
        # Add one more via a mocked provider lookup
        with patch("ndi_ontology.providers.OLSProvider.lookup_term") as mock_lt:
            mock_lt.return_value = OntologyResult(id="CL:new", name="new")
            lookup("CL:new")
        assert len(_lookup_cache) <= _CACHE_MAX

    def test_clearCache_function(self):
        from ndi_ontology import OntologyResult, _lookup_cache, clearCache

        _lookup_cache["test:1"] = OntologyResult(id="test:1")
        assert len(_lookup_cache) > 0
        clearCache()
        assert len(_lookup_cache) == 0

    def test_case_insensitive_prefix(self):
        """Prefix matching should be case-insensitive."""
        from ndi_ontology import OntologyResult, lookup

        with patch("ndi_ontology.providers.OLSProvider.lookup_term") as mock_lt:
            mock_lt.return_value = OntologyResult(id="CL:1", name="test")
            lookup("cl:1")  # lowercase
            assert mock_lt.called

    def test_provider_exception_returns_empty(self):
        """If provider raises, lookup returns empty result."""
        from ndi_ontology import lookup

        with patch("ndi_ontology.providers.OLSProvider.lookup_term") as mock_lt:
            mock_lt.side_effect = RuntimeError("API down")
            result = lookup("CL:0000540")
            assert not result


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    """Tests for the provider registry."""

    def test_registry_populated(self):
        from ndi_ontology.providers import PROVIDER_REGISTRY

        assert "CL" in PROVIDER_REGISTRY
        assert "OM" in PROVIDER_REGISTRY
        assert "NDIC" in PROVIDER_REGISTRY
        assert "NCIm" in PROVIDER_REGISTRY
        assert "CHEBI" in PROVIDER_REGISTRY
        assert "NCBITaxon" in PROVIDER_REGISTRY
        assert "WBStrain" in PROVIDER_REGISTRY
        assert "SNOMED" in PROVIDER_REGISTRY
        assert "RRID" in PROVIDER_REGISTRY
        assert "EFO" in PROVIDER_REGISTRY
        assert "PATO" in PROVIDER_REGISTRY
        assert "PubChem" in PROVIDER_REGISTRY
        assert "EMPTY" in PROVIDER_REGISTRY

    def test_registry_count(self):
        from ndi_ontology.providers import PROVIDER_REGISTRY

        assert len(PROVIDER_REGISTRY) >= 13


# ---------------------------------------------------------------------------
# OLSProvider tests (mocked HTTP)
# ---------------------------------------------------------------------------


class TestOLSProvider:
    """Tests for OLS-based providers with mocked HTTP calls."""

    def test_cl_numeric_lookup(self):
        from ndi_ontology.providers import CLProvider

        provider = CLProvider()
        mock_response = {
            "response": {
                "docs": [
                    {
                        "obo_id": "CL:0000540",
                        "label": "neuron",
                        "short_form": "CL_0000540",
                        "description": ["A cell that receives and transmits nerve impulses"],
                        "synonym": ["nerve cell"],
                    }
                ]
            }
        }
        with patch.object(provider, "_http_get_json", return_value=mock_response):
            result = provider.lookup_term("540")
        assert result.id == "CL:0000540"
        assert result.name == "neuron"
        assert result.prefix == "CL"

    def test_cl_label_lookup(self):
        from ndi_ontology.providers import CLProvider

        mock_response = {
            "response": {
                "docs": [
                    {
                        "obo_id": "CL:0000540",
                        "label": "neuron",
                        "short_form": "CL_0000540",
                        "description": ["A cell"],
                        "synonym": [],
                    }
                ]
            }
        }
        provider = CLProvider()
        with patch.object(provider, "_http_get_json", return_value=mock_response):
            result = provider.lookup_term("neuron")
        assert result.name == "neuron"

    def test_cl_label_no_exact_match(self):
        from ndi_ontology.providers import CLProvider

        mock_response = {
            "response": {
                "docs": [
                    {
                        "obo_id": "CL:0000001",
                        "label": "motor neuron",
                        "short_form": "CL_0000001",
                        "description": [],
                        "synonym": [],
                    }
                ]
            }
        }
        provider = CLProvider()
        with patch.object(provider, "_http_get_json", return_value=mock_response):
            result = provider.lookup_term("neuron")
        # Should not match because 'motor neuron' != 'neuron'
        assert not result

    def test_ols_empty_docs(self):
        from ndi_ontology.providers import CLProvider

        mock_response = {"response": {"docs": []}}
        provider = CLProvider()
        with patch.object(provider, "_http_get_json", return_value=mock_response):
            result = provider.lookup_term("nonexistent")
        assert not result

    def test_ols_api_error(self):
        from ndi_ontology.providers import CLProvider

        provider = CLProvider()
        with patch.object(provider, "_http_get_json", side_effect=Exception("API error")):
            result = provider.lookup_term("540")
        assert not result

    def test_doc_to_result_fallback_short_form(self):
        """When obo_id is empty, fall back to short_form."""
        from ndi_ontology.providers import CLProvider

        provider = CLProvider()
        doc = {
            "obo_id": "",
            "short_form": "CL_9999999",
            "label": "test cell",
            "description": ["A test"],
            "synonym": [],
        }
        result = provider._doc_to_result(doc, "CL")
        assert result.id == "CL:9999999"

    def test_numeric_id_passed_through_verbatim(self):
        """Numeric IDs go to OLS unpadded, as MATLAB sends them.

        This test previously asserted the opposite -- that ``lookup_term("1")``
        queries ``CL:0000001`` -- which encoded a defect. MATLAB's
        preprocessLookupInput builds ``[ontology_prefix ':' numeric_id]`` with
        no padding, and obo_id is an exact-match field, so padding to 7 digits
        silently broke every ontology whose ids are not 7 digits: CHEBI:15377
        was sent as CHEBI:0015377 and matched nothing. It was invisible because
        the ontologies with 7-digit ids (CL, PATO, UBERON, EMPTY) padded to
        themselves, and because lookup by name was unaffected.
        """
        from ndi_ontology.providers import CLProvider

        provider = CLProvider()
        mock_response = {
            "response": {
                "docs": [
                    {
                        "obo_id": "CL:0000001",
                        "label": "cell",
                        "short_form": "CL_0000001",
                        "description": [],
                        "synonym": [],
                    }
                ]
            }
        }
        with patch.object(provider, "_http_get_json", return_value=mock_response) as mock_get:
            provider.lookup_term("1")
            args, kwargs = mock_get.call_args
            assert kwargs["params"]["q"] == "CL:1"

        # The case that padding broke: a CHEBI id is not 7 digits.
        from ndi_ontology.providers import CHEBIProvider

        chebi = CHEBIProvider()
        with patch.object(chebi, "_http_get_json", return_value=mock_response) as mock_get:
            chebi.lookup_term("15377", "CHEBI")
            args, kwargs = mock_get.call_args
            assert kwargs["params"]["q"] == "CHEBI:15377"


# ---------------------------------------------------------------------------
# OMProvider tests
# ---------------------------------------------------------------------------


class TestOMProvider:
    """Tests for OM (Units of Measure) provider."""

    def test_camel_case_conversion(self):
        from ndi_ontology.providers import OMProvider

        provider = OMProvider()
        mock_response = {
            "response": {
                "docs": [
                    {
                        "obo_id": "OM:0001",
                        "label": "milli metre",
                        "short_form": "OM_0001",
                        "description": [],
                        "synonym": [],
                    }
                ]
            }
        }
        with patch.object(provider, "_http_get_json", return_value=mock_response) as mock_get:
            provider.lookup_term("milliMetre")
            # Should convert CamelCase to 'milli metre'
            args, kwargs = mock_get.call_args
            assert kwargs["params"]["q"] == "milli metre"


# ---------------------------------------------------------------------------
# NDICProvider tests (local TSV)
# ---------------------------------------------------------------------------


class TestNDICProvider:
    """Tests for NDI Controlled Vocabulary provider."""

    def test_lookup_by_id(self):
        from ndi_ontology.providers import NDICProvider

        provider = NDICProvider()
        # Reset cached data
        NDICProvider._data = None
        fake_data = [
            {"id": "1", "name": "visual cortex", "description": "Area V1"},
            {"id": "2", "name": "hippocampus", "description": "Memory region"},
        ]
        NDICProvider._data = fake_data
        result = provider.lookup_term("1")
        assert result.id == "1"
        assert result.name == "visual cortex"
        assert result.definition == "Area V1"
        NDICProvider._data = None

    def test_lookup_by_name(self):
        from ndi_ontology.providers import NDICProvider

        NDICProvider._data = [
            {"id": "1", "name": "visual cortex", "description": "Area V1"},
        ]
        provider = NDICProvider()
        result = provider.lookup_term("visual cortex")
        assert result.id == "1"
        NDICProvider._data = None

    def test_lookup_case_insensitive_name(self):
        from ndi_ontology.providers import NDICProvider

        NDICProvider._data = [
            {"id": "1", "name": "Visual Cortex", "description": "V1"},
        ]
        provider = NDICProvider()
        result = provider.lookup_term("visual cortex")
        assert result.id == "1"
        NDICProvider._data = None

    def test_lookup_not_found(self):
        from ndi_ontology.providers import NDICProvider

        NDICProvider._data = [
            {"id": "1", "name": "visual cortex", "description": "V1"},
        ]
        provider = NDICProvider()
        result = provider.lookup_term("nonexistent")
        assert not result
        NDICProvider._data = None


# ---------------------------------------------------------------------------
# NCImProvider tests
# ---------------------------------------------------------------------------


class TestNCImProvider:
    """Tests for NCI Metathesaurus provider."""

    def test_cui_pattern_match(self):
        from ndi_ontology.providers import NCImProvider

        provider = NCImProvider()
        assert provider._CUI_PATTERN.match("C0027947")
        assert not provider._CUI_PATTERN.match("12345")
        assert not provider._CUI_PATTERN.match("C123")

    def test_cui_lookup(self):
        from ndi_ontology.providers import NCImProvider

        provider = NCImProvider()
        mock_data = {
            "code": "C0027947",
            "name": "ndi_neuron",
            "definitions": [{"definition": "A nerve cell"}],
            "synonyms": [{"name": "Nerve Cell"}, {"name": "Neural Cell"}],
        }
        with patch.object(provider, "_http_get_json", return_value=mock_data):
            result = provider.lookup_term("C0027947")
        assert result.id == "C0027947"
        assert result.name == "ndi_neuron"
        assert result.definition == "A nerve cell"
        assert "Nerve Cell" in result.synonyms

    def test_name_search(self):
        from ndi_ontology.providers import NCImProvider

        provider = NCImProvider()
        search_data = {
            "concepts": [{"code": "C0027947"}],
        }
        detail_data = {
            "code": "C0027947",
            "name": "ndi_neuron",
            "definitions": [],
            "synonyms": [],
        }
        with patch.object(provider, "_http_get_json", side_effect=[search_data, detail_data]):
            result = provider.lookup_term("ndi_neuron")
        assert result.id == "C0027947"

    def test_api_error(self):
        from ndi_ontology.providers import NCImProvider

        provider = NCImProvider()
        with patch.object(provider, "_http_get_json", side_effect=Exception("error")):
            result = provider.lookup_term("C0027947")
        assert not result


# ---------------------------------------------------------------------------
# NCBITaxonProvider tests
# ---------------------------------------------------------------------------


class TestNCBITaxonProvider:
    """Tests for NCBI Taxonomy provider."""

    def test_taxid_lookup(self):
        from ndi_ontology.providers import NCBITaxonProvider

        provider = NCBITaxonProvider()
        xml = """<TaxaSet>
            <Taxon>
                <ScientificName>Mus musculus</ScientificName>
                <OtherNames>
                    <CommonName>house mouse</CommonName>
                </OtherNames>
            </Taxon>
        </TaxaSet>"""
        mock_resp = MagicMock()
        mock_resp.text = xml
        with patch("requests.get", return_value=mock_resp):
            result = provider.lookup_term("10090")
        assert result.id == "NCBITaxon:10090"
        assert result.name == "Mus musculus"
        assert "house mouse" in result.synonyms

    def test_name_search(self):
        from ndi_ontology.providers import NCBITaxonProvider

        provider = NCBITaxonProvider()
        search_xml = """<eSearchResult><IdList><Id>10090</Id></IdList></eSearchResult>"""
        fetch_xml = """<TaxaSet>
            <Taxon>
                <ScientificName>Mus musculus</ScientificName>
                <OtherNames></OtherNames>
            </Taxon>
        </TaxaSet>"""
        mock_search = MagicMock()
        mock_search.text = search_xml
        mock_fetch = MagicMock()
        mock_fetch.text = fetch_xml
        with patch("requests.get", side_effect=[mock_search, mock_fetch]):
            result = provider.lookup_term("Mus musculus")
        assert result.id == "NCBITaxon:10090"

    def test_api_error(self):
        from ndi_ontology.providers import NCBITaxonProvider

        provider = NCBITaxonProvider()
        with patch("requests.get", side_effect=Exception("timeout")):
            result = provider.lookup_term("10090")
        assert not result


# ---------------------------------------------------------------------------
# PubChemProvider tests
# ---------------------------------------------------------------------------


class TestPubChemProvider:
    """Tests for PubChem provider."""

    def test_cid_numeric_lookup(self):
        from ndi_ontology.providers import PubChemProvider

        provider = PubChemProvider()
        title_data = {"PropertyTable": {"Properties": [{"Title": "Aspirin"}]}}
        desc_data = {"InformationList": {"Information": [{"Description": "An NSAID"}]}}
        syn_data = {"InformationList": {"Information": [{"Synonym": ["acetylsalicylic acid"]}]}}
        with patch.object(
            provider, "_http_get_json", side_effect=[title_data, desc_data, syn_data]
        ):
            result = provider.lookup_term("2244")
        assert result.id == "2244"
        assert result.name == "Aspirin"

    def test_cid_prefix_lookup(self):
        from ndi_ontology.providers import PubChemProvider

        provider = PubChemProvider()
        title_data = {"PropertyTable": {"Properties": [{"Title": "Water"}]}}
        with patch.object(
            provider, "_http_get_json", side_effect=[title_data, Exception, Exception]
        ):
            result = provider.lookup_term("CID:962")
        assert result.id == "962"

    def test_name_search(self):
        from ndi_ontology.providers import PubChemProvider

        provider = PubChemProvider()
        search_data = {"IdentifierList": {"CID": [2244]}}
        title_data = {"PropertyTable": {"Properties": [{"Title": "Aspirin"}]}}
        with patch.object(
            provider, "_http_get_json", side_effect=[search_data, title_data, Exception, Exception]
        ):
            result = provider.lookup_term("Aspirin")
        assert result.id == "2244"

    def test_api_error(self):
        from ndi_ontology.providers import PubChemProvider

        provider = PubChemProvider()
        with patch.object(provider, "_http_get_json", side_effect=Exception("error")):
            result = provider.lookup_term("2244")
        assert not result


# ---------------------------------------------------------------------------
# RRIDProvider tests
# ---------------------------------------------------------------------------


class TestRRIDProvider:
    """Tests for RRID provider."""

    def test_lookup(self):
        from ndi_ontology.providers import RRIDProvider

        provider = RRIDProvider()
        mock_data = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "item": {
                                "name": "Mouse anti-NeuN",
                                "description": "A neuronal marker antibody",
                                "synonyms": ["anti-NeuN"],
                            }
                        }
                    }
                ]
            }
        }
        with patch.object(provider, "_http_get_json", return_value=mock_data):
            result = provider.lookup_term("AB_123456")
        assert result.id == "RRID:AB_123456"
        assert result.name == "Mouse anti-NeuN"

    def test_not_found(self):
        from ndi_ontology.providers import RRIDProvider

        provider = RRIDProvider()
        mock_data = {"hits": {"hits": []}}
        with patch.object(provider, "_http_get_json", return_value=mock_data):
            result = provider.lookup_term("AB_000000")
        assert not result


# ---------------------------------------------------------------------------
# WBStrainProvider tests
# ---------------------------------------------------------------------------


class TestWBStrainProvider:
    """Tests for WormBase strain provider."""

    def test_numeric_id_lookup(self):
        from ndi_ontology.providers import WBStrainProvider

        provider = WBStrainProvider()
        mock_data = {
            "fields": {
                "name": {"data": {"label": "N2"}},
                "genotype": {"data": "wild type"},
            }
        }
        with patch.object(provider, "_http_get_json", return_value=mock_data):
            result = provider.lookup_term("00000001")
        assert result.id == "WBStrain:00000001"
        assert result.name == "N2"
        assert result.definition == "wild type"

    def test_api_error(self):
        from ndi_ontology.providers import WBStrainProvider

        provider = WBStrainProvider()
        with patch.object(provider, "_http_get_json", side_effect=Exception("error")):
            result = provider.lookup_term("N2")
        assert not result


# ---------------------------------------------------------------------------
# EMPTYProvider tests
# ---------------------------------------------------------------------------


class TestEMPTYProvider:
    """Tests for EMPTY (stub) provider."""

    def test_returns_empty_result(self):
        from ndi_ontology.providers import EMPTYProvider

        provider = EMPTYProvider()
        result = provider.lookup_term("anything")
        assert result.prefix == "EMPTY"
        assert not result.id


# ---------------------------------------------------------------------------
# Base provider
# ---------------------------------------------------------------------------


class TestOntologyProvider:
    """Tests for base OntologyProvider."""

    def test_default_lookup_returns_empty(self):
        from ndi_ontology.providers import OntologyProvider

        provider = OntologyProvider()
        result = provider.lookup_term("anything")
        assert not result

    def test_http_get_json(self):
        from ndi_ontology.providers import OntologyProvider

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"key": "value"}
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = OntologyProvider._http_get_json("https://example.com/api")
        assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


class TestOntologyImports:
    """Verify module structure."""

    def test_import_ontology(self):
        import ndi_ontology

        assert hasattr(ndi_ontology, "lookup")
        assert hasattr(ndi_ontology, "OntologyResult")
        assert hasattr(ndi_ontology, "clearCache")

    def test_import_providers(self):
        from ndi_ontology.providers import (
            PROVIDER_REGISTRY,
            CLProvider,
            NCImProvider,
            NDICProvider,
            OLSProvider,
            OMProvider,
            OntologyProvider,
        )

        assert all(
            [
                PROVIDER_REGISTRY,
                OntologyProvider,
                OLSProvider,
                CLProvider,
                OMProvider,
                NDICProvider,
                NCImProvider,
            ]
        )

    def test_all_exports(self):
        from ndi_ontology import __all__

        assert "OntologyResult" in __all__
        assert "lookup" in __all__
        assert "clearCache" in __all__


# ---------------------------------------------------------------------------
# Packaged data files / standalone-ness
# ---------------------------------------------------------------------------


class TestPackagedDataFiles:
    """The toolbox must resolve its own data files without NDI-python.

    MATLAB equivalent: ndi.ontologyToolboxDir, which locates ndi_common
    relative to the toolbox rather than relative to NDI-matlab.
    """

    def test_ontology_list_ships_with_package(self):
        from ndi_ontology.paths import ONTOLOGY_LIST_FILE

        assert ONTOLOGY_LIST_FILE.exists(), f"missing packaged data file: {ONTOLOGY_LIST_FILE}"

    def test_ndic_ships_with_package(self):
        from ndi_ontology.paths import NDIC_FILE

        assert NDIC_FILE.exists(), f"missing packaged data file: {NDIC_FILE}"

    def test_toolbox_dir_contains_common_folder(self):
        from ndi_ontology.paths import COMMON_FOLDER, ontologyToolboxDir

        assert COMMON_FOLDER.is_dir()
        assert COMMON_FOLDER.parent == ontologyToolboxDir()

    def test_no_import_of_ndi_python(self):
        """This package must not depend on NDI-python: that would be a cycle.

        NDI-python depends on ndi_ontology, so any ``import ndi`` here would
        close a loop. The check is textual because importing the modules
        cannot prove the absence of a lazy import inside a function body.
        """
        import re
        from pathlib import Path

        import ndi_ontology

        pkg_dir = Path(ndi_ontology.__file__).parent
        offenders = []
        pattern = re.compile(r"^\s*(?:from\s+ndi(?:\.|\s)|import\s+ndi(?:\.|\s|$))")
        for py in sorted(pkg_dir.rglob("*.py")):
            for lineno, line in enumerate(py.read_text().splitlines(), start=1):
                if pattern.match(line) and "ndi_ontology" not in line:
                    offenders.append(f"{py.name}:{lineno}: {line.strip()}")
        assert not offenders, "ndi_ontology must not import NDI-python:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# Positional (MATLAB-shaped) access
# ---------------------------------------------------------------------------


class TestOntologyResultIteration:
    """OntologyResult unpacks like MATLAB's six output arguments.

    MATLAB's ndi.ontology.lookup declares
    `[id, name, prefix, definition, synonyms, shortName]` (ontology.m:125), and
    the porting guide's section 5 requires multiple MATLAB outputs to become a
    Python tuple in declaration order. These tests pin that order to the MATLAB
    declaration, not to whatever the class currently happens to do.
    """

    #: Transcribed from ndi-ontology-matlab src/ndi/+ndi/ontology.m:125,
    #: mapped to the Python field names. shortName -> short_name is the only
    #: rename, and it predates this change.
    MATLAB_OUTPUT_ORDER = ("id", "name", "prefix", "definition", "synonyms", "short_name")

    def _sample(self):
        from ndi_ontology import OntologyResult

        return OntologyResult(
            id="CL:0000540",
            name="neuron",
            prefix="CL",
            definition="A cell of the nervous system",
            synonyms=["nerve cell"],
            short_name="CL_0000540",
        )

    def test_iteration_order_matches_matlab(self):
        """The declared field order IS MATLAB's output order."""
        from ndi_ontology import OntologyResult

        assert OntologyResult.__slots__ == self.MATLAB_OUTPUT_ORDER

    def test_unpacks_into_all_six(self):
        id_, name, prefix, definition, synonyms, short_name = self._sample()
        assert id_ == "CL:0000540"
        assert name == "neuron"
        assert prefix == "CL"
        assert definition == "A cell of the nervous system"
        assert synonyms == ["nerve cell"]
        assert short_name == "CL_0000540"

    def test_matlab_shaped_first_two(self):
        """`id, name, *_` is how a caller asks for MATLAB's first two outputs.

        This is the idiom the three NDI-python call sites use. MATLAB lets a
        caller request fewer outputs than declared; Python unpacking does not,
        so the remainder is spelled out.
        """
        ont_id, name, *_ = self._sample()
        assert (ont_id, name) == ("CL:0000540", "neuron")

    def test_exact_count_still_enforced(self):
        """Two names for six values raises, as Python requires.

        Recorded so the limit is explicit: __iter__ does not make
        `id, name = lookup(...)` work, it makes `id, name, *_` work.
        """
        import pytest

        with pytest.raises(ValueError):
            _a, _b = self._sample()

    def test_tuple_and_len(self):
        from ndi_ontology import OntologyResult

        assert len(self._sample()) == len(OntologyResult.__slots__) == 6
        assert tuple(self._sample())[:3] == ("CL:0000540", "neuron", "CL")

    def test_iteration_agrees_with_attributes_and_to_dict(self):
        """One field order, three ways of reading it -- they must not diverge."""
        from ndi_ontology import OntologyResult

        r = self._sample()
        by_attr = [getattr(r, f) for f in OntologyResult.__slots__]
        assert list(r) == by_attr
        assert list(r.to_dict().values()) == by_attr

    def test_an_empty_result_still_unpacks(self):
        """A failed lookup unpacks too, rather than raising a second error."""
        from ndi_ontology import OntologyResult

        ont_id, name, *_ = OntologyResult()
        assert (ont_id, name) == ("", "")


# ---------------------------------------------------------------------------
# Providers ported from ndi-ontology-matlab (NDI-python#98)
# ---------------------------------------------------------------------------


class TestOLSPortedProviders:
    """Uberon, NCIT and STATO are OLSProvider subclasses, as in MATLAB.

    Each MATLAB class sets only ontology_prefix and ontology_name_ols and
    defers to the shared preprocessLookupInput / searchOLSAndPerformIRILookup
    helpers, so the only thing worth asserting here is that the two parameters
    are right and reach the query.
    """

    OLS_PARAMS = {
        "Uberon": ("uberon", "UBERON"),
        "NCIT": ("ncit", "NCIT"),
        "STATO": ("stato", "STATO"),
    }

    def test_ols_parameters_match_matlab(self):
        from ndi_ontology.providers import NCITProvider, STATOProvider, UberonProvider

        for cls, key in (
            (UberonProvider, "Uberon"),
            (NCITProvider, "NCIT"),
            (STATOProvider, "STATO"),
        ):
            ontology, prefix = self.OLS_PARAMS[key]
            assert cls.ols_ontology == ontology
            assert cls.ols_prefix == prefix

    def test_lookup_by_id_queries_the_right_ontology(self):
        from ndi_ontology.providers import UberonProvider

        provider = UberonProvider()
        response = {
            "response": {
                "docs": [
                    {
                        "obo_id": "UBERON:0000948",
                        "label": "heart",
                        "short_form": "UBERON_0000948",
                        "description": ["a hollow muscular organ"],
                        "synonym": ["chambered heart"],
                    }
                ]
            }
        }
        with patch.object(provider, "_http_get_json", return_value=response) as mock_get:
            result = provider.lookup_term("0000948", "UBERON")

        _args, kwargs = mock_get.call_args
        assert kwargs["params"]["ontology"] == "uberon"
        assert kwargs["params"]["q"] == "UBERON:0000948"
        assert result.id == "UBERON:0000948"
        assert result.name == "heart"

    def test_lookup_by_name(self):
        from ndi_ontology.providers import STATOProvider

        provider = STATOProvider()
        response = {
            "response": {
                "docs": [
                    {
                        "obo_id": "STATO:0000700",
                        "label": "p-value",
                        "short_form": "STATO_0000700",
                        "description": [],
                        "synonym": [],
                    }
                ]
            }
        }
        with patch.object(provider, "_http_get_json", return_value=response) as mock_get:
            result = provider.lookup_term("p-value", "STATO")

        _args, kwargs = mock_get.call_args
        assert kwargs["params"]["queryFields"] == "label"
        assert result.id == "STATO:0000700"

    def test_not_found_is_empty(self):
        from ndi_ontology.providers import NCITProvider

        provider = NCITProvider()
        with patch.object(provider, "_http_get_json", return_value={"response": {"docs": []}}):
            assert not provider.lookup_term("NoSuchTerm", "NCIT")


EDAM_OWL = """
<owl:Class rdf:about="http://edamontology.org/format_1929">
  <rdfs:label>FASTA</rdfs:label>
  <obo:IAO_0000115>FASTA format.</obo:IAO_0000115>
</owl:Class>
<owl:Class rdf:about="http://edamontology.org/data_0006">
  <rdfs:label>Data</rdfs:label>
</owl:Class>
<owl:Class rdf:about="http://edamontology.org/notanid">
  <rdfs:label>Skipped</rdfs:label>
</owl:Class>
"""

IAO_OWL = """
<owl:Class rdf:about="http://purl.obolibrary.org/obo/IAO_0000310">
  <rdfs:label>document</rdfs:label>
  <obo:IAO_0000115>A collection of information content entities.</obo:IAO_0000115>
  <oboInOwl:hasExactSynonym>doc</oboInOwl:hasExactSynonym>
</owl:Class>
<rdf:Description rdf:about="http://purl.obolibrary.org/obo/IAO_0000030">
  <rdfs:label>information content entity</rdfs:label>
</rdf:Description>
<rdf:Description rdf:about="http://purl.obolibrary.org/obo/IAO_0000099">
</rdf:Description>
"""


class TestEDAMProvider:
    """MATLAB equivalent: +ndi/+ontology/EDAM.m."""

    def _provider(self):
        from ndi_ontology.providers import EDAMProvider

        EDAMProvider._cache = None
        return EDAMProvider()

    def test_lookup_by_numeric_id_drops_the_sub_namespace(self):
        """EDAM IRIs are format_1929 / data_0006; the id returned is EDAM:1929."""
        from ndi_ontology.providers import EDAMProvider

        provider = self._provider()
        with patch.object(EDAMProvider, "_fetch_owl", return_value=EDAM_OWL):
            result = provider.lookup_term("1929", "EDAM")

        assert result.id == "EDAM:1929"
        assert result.name == "FASTA"
        assert result.definition == "FASTA format."

    def test_lookup_by_name_is_case_insensitive(self):
        from ndi_ontology.providers import EDAMProvider

        provider = self._provider()
        with patch.object(EDAMProvider, "_fetch_owl", return_value=EDAM_OWL):
            assert provider.lookup_term("fasta", "EDAM").id == "EDAM:1929"

    def test_malformed_local_ids_are_skipped(self):
        """`notanid` has no `<word>_<digits>` shape, so MATLAB skips it."""
        from ndi_ontology.providers import EDAMProvider

        provider = self._provider()
        with patch.object(EDAMProvider, "_fetch_owl", return_value=EDAM_OWL):
            assert not provider.lookup_term("Skipped", "EDAM")

    def test_not_found_is_empty(self):
        from ndi_ontology.providers import EDAMProvider

        provider = self._provider()
        with patch.object(EDAMProvider, "_fetch_owl", return_value=EDAM_OWL):
            assert not provider.lookup_term("9999999", "EDAM")


class TestIAOProvider:
    """MATLAB equivalent: +ndi/+ontology/IAO.m."""

    def _provider(self):
        from ndi_ontology.providers import IAOProvider

        IAOProvider._cache = None
        return IAOProvider()

    def test_lookup_by_numeric_id(self):
        from ndi_ontology.providers import IAOProvider

        provider = self._provider()
        with patch.object(IAOProvider, "_fetch_owl", return_value=IAO_OWL):
            result = provider.lookup_term("0000310", "IAO")

        assert result.id == "IAO:0000310"
        assert result.name == "document"
        assert result.synonyms == ["doc"]

    def test_rdf_description_blocks_count_when_labelled(self):
        """IAO terms appear as owl:Class AND rdf:Description; MATLAB reads both."""
        from ndi_ontology.providers import IAOProvider

        provider = self._provider()
        with patch.object(IAOProvider, "_fetch_owl", return_value=IAO_OWL):
            assert provider.lookup_term("information content entity", "IAO").id == "IAO:0000030"

    def test_unlabelled_terms_are_skipped(self):
        """IAO_0000099 carries no rdfs:label, so it is not indexed."""
        from ndi_ontology.providers import IAOProvider

        provider = self._provider()
        with patch.object(IAOProvider, "_fetch_owl", return_value=IAO_OWL):
            assert not provider.lookup_term("0000099", "IAO")

    def test_url_order_matches_matlab(self):
        """The obolibrary PURL is tried first, the GitHub raw copy second."""
        from ndi_ontology.providers import IAOProvider

        assert IAOProvider.owl_urls[0].startswith("http://purl.obolibrary.org/")
        assert "raw.githubusercontent.com" in IAOProvider.owl_urls[1]


class TestSchemaOrgProvider:
    """MATLAB equivalent: +ndi/+ontology/SchemaOrg.m."""

    def _response(self, body: str):
        mock = MagicMock()
        mock.text = body
        mock.json.return_value = __import__("json").loads(body)
        mock.raise_for_status.return_value = None
        return mock

    PERSON = (
        '{"@graph": [{"@id": "schema:Person", "rdfs:label": "Person",'
        ' "rdfs:comment": "A person (alive, dead, undead, or fictional)."}]}'
    )

    def test_lookup_reads_the_matching_graph_entry(self):
        from ndi_ontology.providers import SchemaOrgProvider

        provider = SchemaOrgProvider()
        with patch("requests.get", return_value=self._response(self.PERSON)):
            result = provider.lookup_term("Person", "schema")

        assert result.id == "schema:Person"
        assert result.name == "Person"
        assert result.definition.startswith("A person")

    def test_full_iri_form_of_the_id_also_matches(self):
        """The document may spell @id compact or as the full IRI; both count."""
        from ndi_ontology.providers import SchemaOrgProvider

        body = '{"@graph": [{"@id": "https://schema.org/Dataset", "rdfs:label": "Dataset"}]}'
        provider = SchemaOrgProvider()
        with patch("requests.get", return_value=self._response(body)):
            assert provider.lookup_term("Dataset", "schema").id == "schema:Dataset"

    def test_a_page_describing_something_else_is_a_miss(self):
        from ndi_ontology.providers import SchemaOrgProvider

        body = '{"@graph": [{"@id": "schema:Thing", "rdfs:label": "Thing"}]}'
        provider = SchemaOrgProvider()
        with patch("requests.get", return_value=self._response(body)):
            assert not provider.lookup_term("NoSuchSchemaOrgTerm", "schema")

    def test_name_falls_back_to_the_term(self):
        """MATLAB seeds name with the term and only overwrites it from a label."""
        from ndi_ontology.providers import SchemaOrgProvider

        body = '{"@graph": [{"@id": "schema:Organization"}]}'
        provider = SchemaOrgProvider()
        with patch("requests.get", return_value=self._response(body)):
            result = provider.lookup_term("Organization", "schema")

        assert (result.id, result.name) == ("schema:Organization", "Organization")


class TestPrefixRegistryIsSingleSourced:
    """ontology_list.json is the only place a prefix is registered."""

    def test_every_registered_prefix_has_a_provider(self):
        """The defect this closes: Uberon and NCIT were registered with none.

        A prefix that resolves to a missing provider produces an empty result,
        which is indistinguishable from "term not found".
        """
        from ndi_ontology import _load_prefix_map
        from ndi_ontology.providers import PROVIDER_REGISTRY

        unbacked = sorted(
            {name for name in _load_prefix_map().values() if name not in PROVIDER_REGISTRY}
        )
        assert not unbacked, f"registered prefixes with no provider: {unbacked}"

    def test_there_is_no_second_hardcoded_map(self):
        import ndi_ontology

        assert not hasattr(ndi_ontology, "_PREFIX_MAP"), (
            "the literal prefix map is back; ontology_list.json must stay the "
            "single source, or the two can disagree again"
        )

    def test_aliases_resolve_to_the_canonical_ontology(self):
        from ndi_ontology import _load_prefix_map

        m = _load_prefix_map()
        assert m["format"] == "EDAM"
        assert m["taxonomy"] == "NCBITaxon"
        assert m["schema"] == "SchemaOrg"
