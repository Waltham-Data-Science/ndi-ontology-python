"""Tests for ndi_ontology — ontology lookup system with providers."""

from unittest.mock import MagicMock, patch

import pytest

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

    def test_no_colon_raises(self):
        """An unprefixed string is not a lookup. MATLAB errors; so do we."""
        import pytest

        from ndi_ontology import NDIOntologyLookupError, lookup

        with pytest.raises(NDIOntologyLookupError, match="no ontology prefix"):
            lookup("neuron")

    def test_unknown_prefix_raises_and_names_the_known_ones(self):
        import pytest

        from ndi_ontology import NDIOntologyLookupError, lookup

        with pytest.raises(NDIOntologyLookupError) as excinfo:
            lookup("UNKNOWN:12345")

        message = str(excinfo.value)
        assert "UNKNOWN" in message
        # The message lists what *is* registered, which is the first thing
        # anyone hitting this needs.
        assert "NDIC" in message

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

    def test_remainder_is_trimmed_before_the_provider_sees_it(self):
        """ontology.m:493 -- remainder = strtrim(...) before lookupTermOrID."""
        from ndi_ontology import OntologyResult, lookup

        with patch("ndi_ontology.providers.OLSProvider.lookup_term") as mock_lt:
            mock_lt.return_value = OntologyResult(id="CL:0000540", name="neuron")
            lookup("CL:  0000540 \t")
        mock_lt.assert_called_once_with("0000540", "CL")

    @pytest.mark.parametrize("typed", ["NDIC: 8", " NDIC:8", "NDIC :8", "  ndic : 8  "])
    def test_whitespace_around_prefix_or_term_resolves(self, typed):
        """ontology.m:493 trims both halves; the prefix before it is mapped."""
        from ndi_ontology import lookup

        result = lookup(typed)
        assert result.name == "Experienced cricket hunting"
        assert result.prefix == typed.split(":", 1)[0].strip()

    def test_provider_exception_is_chained(self):
        """A provider error surfaces as NDIOntologyLookupError, cause intact.

        The failure is not separately typed -- MATLAB raises one MException for
        every kind of failure and so do we -- but chaining keeps a transport
        problem diagnosable instead of indistinguishable from a missing term,
        which is the ambiguity this whole change removes.
        """
        import pytest

        from ndi_ontology import NDIOntologyLookupError, lookup

        with patch("ndi_ontology.providers.OLSProvider.lookup_term") as mock_lt:
            mock_lt.side_effect = RuntimeError("API down")
            with pytest.raises(NDIOntologyLookupError) as excinfo:
                lookup("CL:0000540")

        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert "API down" in str(excinfo.value)

    def test_a_failed_lookup_is_not_cached(self):
        """A failure must not become permanent for the life of the process."""
        import pytest

        from ndi_ontology import NDIOntologyLookupError, _lookup_cache, lookup

        with patch("ndi_ontology.providers.OLSProvider.lookup_term") as mock_lt:
            mock_lt.side_effect = RuntimeError("transient")
            with pytest.raises(NDIOntologyLookupError):
                lookup("CL:0000540")

        assert "CL:0000540" not in _lookup_cache


class TestLookupSetsMatlabFields:
    """lookup() sets prefix, synonyms and shortName itself, as MATLAB's does.

    MATLAB: ontology.m:295 (prefix), :316-327 (synonyms), :332 (shortName).
    """

    def setup_method(self):
        from ndi_ontology import clearCache

        clearCache()

    teardown_method = setup_method

    def test_short_name_is_name2variableName_not_ols_short_form(self):
        """The case that gave NDI-python different table columns from MATLAB."""
        from ndi_ontology import OntologyResult, lookup

        provided = OntologyResult(
            id="CHEBI:15377", name="water", prefix="CHEBI", short_name="CHEBI_15377"
        )
        with patch("ndi_ontology.providers.OLSProvider.lookup_term", return_value=provided):
            result = lookup("CHEBI:15377")
        assert result.short_name == "Water"

    def test_short_name_is_set_where_the_provider_left_it_blank(self):
        from ndi_ontology import lookup

        assert lookup("NDIC:8").short_name == "ExperiencedCricketHunting"

    @pytest.mark.parametrize("typed", ["NDIC", "ndic", "Ndic"])
    def test_prefix_is_the_prefix_as_typed(self, typed):
        """MATLAB returns the caller's prefix, not the ontology's canonical one."""
        from ndi_ontology import lookup

        assert lookup(f"{typed}:8").prefix == typed

    def test_alias_prefix_is_kept(self):
        from ndi_ontology import OntologyResult, lookup

        provided = OntologyResult(id="9606", name="Homo sapiens", prefix="NCBITaxon")
        with patch("ndi_ontology.providers.NCBITaxonProvider.lookup_term", return_value=provided):
            assert lookup("taxonomy:9606").prefix == "taxonomy"

    def test_synonyms_are_flattened_and_empties_dropped(self):
        from ndi_ontology import OntologyResult, lookup

        provided = OntologyResult(
            id="CL:0000540", name="neuron", synonyms=["nerve cell", "", ["neurone", ""]]
        )
        with patch("ndi_ontology.providers.OLSProvider.lookup_term", return_value=provided):
            result = lookup("CL:0000540")
        assert result.synonyms == ["nerve cell", "neurone"]


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
        assert "WormBase" in PROVIDER_REGISTRY
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
        # OM's own file holds no match, so the lookup falls back to OLS.
        empty_index = {"local": [], "label": [], "definition": [], "alternative": [], "kind": []}
        with (
            patch.object(OMProvider, "fileIndex", return_value=empty_index),
            patch.object(provider, "_http_get_json", return_value=mock_response) as mock_get,
        ):
            provider.lookup_term("milliMetre")
            # Should convert CamelCase to 'milli metre'
            args, kwargs = mock_get.call_args
            assert kwargs["params"]["q"] == "milli metre"

    INDEX = {
        "local": ["metre", "second-Time"],
        "label": ["metre", "second"],
        "definition": ["The metre is a unit of length.", ""],
        "alternative": [["meter"], []],
        "kind": ["om:Unit", "om:SingularUnit"],
    }

    def test_unit_is_read_from_oms_file_without_ols(self):
        """MATLAB OM.m step 0: units are individuals, which OLS lacks."""
        from ndi_ontology.providers import OMProvider

        provider = OMProvider()
        with (
            patch.object(OMProvider, "fileIndex", return_value=self.INDEX),
            patch.object(provider, "_http_get_json") as mock_get,
        ):
            result = provider.lookup_term("meter", "OM")
        mock_get.assert_not_called()
        assert result.id == "OM:metre"
        assert result.name == "metre"
        assert result.definition == "The metre is a unit of length."
        assert result.synonyms == ["meter"]

    def test_numeric_term_skips_the_file(self):
        from ndi_ontology.providers import OMProvider

        provider = OMProvider()
        with (
            patch.object(OMProvider, "fileIndex") as mock_index,
            patch.object(provider, "_http_get_json", return_value={"response": {"docs": []}}),
        ):
            assert not provider.lookup_term("182", "OM")
        mock_index.assert_not_called()

    def test_unreadable_file_warns_and_falls_back_to_ols(self):
        from ndi_ontology.providers import OMProvider

        provider = OMProvider()
        doc = {"obo_id": "", "label": "molar volume unit", "short_form": "MolarVolumeUnit"}
        with (
            patch.object(OMProvider, "fileIndex", side_effect=OSError("offline")),
            patch.object(provider, "_http_get_json", return_value={"response": {"docs": [doc]}}),
            pytest.warns(UserWarning, match="falling back to OLS"),
        ):
            result = provider.lookup_term("MolarVolumeUnit", "OM")
        assert result.name == "molar volume unit"

    def test_file_index_is_downloaded_once_and_cleared_by_clearCache(self):
        from ndi_ontology import clearCache
        from ndi_ontology.providers import OMProvider

        clearCache()
        response = MagicMock(text='  <om:Unit rdf:about="&om;metre">\n  </om:Unit>\n')
        with patch("requests.get", return_value=response) as mock_get:
            first = OMProvider.fileIndex()
            second = OMProvider.fileIndex()
            assert mock_get.call_count == 1
            assert first is second
            assert first["local"] == ["metre"]
            clearCache()
            OMProvider.fileIndex()
            assert mock_get.call_count == 2
        clearCache()


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
# WormBaseProvider tests
# ---------------------------------------------------------------------------


def _wormmine(*records):
    """A WormMine jsonobjects response holding RECORDS."""
    return {"results": list(records), "wasSuccessful": True, "error": None}


_N2 = {
    "primaryIdentifier": "WBStrain00000001",
    "name": "N2",
    "genotype": "Caenorhabditis elegans wild isolate.",
    "otherName": None,
    "mutagen": None,
    "outcrossed": None,
}


class TestWormBaseProvider:
    """Tests for the WormBase strain provider (WormMine-backed)."""

    def test_numeric_id_lookup(self):
        from ndi_ontology.providers import WormBaseProvider

        provider = WormBaseProvider()
        with patch.object(provider, "_http_get_json", return_value=_wormmine(_N2)) as get:
            result = provider.lookup_term("00000001", "WBStrain")
        assert result.id == "WBStrain:00000001"
        assert result.name == "N2"
        assert result.prefix == "WBStrain"
        assert result.definition == "Genotype: Caenorhabditis elegans wild isolate."
        query = get.call_args.kwargs["params"]["query"]
        assert 'path="Strain.primaryIdentifier"' in query
        assert 'value="WBStrain00000001"' in query

    def test_name_lookup_ignores_case(self):
        from ndi_ontology.providers import WormBaseProvider

        provider = WormBaseProvider()
        with patch.object(provider, "_http_get_json", return_value=_wormmine(_N2)) as get:
            result = provider.lookup_term("n2", "WBStrain")
        assert result.id == "WBStrain:00000001"
        assert 'path="Strain.name"' in get.call_args.kwargs["params"]["query"]

    def test_bioregistry_curie_keeps_its_form(self):
        from ndi_ontology.providers import WormBaseProvider

        provider = WormBaseProvider()
        with patch.object(provider, "_http_get_json", return_value=_wormmine(_N2)):
            result = provider.lookup_term("WBStrain00000001", "wormbase")
        assert result.id == "wormbase:WBStrain00000001"
        assert result.prefix == "wormbase"

    def test_not_found_is_empty(self):
        from ndi_ontology.providers import WormBaseProvider

        provider = WormBaseProvider()
        with patch.object(provider, "_http_get_json", return_value=_wormmine()):
            result = provider.lookup_term("99999999", "WBStrain")
        assert not result

    @pytest.mark.parametrize("term", ["WBGene00000001", "CE12345", "N*"])
    def test_not_a_strain_raises_without_a_query(self, term):
        from ndi_ontology.providers import WormBaseProvider

        provider = WormBaseProvider()
        with patch.object(provider, "_http_get_json") as get:
            with pytest.raises(ValueError):
                provider.lookup_term(term, "wormbase")
        get.assert_not_called()

    def test_ambiguous_name_raises(self):
        from ndi_ontology.providers import WormBaseProvider

        provider = WormBaseProvider()
        other = dict(_N2, primaryIdentifier="WBStrain00000002")
        with patch.object(provider, "_http_get_json", return_value=_wormmine(_N2, other)):
            with pytest.raises(ValueError, match="2 WormBase strains"):
                provider.lookup_term("N2", "WBStrain")

    def test_name_mismatch_raises(self):
        from ndi_ontology.providers import WormBaseProvider

        provider = WormBaseProvider()
        with patch.object(provider, "_http_get_json", return_value=_wormmine(_N2)):
            with pytest.raises(ValueError, match="Try the WBStrain ID"):
                provider.lookup_term("N3", "WBStrain")

    def test_wormmine_error_raises(self):
        from ndi_ontology.providers import WormBaseProvider

        provider = WormBaseProvider()
        response = {"results": [], "wasSuccessful": False, "error": "bad query"}
        with patch.object(provider, "_http_get_json", return_value=response):
            with pytest.raises(ValueError, match="bad query"):
                provider.lookup_term("N2", "WBStrain")

    def test_api_error_reaches_lookup_as_lookup_error(self):
        from ndi_ontology import NDIOntologyLookupError, clearCache, lookup
        from ndi_ontology.providers import WormBaseProvider

        clearCache()
        with patch.object(WormBaseProvider, "_http_get_json", side_effect=Exception("403")):
            with pytest.raises(NDIOntologyLookupError, match="403"):
                lookup("WBStrain:N2")

    def test_both_prefixes_route_to_wormbase(self):
        from ndi_ontology import _load_prefix_map

        m = _load_prefix_map()
        assert m["WBStrain"] == "WormBase"
        assert m["wormbase"] == "WormBase"


# ---------------------------------------------------------------------------
# EMPTYProvider tests
# ---------------------------------------------------------------------------


class TestEMPTYProvider:
    """Tests for EMPTY provider, against EMPTY.m, with the downloads mocked."""

    # An excerpt of empty-base.owl in RDF/XML, as the main branch serves it.
    XML = """<?xml version="1.0"?>
<rdf:RDF xmlns:obo="http://purl.obolibrary.org/obo/"
     xmlns:owl="http://www.w3.org/2002/07/owl#"
     xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
     xmlns:oboInOwl="http://www.geneontology.org/formats/oboInOwl#">
    <owl:Class rdf:about="http://purl.obolibrary.org/obo/EMPTY_0000001">
        <obo:IAO_0000115>A measurement.</obo:IAO_0000115>
        <rdfs:label xml:lang="en">measurement</rdfs:label>
    </owl:Class>
    <owl:Class rdf:about="http://purl.obolibrary.org/obo/EMPTY_0000002">
        <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/EMPTY_0000001"/>
        <obo:IAO_0000115>An organism&apos;s
            behaviour.</obo:IAO_0000115>
        <oboInOwl:hasExactSynonym>behaviour measurement</oboInOwl:hasExactSynonym>
        <oboInOwl:hasRelatedSynonym xml:lang="en">conduct &amp; reaction</oboInOwl:hasRelatedSynonym>
        <rdfs:label xml:lang="en">behavioral measurement</rdfs:label>
    </owl:Class>
    <owl:Class rdf:about="http://purl.obolibrary.org/obo/EMPTY_0000006">
        <rdfs:label xml:lang="en">elevated plus maze: open arm (north) - entries</rdfs:label>
    </owl:Class>
</rdf:RDF>
"""

    # The same terms in OWL functional syntax, as empty-edit.owl is written.
    FUNCTIONAL = """Prefix(obo:=<http://purl.obolibrary.org/obo/>)
Ontology(<http://purl.obolibrary.org/obo/empty.owl>
Declaration(Class(obo:EMPTY_0000002))
Declaration(Class(obo:EMPTY_0000009))
AnnotationAssertion(obo:IAO_0000115 obo:EMPTY_0000009 "A draft term.")
AnnotationAssertion(oboInOwl:hasExactSynonym obo:EMPTY_0000009 "draft")
AnnotationAssertion(oboInOwl:hasRelatedSynonym obo:EMPTY_0000009 "sketch")
AnnotationAssertion(rdfs:label obo:EMPTY_0000009 "draft measurement")
AnnotationAssertion(rdfs:label obo:EMPTY_0000002 "behavioral measurement")
SubClassOf(obo:EMPTY_0000009 obo:EMPTY_0000002)
)
"""

    def setup_method(self):
        from ndi_ontology import clearCache

        clearCache()

    teardown_method = setup_method

    @staticmethod
    def _http_404(url):
        import requests

        response = requests.Response()
        response.status_code = 404
        response.url = url
        return requests.HTTPError(f"404 Client Error: Not Found for url: {url}", response=response)

    def _serve(self, main, dev=None):
        """A fake download: each value is a body to return or an exception to raise."""
        from ndi_ontology.providers import EMPTYProvider

        def fake_get(url, timeout=30):
            body = {EMPTYProvider.OWL_URL_MAIN: main, EMPTYProvider.OWL_URL_DEV: dev}[url]
            if body is None:
                raise self._http_404(url)
            if isinstance(body, Exception):
                raise body
            return body

        return patch.object(EMPTYProvider, "_http_get_text", side_effect=fake_get)

    def test_reads_the_owl_files_matlab_reads(self):
        """EMPTY.m:8-9 -- empty-base.owl on main, empty-edit.owl on development."""
        from ndi_ontology.providers import EMPTYProvider

        base = "https://raw.githubusercontent.com/Waltham-Data-Science/empty-ontology/"
        assert EMPTYProvider.OWL_URL_MAIN == base + "main/empty-base.owl"
        assert EMPTYProvider.OWL_URL_DEV == base + "development/src/ontology/empty-edit.owl"

    def test_xml_lookup_by_id(self):
        from ndi_ontology.providers import EMPTYProvider

        with self._serve(self.XML) as mock_get:
            result = EMPTYProvider().lookup_term("0000002")
        mock_get.assert_called_once_with(EMPTYProvider.OWL_URL_MAIN, timeout=30)
        assert result.id == "EMPTY:0000002"
        assert result.name == "behavioral measurement"
        # unescapeXML: entities decoded, then trimmed (EMPTY.m:193-203).
        assert result.definition == "An organism's\n            behaviour."
        assert result.synonyms == ["behaviour measurement", "conduct & reaction"]

    def test_xml_lookup_by_name_is_case_insensitive(self):
        from ndi_ontology.providers import EMPTYProvider

        with self._serve(self.XML):
            result = EMPTYProvider().lookup_term("Behavioral Measurement")
        assert result.id == "EMPTY:0000002"
        assert result.name == "behavioral measurement"

    def test_xml_name_with_punctuation(self):
        from ndi_ontology.providers import EMPTYProvider

        with self._serve(self.XML):
            result = EMPTYProvider().lookup_term("Elevated Plus Maze: open arm (north) - entries")
        assert result.id == "EMPTY:0000006"
        assert result.definition == ""
        assert result.synonyms == []

    @pytest.mark.parametrize(
        "term",
        [
            "behavioral",  # a label substring: EMPTY.m matches whole labels only
            "2",  # an unpadded id: EMPTY.m compares the digits as written
            "EMPTY_0000002",  # the OBO form: EMPTY.m compares the bare digits
            "0000000",
        ],
    )
    def test_matches_only_exact_id_or_label(self, term):
        """EMPTY.m:89 and :160 -- strcmpi(thisId, fragment) || strcmpi(thisName, fragment)."""
        from ndi_ontology.providers import EMPTYProvider

        with self._serve(self.XML, dev=None):
            result = EMPTYProvider().lookup_term(term)
        assert not result

    def test_functional_syntax_lookup_by_id(self):
        """Content with no XML declaration goes to parseFunctionalFormat (EMPTY.m:62-70)."""
        from ndi_ontology.providers import EMPTYProvider

        with self._serve(self.FUNCTIONAL):
            result = EMPTYProvider().lookup_term("0000009")
        assert result.id == "EMPTY:0000009"
        assert result.name == "draft measurement"
        assert result.definition == "A draft term."
        assert result.synonyms == ["draft", "sketch"]

    def test_functional_syntax_lookup_by_name(self):
        from ndi_ontology.providers import EMPTYProvider

        with self._serve(self.FUNCTIONAL):
            result = EMPTYProvider().lookup_term("BEHAVIORAL MEASUREMENT")
        assert result.id == "EMPTY:0000002"
        assert result.name == "behavioral measurement"

    def test_falls_back_to_development_when_main_lacks_the_term(self):
        """EMPTY.m:28-33 -- a term only on development is found there."""
        from ndi_ontology import lookup
        from ndi_ontology.providers import EMPTYProvider

        with self._serve(self.XML, dev=self.FUNCTIONAL) as mock_get:
            result = lookup("EMPTY:draft measurement")
        assert result.id == "EMPTY:0000009"
        assert [c.args[0] for c in mock_get.call_args_list] == [
            EMPTYProvider.OWL_URL_MAIN,
            EMPTYProvider.OWL_URL_DEV,
        ]

    def test_falls_back_to_development_when_main_fails(self):
        import requests

        from ndi_ontology import lookup

        with self._serve(requests.Timeout("timed out"), dev=self.FUNCTIONAL):
            assert lookup("EMPTY:0000009").name == "draft measurement"

    def test_not_found_with_no_development_branch(self):
        """EMPTY.m:39-43 -- dev 404s, so main's TermNotFound is what surfaces."""
        from ndi_ontology import NDIOntologyLookupError, lookup

        with self._serve(self.XML, dev=None):
            with pytest.raises(NDIOntologyLookupError, match="not found in ontology EMPTY"):
                lookup("EMPTY:NoSuchTermHere")

    def test_main_failure_surfaces_when_development_404s(self):
        """EMPTY.m:41 -- throw(mainError): the main branch's error, not the 404."""
        import requests

        from ndi_ontology import NDIOntologyLookupError, lookup

        with self._serve(requests.Timeout("timed out"), dev=None):
            with pytest.raises(NDIOntologyLookupError, match="timed out") as excinfo:
                lookup("EMPTY:0000002")
        assert isinstance(excinfo.value.__cause__, requests.Timeout)

    def test_failure_on_both_branches_names_both(self):
        """EMPTY.m:46-51 -- a non-404 failure on development combines both errors."""
        import requests

        from ndi_ontology import NDIOntologyLookupError, lookup
        from ndi_ontology.providers import EMPTYProvider

        with self._serve(requests.Timeout("main timed out"), dev=self.FUNCTIONAL):
            with pytest.raises(
                NDIOntologyLookupError, match="both MAIN and DEVELOPMENT"
            ) as excinfo:
                lookup("EMPTY:NoSuchTermHere")
        cause = excinfo.value.__cause__
        assert isinstance(cause, EMPTYProvider.LookupFailed)
        assert isinstance(cause.main_error, requests.Timeout)
        assert isinstance(cause.dev_error, EMPTYProvider.TermNotFound)

    def test_failed_download_raises_and_is_not_cached(self):
        """One timeout must not become a permanent "not found"."""
        import requests

        from ndi_ontology import NDIOntologyLookupError, lookup
        from ndi_ontology.providers import EMPTYProvider

        with self._serve(requests.Timeout("timed out"), dev=None):
            with pytest.raises(NDIOntologyLookupError, match="timed out"):
                lookup("EMPTY:0000002")
        assert not EMPTYProvider._cache

        # The next lookup downloads again and succeeds, with no clearCache().
        with self._serve(self.XML):
            assert lookup("EMPTY:0000002").id == "EMPTY:0000002"

    def test_download_is_cached_until_clearCache(self):
        from ndi_ontology import clearCache
        from ndi_ontology.providers import EMPTYProvider

        provider = EMPTYProvider()
        with self._serve(self.XML) as mock_get:
            provider.lookup_term("0000002")
            provider.lookup_term("0000001")
            assert mock_get.call_count == 1
            clearCache()
            assert EMPTYProvider._cache is None
            provider.lookup_term("0000002")
            assert mock_get.call_count == 2


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

    # ontology_name_ols and ontology_prefix, as each MATLAB class sets them
    OLS_PARAMS = {
        "Uberon": ("uberon", "UBERON"),
        "NCIT": ("ncit", "NCIT"),
        "STATO": ("stato", "STATO"),
        "MICRO": ("micro", "MICRO"),
        "MCO": ("mco", "MCO"),
        "OBI": ("obi", "OBI"),
        "ZECO": ("zeco", "ZECO"),
        "WBls": ("wbls", "WBls"),
    }

    def test_ols_parameters_match_matlab(self):
        from ndi_ontology.providers import PROVIDER_REGISTRY, OLSProvider

        for key, (ontology, prefix) in self.OLS_PARAMS.items():
            cls = PROVIDER_REGISTRY[key]
            assert issubclass(cls, OLSProvider)
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


class TestCREDITProvider:
    """MATLAB equivalent: +ndi/+ontology/CREDIT.m. Offline: the roles are held here."""

    def test_lookup_by_slug(self):
        from ndi_ontology import lookup

        result = lookup("credit:data-curation")
        assert result.id == "credit:data-curation"
        assert result.name == "Data curation"
        assert result.definition.startswith("Management activities")
        assert result.synonyms == ["CREDIT:00000002"]

    @pytest.mark.parametrize(
        "term",
        [
            "writing-review-editing",
            "Writing \u2013 review & editing",
            "Writing - review & editing",
            "writing review and editing role",
            "00000014",
            "14",
            "CREDIT_00000014",
            "credit:14",
        ],
    )
    def test_lookup_by_name_or_number(self, term):
        from ndi_ontology.providers import CREDITProvider

        result = CREDITProvider().lookup_term(term, "credit")
        assert result.id == "credit:writing-review-editing"
        assert result.name == "Writing \u2013 review & editing"

    def test_the_cro_numbering_is_an_alias(self):
        from ndi_ontology import lookup

        assert lookup("CREDIT:00000001").id == "credit:conceptualization"

    @pytest.mark.parametrize("term", ["corresponding author", "00000015", "0", "", "role"])
    def test_not_found_raises(self, term):
        from ndi_ontology import NDIOntologyLookupError, lookup

        with pytest.raises(NDIOntologyLookupError, match="CRediT roles"):
            lookup(f"credit:{term}")

    def test_fourteen_roles_with_distinct_slugs(self):
        from ndi_ontology.providers import CREDITProvider

        slugs = [row[0] for row in CREDITProvider.ROLES]
        assert len(slugs) == 14
        assert len(set(slugs)) == 14


class TestOWLTimeProvider:
    """MATLAB equivalent: +ndi/+ontology/OWLTime.m. Offline: the relations are held here."""

    @pytest.mark.parametrize(
        "term", ["intervalDuring", "interval during", "INTERVAL_DURING", " IntervalDuring "]
    )
    def test_lookup_by_local_name_or_label(self, term):
        from ndi_ontology.providers import OWLTimeProvider

        result = OWLTimeProvider().lookup_term(term, "time")
        assert result.id == "time:intervalDuring"
        assert result.name == "interval during"
        assert result.synonyms == ["http://www.w3.org/2006/time#intervalDuring"]
        assert result.definition.startswith("If a proper interval T1 is intervalDuring")

    def test_prefix_is_case_insensitive(self):
        from ndi_ontology import lookup

        assert lookup("TIME:intervalMetBy").id == "time:intervalMetBy"

    def test_fifteen_relations(self):
        from ndi_ontology.providers import OWLTimeProvider

        assert len(OWLTimeProvider.RELATIONS) == 15

    @pytest.mark.parametrize("term", ["Instant", "", "interval"])
    def test_not_found_raises(self, term):
        from ndi_ontology import NDIOntologyLookupError, lookup

        with pytest.raises(NDIOntologyLookupError, match="interval relations"):
            lookup(f"time:{term}")


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
