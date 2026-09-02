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
