"""
ndi_ontology.providers - Ontology provider implementations.

MATLAB equivalents: ndi-ontology-matlab src/ndi/+ndi/+ontology/*.m

Each provider subclasses OntologyProvider and implements lookup_term().
"""

from __future__ import annotations

import csv
import re
from typing import Any
from urllib.parse import quote

import pydantic

# Registry populated at module load
PROVIDER_REGISTRY: dict[str, type[OntologyProvider]] = {}


class OntologyProvider:
    """Base class for ontology providers."""

    name: str = ""

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        """Look up a term by ID or name. Override in subclasses."""
        from . import OntologyResult

        return OntologyResult()

    @staticmethod
    def _http_get_json(url: str, params: dict | None = None, timeout: int = 30) -> Any:
        """HTTP GET returning parsed JSON."""
        import requests

        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# OLS-based providers (shared logic)
# ---------------------------------------------------------------------------


class OLSProvider(OntologyProvider):
    """Provider backed by the EBI OLS4 API."""

    ols_ontology: str = ""
    ols_prefix: str = ""

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:

        prefix = prefix or self.ols_prefix

        is_numeric = bool(re.match(r"^\d+$", term))

        if is_numeric:
            full_id = f"{prefix}:{term.zfill(7)}"
            return self._search_ols(full_id, "obo_id", prefix)
        else:
            return self._search_ols(term, "label", prefix)

    def _search_ols(self, query: str, field: str, prefix: str) -> Any:
        from . import OntologyResult

        try:
            params: dict[str, Any] = {
                "q": query,
                "ontology": self.ols_ontology,
                "queryFields": field,
            }
            if field == "obo_id":
                params["exact"] = "true"

            data = self._http_get_json(
                "https://www.ebi.ac.uk/ols4/api/search",
                params=params,
            )

            docs = data.get("response", {}).get("docs", [])
            if not docs:
                return OntologyResult()

            # For label search, find exact match
            if field == "label":
                for doc in docs:
                    if doc.get("label", "").lower() == query.lower():
                        return self._doc_to_result(doc, prefix)
                return OntologyResult()

            doc = docs[0]
            return self._doc_to_result(doc, prefix)

        except Exception:
            return OntologyResult()

    def _doc_to_result(self, doc: dict, prefix: str) -> Any:
        from . import OntologyResult

        obo_id = doc.get("obo_id", "")
        if not obo_id:
            short = doc.get("short_form", "")
            if short:
                obo_id = short.replace("_", ":")

        desc_list = doc.get("description", [])
        definition = desc_list[0] if isinstance(desc_list, list) and desc_list else ""

        synonyms = doc.get("synonym", [])
        if isinstance(synonyms, list):
            synonyms = [s if isinstance(s, str) else s.get("name", "") for s in synonyms]

        return OntologyResult(
            id=obo_id,
            name=doc.get("label", ""),
            prefix=prefix,
            definition=definition,
            synonyms=synonyms,
            short_name=doc.get("short_form", ""),
        )


# ---------------------------------------------------------------------------
# Individual providers
# ---------------------------------------------------------------------------


class CLProvider(OLSProvider):
    name = "CL"
    ols_ontology = "cl"
    ols_prefix = "CL"


class OMProvider(OLSProvider):
    """Ontology of Units of Measure — label-only lookups."""

    name = "OM"
    ols_ontology = "om"
    ols_prefix = "OM"

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:

        # OM doesn't support numeric ID lookups
        # Convert CamelCase to spaced lowercase for label search
        label = re.sub(r"([a-z])([A-Z])", r"\1 \2", term).lower()
        return self._search_ols(label, "label", prefix or "OM")


class CHEBIProvider(OLSProvider):
    name = "CHEBI"
    ols_ontology = "chebi"
    ols_prefix = "CHEBI"


class SNOMEDProvider(OLSProvider):
    name = "SNOMED"
    ols_ontology = "snomed"
    ols_prefix = "SNOMED"


class EFOProvider(OLSProvider):
    name = "EFO"
    ols_ontology = "efo"
    ols_prefix = "EFO"


class PATOProvider(OLSProvider):
    name = "PATO"
    ols_ontology = "pato"
    ols_prefix = "PATO"


class NDICProvider(OntologyProvider):
    """NDI Controlled Vocabulary — local TSV file."""

    name = "NDIC"

    _data: list[dict[str, str]] | None = None

    def _load_data(self) -> list[dict[str, str]]:
        if NDICProvider._data is not None:
            return NDICProvider._data

        try:
            from .paths import NDIC_FILE

            path = NDIC_FILE
            if not path.exists():
                NDICProvider._data = []
                return []

            entries: list[dict[str, str]] = []
            with open(path) as f:
                reader = csv.reader(f, delimiter="\t")
                for row in reader:
                    if len(row) >= 3:
                        entries.append(
                            {
                                "id": row[0].strip(),
                                "name": row[1].strip(),
                                "description": row[2].strip(),
                            }
                        )
            NDICProvider._data = entries
            return entries
        except Exception:
            NDICProvider._data = []
            return []

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        data = self._load_data()

        for entry in data:
            if entry["id"] == term or entry["name"].lower() == term.lower():
                return OntologyResult(
                    # Bare identifier, no "NDIC:" prefix. MATLAB's NDIC.m:67 is
                    # `id = num2str(ndicData.Identifier(rowIndex))`, and the
                    # README's "external database lookups" rule says the prefix
                    # may not appear in the returned id.
                    id=entry["id"],
                    name=entry["name"],
                    prefix="NDIC",
                    definition=entry["description"],
                )
        return OntologyResult()


class NCImProvider(OntologyProvider):
    """NCI Metathesaurus — NCI EVS REST API."""

    name = "NCIm"
    _CUI_PATTERN = re.compile(r"^C\d{7}$")

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        try:
            if self._CUI_PATTERN.match(term):
                return self._lookup_cui(term)
            return self._search_name(term)
        except Exception:
            return OntologyResult()

    def _lookup_cui(self, cui: str) -> Any:
        from . import OntologyResult

        data = self._http_get_json(
            f"https://api-evsrest.nci.nih.gov/api/v1/concept/ncim/{cui}",
            params={"include": "full"},
        )
        defs = data.get("definitions", [])
        definition = defs[0].get("definition", "") if defs else ""
        syns = [s.get("name", "") for s in data.get("synonyms", []) if isinstance(s, dict)]

        return OntologyResult(
            # Bare concept code, no "NCIm:" prefix -- MATLAB NCIm.m:138,
            # `id = char(data.code)`.
            id=data.get("code", cui),
            name=data.get("name", ""),
            prefix="NCIm",
            definition=definition,
            synonyms=syns,
        )

    def _search_name(self, name: str) -> Any:
        from . import OntologyResult

        data = self._http_get_json(
            "https://api-evsrest.nci.nih.gov/api/v1/concept/search",
            params={"terminology": "ncim", "term": name, "type": "match"},
        )
        concepts = data.get("concepts", [])
        if not concepts:
            return OntologyResult()
        return self._lookup_cui(concepts[0].get("code", ""))


class NCBITaxonProvider(OntologyProvider):
    """NCBI Taxonomy — NCBI E-utilities."""

    name = "NCBITaxon"

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        try:
            if term.isdigit():
                return self._lookup_taxid(term)
            return self._search_name(term)
        except Exception:
            return OntologyResult()

    def _lookup_taxid(self, taxid: str) -> Any:
        import xml.etree.ElementTree as ET

        import requests

        from . import OntologyResult

        resp = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db": "taxonomy", "id": taxid, "retmode": "xml"},
            timeout=30,
        )
        root = ET.fromstring(resp.text)
        taxon = root.find(".//Taxon")
        if taxon is None:
            return OntologyResult()

        name = taxon.findtext("ScientificName", "")
        synonyms = []
        for other in taxon.findall(".//OtherNames/Name/DispName"):
            if other.text:
                synonyms.append(other.text)
        common = taxon.findtext(".//OtherNames/CommonName", "")
        if common:
            synonyms.insert(0, common)

        return OntologyResult(
            id=f"NCBITaxon:{taxid}",
            name=name,
            prefix="NCBITaxon",
            synonyms=synonyms,
        )

    def _search_name(self, name: str) -> Any:
        import xml.etree.ElementTree as ET

        import requests

        from . import OntologyResult

        resp = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "taxonomy", "term": f"{name}[Scientific Name]", "retmode": "xml"},
            timeout=30,
        )
        root = ET.fromstring(resp.text)
        id_list = root.findall(".//Id")
        if not id_list:
            return OntologyResult()
        return self._lookup_taxid(id_list[0].text or "")


class WBStrainProvider(OntologyProvider):
    """WormBase Strain ndi_database."""

    name = "WBStrain"

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        try:
            if re.match(r"^\d{8}$", term):
                return self._lookup_id(term)
            return self._search_name(term)
        except Exception:
            return OntologyResult()

    def _lookup_id(self, strain_id: str) -> Any:
        from . import OntologyResult

        data = self._http_get_json(
            f"http://rest.wormbase.org/rest/widget/strain/{strain_id}/overview",
        )
        overview = data.get("fields", {})
        name_data = overview.get("name", {}).get("data", {})
        name = name_data.get("label", "") if isinstance(name_data, dict) else ""
        genotype = overview.get("genotype", {}).get("data", "")

        return OntologyResult(
            id=f"WBStrain:{strain_id}",
            name=name,
            prefix="WBStrain",
            definition=str(genotype) if genotype else "",
        )

    def _search_name(self, name: str) -> Any:
        from . import OntologyResult

        data = self._http_get_json(
            "https://www.alliancegenome.org/api/search",
            params={"category": "model", "q": f"{name}(Cel)"},
        )
        results = data.get("results", [])
        if not results:
            return OntologyResult()
        primary_id = results[0].get("primaryId", "")
        strain_id = primary_id.split(":")[-1] if ":" in primary_id else primary_id
        return self._lookup_id(strain_id)


class RRIDProvider(OntologyProvider):
    """Research Resource Identifier — SciCrunch resolver."""

    name = "RRID"

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        try:
            full_rrid = f"RRID:{term}"
            data = self._http_get_json(
                f"https://scicrunch.org/resolver/{full_rrid}.json",
            )
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                return OntologyResult()

            source = hits[0].get("_source", {}).get("item", {})
            return OntologyResult(
                id=full_rrid,
                name=source.get("name", ""),
                prefix="RRID",
                definition=source.get("description", ""),
                synonyms=(
                    source.get("synonyms", []) if isinstance(source.get("synonyms"), list) else []
                ),
            )
        except Exception:
            return OntologyResult()


class PubChemProvider(OntologyProvider):
    """PubChem Compound — PUG REST API."""

    name = "PubChem"

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        try:
            # Detect CID
            cid = ""
            if term.isdigit():
                cid = term
            elif term.lower().startswith("cid"):
                cid = term[3:].lstrip(":").strip()
            if cid:
                return self._lookup_cid(cid)
            return self._search_name(term)
        except Exception:
            return OntologyResult()

    def _lookup_cid(self, cid: str) -> Any:
        from . import OntologyResult

        base = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid"

        title_data = self._http_get_json(f"{base}/{cid}/property/Title/JSON")
        props = title_data.get("PropertyTable", {}).get("Properties", [{}])
        title = props[0].get("Title", "") if props else ""

        try:
            desc_data = self._http_get_json(f"{base}/{cid}/description/JSON")
            descs = desc_data.get("InformationList", {}).get("Information", [])
            definition = descs[0].get("Description", "") if descs else ""
        except Exception:
            definition = ""

        try:
            syn_data = self._http_get_json(f"{base}/{cid}/synonyms/JSON")
            syn_info = syn_data.get("InformationList", {}).get("Information", [])
            synonyms = syn_info[0].get("Synonym", [])[:10] if syn_info else []
        except Exception:
            synonyms = []

        return OntologyResult(
            # Bare CID, no "PubChem:" prefix -- MATLAB PubChem.m:148,
            # `id = char(cid)`.
            id=cid,
            name=title,
            prefix="PubChem",
            definition=definition,
            synonyms=synonyms,
        )

    def _search_name(self, name: str) -> Any:
        from . import OntologyResult

        data = self._http_get_json(
            f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{quote(name)}/cids/JSON",
        )
        cids = data.get("IdentifierList", {}).get("CID", [])
        if not cids:
            return OntologyResult()
        return self._lookup_cid(str(cids[0]))


class EMPTYProvider(OntologyProvider):
    """Experimental Measurements, Purposes, and Treatments ontologY (EMPTY).

    MATLAB equivalent: +ndi/+ontology/EMPTY.m

    Fetches the EMPTY ontology as JSON from the Waltham-ndi_gui_Data-Science
    GitHub repository and caches it in memory. Supports lookup by
    numeric ID (e.g. ``"0000074"``), full OBO-style ID
    (e.g. ``"EMPTY_0000074"``), or label substring
    (e.g. ``"Optogenetic Tetanus Stimulation Target Location"``).
    """

    name = "EMPTY"

    _JSON_URL = (
        "https://raw.githubusercontent.com/Waltham-ndi_gui_Data-Science/empty-ontology"
        "/main/empty-base.json"
    )

    # Class-level cache shared across instances
    _cache: dict[str, Any] | None = None

    def _load_ontology(self) -> dict[str, Any]:
        """Fetch and parse empty-base.json, caching in class variable."""
        if EMPTYProvider._cache is not None:
            return EMPTYProvider._cache

        try:
            data = self._http_get_json(self._JSON_URL, timeout=30)
        except Exception:
            EMPTYProvider._cache = {"nodes": [], "edges": []}
            return EMPTYProvider._cache

        # The JSON has a single graph with nodes and edges
        graphs = data.get("graphs", [])
        graph = graphs[0] if graphs else {}

        # Build lookup indices
        nodes = graph.get("nodes", [])
        by_id: dict[str, dict] = {}
        by_label: dict[str, dict] = {}
        for node in nodes:
            node_id = node.get("id", "")
            label = node.get("lbl", "")
            # Extract the EMPTY_NNNNNNN suffix from the IRI
            obo_id = ""
            if "EMPTY_" in node_id:
                obo_id = node_id.rsplit("/", 1)[-1]  # e.g. EMPTY_0000074
            by_id[obo_id] = node
            if label:
                by_label[label.lower()] = node

        EMPTYProvider._cache = {
            "nodes": nodes,
            "by_id": by_id,
            "by_label": by_label,
        }
        return EMPTYProvider._cache

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult
        from .name_utils import name_to_variable_name

        cache = self._load_ontology()
        by_id = cache.get("by_id", {})
        by_label = cache.get("by_label", {})

        node = None

        # Try numeric ID: "0000074" -> "EMPTY_0000074"
        if re.match(r"^\d+$", term):
            obo_key = f"EMPTY_{term.zfill(7)}"
            node = by_id.get(obo_key)
        # Try full OBO ID: "EMPTY_0000074"
        elif term.startswith("EMPTY_"):
            node = by_id.get(term)
        # Try exact label match (case-insensitive)
        if node is None:
            node = by_label.get(term.lower())
        # Try substring match on labels
        if node is None:
            term_lower = term.lower()
            for label, n in by_label.items():
                if term_lower in label:
                    node = n
                    break

        if node is None:
            return OntologyResult(prefix="EMPTY")

        label = node.get("lbl", "")
        node_id = node.get("id", "")
        # Build EMPTY:NNNNNNN style ID
        obo_id = ""
        if "EMPTY_" in node_id:
            suffix = node_id.rsplit("/", 1)[-1]  # EMPTY_0000074
            obo_id = suffix.replace("_", ":", 1)  # EMPTY:0000074

        # Extract definition
        meta = node.get("meta", {})
        definition = ""
        if isinstance(meta, dict):
            defn = meta.get("definition", {})
            if isinstance(defn, dict):
                definition = defn.get("val", "")

        # Extract synonyms
        synonyms = []
        if isinstance(meta, dict):
            for syn in meta.get("synonyms", []):
                if isinstance(syn, dict):
                    synonyms.append(syn.get("val", ""))

        return OntologyResult(
            id=obo_id,
            name=label,
            prefix="EMPTY",
            definition=definition,
            synonyms=synonyms,
            short_name=name_to_variable_name(label),
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PROVIDER_REGISTRY.update(
    {
        "CL": CLProvider,
        "OM": OMProvider,
        "NDIC": NDICProvider,
        "NCIm": NCImProvider,
        "CHEBI": CHEBIProvider,
        "NCBITaxon": NCBITaxonProvider,
        "WBStrain": WBStrainProvider,
        "SNOMED": SNOMEDProvider,
        "RRID": RRIDProvider,
        "EFO": EFOProvider,
        "PATO": PATOProvider,
        "PubChem": PubChemProvider,
        "EMPTY": EMPTYProvider,
    }
)
