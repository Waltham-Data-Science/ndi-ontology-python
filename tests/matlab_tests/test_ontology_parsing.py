"""
Port of MATLAB ndi.unittest.ontology.* tests added with the WormBase rename.

MATLAB source files:
  +ontology/TestNCBITaxonOtherNames.m -> TestNCBITaxonOtherNames
  +ontology/TestWormBaseParsing.m     -> TestWormBaseParsing
  +ontology/TestLookupStringInput.m   -> TestLookupStringInput
  +ontology/TestLookupSynonyms.m      -> TestLookupSynonymsLive

The first three run offline; TestLookupSynonymsLive queries NCBI and WormMine.
"""

import pytest

from ndi_ontology import clearCache, lookup
from ndi_ontology.providers import NCBITaxonProvider, WormBaseProvider
from tests._live import network_available

# ===========================================================================
# TestNCBITaxonOtherNames
# ===========================================================================


class TestNCBITaxonOtherNames:
    """The names NCBITaxon returns as synonyms, read from literal efetch records.

    The parser this replaces read only <CommonName> and every <DispName>, so a
    <Synonym> or a <GenbankCommonName> was never returned, and authority
    citations ('Mus musculus Linnaeus, 1758') and misspellings were.
    """

    def test_former_genus_is_a_synonym(self):
        # NCBITaxon:6239, as efetch returns it
        xml = (
            "<TaxaSet><Taxon><TaxId>6239</TaxId>"
            "<ScientificName>Caenorhabditis elegans</ScientificName>"
            "<OtherNames>"
            "<Synonym>Rhabditis elegans</Synonym>"
            "<Name><ClassCDE>authority</ClassCDE>"
            "<DispName>Caenorhabditis elegans (Maupas, 1900)</DispName></Name>"
            "<Name><ClassCDE>authority</ClassCDE>"
            "<DispName>Rhabditis elegans Maupas, 1899</DispName></Name>"
            "</OtherNames></Taxon></TaxaSet>"
        )
        assert NCBITaxonProvider.parseOtherNames(xml) == ["Rhabditis elegans"]

    def test_common_names_and_not_includes_or_misspellings(self):
        # NCBITaxon:10090, shortened
        xml = (
            "<OtherNames>"
            "<GenbankCommonName>house mouse</GenbankCommonName>"
            "<CommonName>mouse</CommonName>"
            "<Includes>nude mice</Includes>"
            "<Name><ClassCDE>authority</ClassCDE>"
            "<DispName>Mus musculus Linnaeus, 1758</DispName></Name>"
            "<Name><ClassCDE>misspelling</ClassCDE>"
            "<DispName>mice C57BL/6xCBA/CaJ hybrid</DispName></Name>"
            "</OtherNames>"
        )
        assert NCBITaxonProvider.parseOtherNames(xml) == ["house mouse", "mouse"]

    def test_name_entries_of_a_kept_kind(self):
        xml = (
            "<OtherNames>"
            "<Name><ClassCDE>equivalent name</ClassCDE>"
            "<DispName>Escherichia coli &amp; relatives</DispName></Name>"
            "<Name><ClassCDE>synonym</ClassCDE>"
            "<DispName>Bacillus coli</DispName></Name>"
            "<Synonym>Bacillus coli</Synonym>"
            "</OtherNames>"
        )
        assert NCBITaxonProvider.parseOtherNames(xml) == [
            "Bacillus coli",
            "Escherichia coli & relatives",
        ]

    def test_no_other_names(self):
        assert (
            NCBITaxonProvider.parseOtherNames("<Taxon><ScientificName>x</ScientificName></Taxon>")
            == []
        )
        assert (
            NCBITaxonProvider.parseOtherNames(
                "<OtherNames><Name><ClassCDE>authority</ClassCDE>"
                "<DispName>x Smith, 1900</DispName></Name></OtherNames>"
            )
            == []
        )


# ===========================================================================
# TestWormBaseParsing
# ===========================================================================


class TestWormBaseParsing:
    """How a WormMine strain record becomes the WBStrain lookup outputs.

    The records are the ones WormMine returns for N2, MT13113 and BK6.
    """

    def test_wild_type(self):
        s = {
            "primaryIdentifier": "WBStrain00000001",
            "name": "N2",
            "genotype": "Caenorhabditis elegans wild isolate.",
            "otherName": None,
            "mutagen": None,
            "outcrossed": None,
        }
        id_, name, definition, synonyms = WormBaseProvider.parseStrain(s)
        assert id_ == "WBStrain:00000001"
        assert name == "N2"
        assert definition == "Genotype: Caenorhabditis elegans wild isolate."
        assert synonyms == []

    def test_mutant(self):
        s = {
            "primaryIdentifier": "WBStrain00027424",
            "name": "MT13113",
            "genotype": "tdc-1(n3419) II.",
            "otherName": None,
            "mutagen": "UV+TMP",
            "outcrossed": "x11",
        }
        id_, name, definition, _ = WormBaseProvider.parseStrain(s)
        assert id_ == "WBStrain:00027424"
        assert name == "MT13113"
        assert definition == "Genotype: tdc-1(n3419) II. Mutagen: UV+TMP. Outcrossed: x11."

    def test_other_name_is_a_synonym(self):
        s = {
            "primaryIdentifier": "WBStrain00003818",
            "name": "BK6",
            "genotype": None,
            "otherName": "BK006",
            "mutagen": None,
            "outcrossed": None,
        }
        _, _, definition, synonyms = WormBaseProvider.parseStrain(s)
        assert definition == ""
        assert synonyms == ["BK006"]

    def test_record_without_an_id_is_an_error(self):
        # MATLAB: verifyError(..., 'ndi:ontology:WormBase:APIParsingFailed')
        with pytest.raises(ValueError, match="valid WBStrain ID"):
            WormBaseProvider.parseStrain({"primaryIdentifier": None, "name": "N2"})


# ===========================================================================
# TestLookupStringInput
# ===========================================================================


class TestLookupStringInput:
    """lookup() of a string gives the same result as of a character vector.

    MATLAB's fix (convertStringsToChars at the top of ndi.ontology.lookup) has
    nothing to port: Python has one string type. The test is kept so the two
    suites stay one-to-one. NDIC is read from a packaged file, so no network.
    """

    def test_string_gives_the_same_result_as_char(self):
        clearCache()
        first = lookup("NDIC:8")
        clearCache()
        second = lookup("NDIC:8")
        assert first.id == second.id
        assert first.name == second.name
        assert first.prefix == "NDIC"
        assert second.prefix == "NDIC"


# ===========================================================================
# TestLookupSynonyms - Live network
# ===========================================================================


@pytest.mark.live
class TestLookupSynonymsLive:
    """The synonyms lookup() returns, from the live services."""

    @pytest.fixture(autouse=True)
    def _requires_network(self):
        if not network_available():
            pytest.skip("No network access for ontology lookup")

    def test_c_elegans_former_genus(self):
        clearCache()
        result = lookup("NCBITaxon:6239")
        assert result.name == "Caenorhabditis elegans"
        assert (
            "Rhabditis elegans" in result.synonyms
        ), "NCBI lists Rhabditis elegans as a synonym of C. elegans."
        assert not any(
            "Maupas" in s for s in result.synonyms
        ), "Authority citations are not synonyms."

    def test_mouse_common_names(self):
        clearCache()
        result = lookup("NCBITaxon:10090")
        assert {"house mouse", "mouse"} <= set(
            result.synonyms
        ), 'NCBI lists "house mouse" (GenBank) and "mouse" for Mus musculus.'

    def test_strain_definition(self):
        clearCache()
        result = lookup("WBStrain:MT13113")
        assert result.name == "MT13113"
        assert "tdc-1(n3419)" in result.definition, "The definition carries the strain genotype."
