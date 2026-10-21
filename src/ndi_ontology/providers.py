"""
ndi_ontology.providers - Ontology provider implementations.

MATLAB equivalents: ndi-ontology-matlab src/ndi/+ndi/+ontology/*.m

Each provider subclasses OntologyProvider and implements lookup_term().
"""

from __future__ import annotations

import csv
import re
import warnings
from typing import Any
from urllib.parse import quote
from xml.sax.saxutils import escape

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
    """Provider backed by the EBI OLS4 API.

    MATLAB equivalent: the shared static helpers in +ndi/ontology.m that every
    OLS-backed class (CL.m, CHEBI.m, PATO.m, ...) defers to after setting its
    ontology_prefix and ontology_name_ols: preprocessLookupInput,
    searchOLSAndPerformIRILookup and performIriLookup, ported here under
    MATLAB's names.

    The lookup is two requests, as in MATLAB: an OLS search that must name
    exactly one term, then that term's own record from OLS's term API, which
    is where the id, name, definition and synonyms are read. "Not found" is an
    empty result; anything else MATLAB raises for -- an ambiguous match, a
    transport failure -- raises here too.
    """

    ols_ontology: str = ""
    ols_prefix: str = ""

    OLS_SEARCH_URL = "https://www.ebi.ac.uk/ols4/api/search"
    OLS_ONTOLOGIES_URL = "https://www.ebi.ac.uk/ols4/api/ontologies/"

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        search_query, search_field, lookup_type_msg = OLSProvider.preprocessLookupInput(
            term, self.ols_prefix
        )
        return self.searchOLSAndPerformIRILookup(
            search_query, search_field, self.ols_ontology, self.ols_prefix, lookup_type_msg
        )

    @staticmethod
    @pydantic.validate_call
    def preprocessLookupInput(
        term_or_id_or_name: str, ontology_prefix: str
    ) -> tuple[str, str, str]:
        """Decide whether TERM is an id or a name and build the OLS query.

        MATLAB: ndi.ontology.preprocessLookupInput. Returns (search_query,
        search_field, lookup_type_msg); MATLAB's fourth output, the original
        input, is the caller's own argument and is not repeated.

        A numeric id is sent as ``PREFIX:id``, unpadded, against the exact
        ``obo_id`` field; anything else is a ``label`` search. A remainder that
        repeats the prefix (``CL:0000540`` given to CL) is unwrapped. OM takes
        its own branch: numeric ids are rejected and the term is turned into a
        label by the camel-case heuristic ('MolarVolumeUnit' -> 'molar volume
        unit').
        """
        if not term_or_id_or_name:
            raise ValueError("an ontology term or id cannot be empty")
        original = term_or_id_or_name
        processed = original.strip()
        prefix_with_colon = ontology_prefix + ":"
        has_prefix = processed.lower().startswith(prefix_with_colon.lower())
        remainder = processed[len(prefix_with_colon) :].strip() if has_prefix else processed

        if ontology_prefix.lower() == "om":
            if re.fullmatch(r"\d+", remainder):
                kind = "prefixed numeric ID" if has_prefix else "purely numeric ID"
                raise ValueError(f'Lookup by {kind} ("{original}") is not supported for OM.')
            if has_prefix and not remainder:
                raise ValueError(
                    f'Input "{original}" has prefix "{prefix_with_colon}" but is missing '
                    f"term component."
                )
            label = OLSProvider.convertComponentToLabel_OMHeuristic(remainder)
            if not label:
                raise ValueError(
                    f'Derived empty search label from OM term component "{remainder}".'
                )
            return label, "label", f'input "{original}" (searching label as "{label}")'

        if has_prefix and not remainder:
            raise ValueError(
                f'Input "{original}" has prefix "{prefix_with_colon}" but is missing term/ID.'
            )
        if re.fullmatch(r"\d+", remainder):
            kind = "prefixed ID" if has_prefix else "numeric ID"
            return f"{ontology_prefix}:{remainder}", "obo_id", f'{kind} "{original}"'
        kind = "prefixed name" if has_prefix else "name"
        return remainder, "label", f'{kind} "{original}"'

    @staticmethod
    @pydantic.validate_call
    def convertComponentToLabel_OMHeuristic(comp: str) -> str:
        """MATLAB: ndi.ontology.convertComponentToLabel_OMHeuristic."""
        return re.sub(r"([a-z])([A-Z])", r"\1 \2", comp).strip().lower()

    def searchOLSAndPerformIRILookup(
        self,
        search_query: str,
        search_field: str,
        ontology_name_ols: str,
        ontology_prefix: str,
        lookup_type_msg: str,
    ) -> Any:
        """Search OLS for exactly one term, then read it by its IRI.

        MATLAB: ndi.ontology.searchOLSAndPerformIRILookup. An id search must
        return exactly one result. A label search must name exactly one
        result whose label equals the query ignoring case; when OLS returns a
        single result, its label must match too.

        No match is an empty result, which lookup() raises on; more than one
        match raises, as MATLAB does, rather than picking the first.
        """
        from . import OntologyResult

        if search_field not in ("obo_id", "label"):
            raise ValueError(f"search_field must be 'obo_id' or 'label', not {search_field!r}")
        params: dict[str, Any] = {
            "q": search_query,
            "ontology": ontology_name_ols,
            "queryFields": search_field,
        }
        if search_field == "obo_id":
            params["exact"] = "true"

        data = self._http_get_json(OLSProvider.OLS_SEARCH_URL, params=params)
        response = data.get("response") if isinstance(data, dict) else None
        if not isinstance(response, dict) or "numFound" not in response:
            raise ValueError(
                f"Invalid search response structure from OLS for {lookup_type_msg} "
                f'in "{ontology_name_ols}".'
            )
        num_found = response["numFound"]
        docs = response.get("docs") or []

        if num_found == 0:
            return OntologyResult()
        if num_found == 1:
            doc = docs[0] if docs else {}
            if search_field == "label" and doc.get("label", "").lower() != search_query.lower():
                # MATLAB: MismatchOnSingleResult -- the one hit is not this term
                return OntologyResult()
        elif search_field == "label":
            matches = [d for d in docs if d.get("label", "").lower() == search_query.lower()]
            if not matches:
                return OntologyResult()
            if len(matches) > 1:
                raise ValueError(
                    f"Term matching {lookup_type_msg} resulted in {len(matches)} exact matches "
                    f'(case-insensitive) in "{ontology_name_ols}". Requires unique match.'
                )
            doc = matches[0]
        else:
            raise ValueError(
                f"Term matching {lookup_type_msg} yielded {num_found} results in "
                f'"{ontology_name_ols}" (expected 1 for ID search).'
            )

        term_iri = doc.get("iri") or ""
        if not term_iri:
            raise ValueError(f"Found unique term for {lookup_type_msg}, but could not extract IRI.")
        return self.performIriLookup(term_iri, ontology_name_ols, ontology_prefix)

    def performIriLookup(self, term_iri: str, ontology_name_ols: str, ontology_prefix: str) -> Any:
        """Read one term's record from OLS's term API by its IRI.

        MATLAB: ndi.ontology.performIriLookup. The IRI is URL-encoded twice,
        as OLS requires. The id is the record's obo_id when it carries this
        ontology's prefix, else is built from short_form, else falls back to
        the raw obo_id (EDAM's sub-namespaces); the definition is the first
        non-empty description; the synonyms are the obo_synonym names.
        """
        from . import OntologyResult

        encoded = quote(quote(term_iri, safe=""), safe="")
        data = self._http_get_json(
            f"{OLSProvider.OLS_ONTOLOGIES_URL}{ontology_name_ols}/terms/{encoded}"
        )
        if not isinstance(data, dict) or not data:
            raise ValueError(
                f"Received invalid/empty response from OLS Term API for ontology "
                f'"{ontology_name_ols}", IRI "{term_iri}".'
            )

        lower_prefix = ontology_prefix.lower()
        obo_id = data.get("obo_id") or ""
        short_form = data.get("short_form") or ""
        if obo_id and obo_id.lower().startswith(lower_prefix + ":"):
            id_ = obo_id
        elif short_form:
            if short_form.lower().startswith(lower_prefix + "_"):
                id_ = short_form.replace("_", ":")
            elif re.fullmatch(r"\d+", short_form):
                id_ = f"{ontology_prefix}:{short_form}"
            elif short_form.lower().startswith(lower_prefix + ":"):
                id_ = short_form
            else:
                id_ = ""
        else:
            id_ = ""
        if not id_ and obo_id:
            id_ = obo_id
        if not id_:
            warnings.warn(
                f"Could not extract valid ID (e.g., {ontology_prefix}:123) from OLS response "
                f'for ontology "{ontology_name_ols}", IRI "{term_iri}".',
                stacklevel=2,
            )

        name = data.get("label") or ""
        if not name:
            warnings.warn(
                f'Field "label" not found/empty for ontology "{ontology_name_ols}", '
                f'IRI "{term_iri}".',
                stacklevel=2,
            )

        description = data.get("description")
        definition = ""
        if isinstance(description, list):
            definition = next((d for d in description if d), "")

        synonyms: list[str] = []
        obo_synonym = data.get("obo_synonym")
        if isinstance(obo_synonym, list) and obo_synonym and isinstance(obo_synonym[0], dict):
            key = (
                "name" if "name" in obo_synonym[0] else "label" if "label" in obo_synonym[0] else ""
            )
            if key:
                synonyms = [str(x.get(key) or "") for x in obo_synonym if x.get(key)]

        return OntologyResult(
            id=id_,
            name=name,
            prefix=ontology_prefix,
            definition=definition,
            synonyms=synonyms,
        )


# ---------------------------------------------------------------------------
# Individual providers
# ---------------------------------------------------------------------------


class CLProvider(OLSProvider):
    name = "CL"
    ols_ontology = "cl"
    ols_prefix = "CL"


class OMProvider(OLSProvider):
    """Ontology of Units of Measure.

    MATLAB equivalent: +ndi/+ontology/OM.m

    OM's units are INDIVIDUALS (``om:metre`` is an om:Unit, not a class), and
    the EBI OLS index holds only OM's classes, so a unit cannot be found there
    at all. lookup_term therefore reads OM's own file first (fileIndex,
    downloaded once per process) and only when that file cannot be read, or
    holds no match, falls back to the OLS label search, which finds classes
    such as ``MolarVolumeUnit``.
    """

    name = "OM"
    ols_ontology = "om"
    ols_prefix = "OM"

    #: OM's own file, the source of its units (individuals, not classes)
    RDF_URL = "https://raw.githubusercontent.com/HajoRijgersberg/OM/master/om-2.0.rdf"

    _file_index: dict[str, list] | None = None

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        # --- Step 0: OM's own file (units are individuals; OLS lacks them) ---
        stripped = term.strip()
        if not re.fullmatch(r"\d+", stripped):
            idx = None
            try:
                idx = OMProvider.fileIndex()
            except Exception as exc:
                warnings.warn(
                    f"Could not read OM's file ({exc}); falling back to OLS.",
                    stacklevel=2,
                )
            if idx:
                k = OMProvider.findInIndex(idx, stripped)
                if k is not None:
                    return OntologyResult(
                        id=f"OM:{idx['local'][k]}",
                        name=idx["label"][k],
                        prefix=prefix or "OM",
                        definition=idx["definition"][k],
                        synonyms=list(idx["alternative"][k]),
                    )

        # --- Steps 1-2: the shared OLS path (finds OM's classes) ---
        # preprocessLookupInput's OM branch rejects numeric ids and turns the
        # term into a label by the camel-case heuristic.
        return super().lookup_term(term, prefix)

    @staticmethod
    @pydantic.validate_call
    def fileIndex(reset: bool = False) -> dict[str, list] | None:
        """OM's entries, read from OM's own file once per process.

        ``OMProvider.fileIndex()`` downloads RDF_URL on first use and returns
        its index (see parseRDF). ``OMProvider.fileIndex(True)`` forgets it,
        so the next call downloads again. A failed download raises and caches
        nothing, as MATLAB's persistent stays empty when webread throws.
        """
        if reset:
            OMProvider._file_index = None
            return None
        if OMProvider._file_index is None:
            import requests

            resp = requests.get(OMProvider.RDF_URL, timeout=60)
            resp.raise_for_status()
            OMProvider._file_index = OMProvider.parseRDF(resp.text)
        return OMProvider._file_index

    @staticmethod
    @pydantic.validate_call
    def parseRDF(txt: str) -> dict[str, list]:
        """Index every top-level entry of OM's RDF/XML file.

        Returns a dict of parallel lists, one element per OM identifier:
        ``local`` (the part after om-2/, e.g. 'metre', 'second-Time',
        'Temperature'), ``label`` (the English rdfs:label), ``definition`` (the
        English rdfs:comment), ``alternative`` (English om:alternativeLabel
        values) and ``kind`` (the element, e.g. 'om:Unit', 'om:UnitDivision',
        'owl:Class'). OM states one identifier in several top-level blocks
        (labels in one, the comment in another); they are merged.
        """
        local: list[str] = []
        label: list[str] = []
        definition: list[str] = []
        alternative: list[list[str]] = []
        kind: list[str] = []
        where: dict[str, int] = {}
        # MATLAB's '.' matches newlines and 'lineanchors' makes '^' per-line
        blocks = re.finditer(
            r'^  <([\w:]+) rdf:about="&om;([^"]+)">(.*?)^  </\1>', txt, re.M | re.S
        )
        for block in blocks:
            tag, loc, body = block.group(1), block.group(2), block.group(3)
            if loc in where:
                k = where[loc]
            else:
                k = len(local)
                where[loc] = k
                local.append(loc)
                label.append("")
                definition.append("")
                alternative.append([])
                kind.append(tag)
            en = re.search(r'<rdfs:label xml:lang="en">([^<]+)</rdfs:label>', body)
            if not label[k] and en:
                label[k] = en.group(1).strip()
            c = re.search(r'<rdfs:comment xml:lang="en">([^<]+)</rdfs:comment>', body)
            if not definition[k] and c:
                definition[k] = c.group(1).strip()
            alt = re.findall(
                r'<om:alternativeLabel xml:lang="en">([^<]+)</om:alternativeLabel>', body
            )
            alternative[k] = list(dict.fromkeys(alternative[k] + [a.strip() for a in alt]))
        return {
            "local": local,
            "label": label,
            "definition": definition,
            "alternative": alternative,
            "kind": kind,
        }

    @staticmethod
    @pydantic.validate_call
    def findInIndex(idx: dict[str, list], term: str) -> int | None:
        """The one entry TERM names (0-based), or None if none or several.

        Tried in order, the first rule that names exactly one entry wins: the
        identifier as written; the identifier ignoring case; the English label
        ignoring case; an English alternative label ignoring case; the
        camel-case heuristic ('MetrePerSecond' -> 'metre per second') against
        the labels.
        """
        term = term.strip()
        if not term:
            return None
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", term).strip().lower()
        low = term.lower()
        rules = (
            lambda: [i for i, x in enumerate(idx["local"]) if x == term],
            lambda: [i for i, x in enumerate(idx["local"]) if x.lower() == low],
            lambda: [i for i, x in enumerate(idx["label"]) if x.lower() == low],
            lambda: [
                i for i, a in enumerate(idx["alternative"]) if any(x.lower() == low for x in a)
            ],
            lambda: [i for i, x in enumerate(idx["label"]) if x.lower() == spaced],
        )
        for rule in rules:
            hit = rule()
            if len(hit) == 1:
                return hit[0]
        return None


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
    """NCI Metathesaurus, read from the NCI EVS REST API.

    MATLAB equivalent: +ndi/+ontology/NCIm.m

    A CUI (C followed by seven digits) is read directly. A name must be an
    exact match for exactly one concept, which is then read by its CUI; more
    than one match raises, as in MATLAB, rather than picking the first.
    """

    name = "NCIm"
    _CUI_PATTERN = re.compile(r"^C\d{7}$")
    SEARCH_URL = "https://api-evsrest.nci.nih.gov/api/v1/concept/search"
    CONCEPT_URL = "https://api-evsrest.nci.nih.gov/api/v1/concept/ncim/"

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        if self._CUI_PATTERN.match(term):
            try:
                return self.performNcimIdLookup(term)
            except Exception as exc:
                if _is_404(exc):
                    # MATLAB: ndi:ontology:NCIm:CUINotFound
                    return OntologyResult()
                raise

        data = self._http_get_json(
            NCImProvider.SEARCH_URL,
            params={"term": term, "terminology": "ncim", "type": "match", "include": "minimal"},
        )
        if not isinstance(data, dict) or "total" not in data:
            raise ValueError(f'Invalid search response for "{term}".')
        total = data["total"]
        if total == 0:
            return OntologyResult()
        if total > 1:
            raise ValueError(f'"{term}" had {total} exact matches.')
        concepts = data.get("concepts")
        if not isinstance(concepts, list) or len(concepts) != 1:
            raise ValueError(f'API reported 1 result for "{term}", but concept data invalid.')
        code = concepts[0].get("code") or ""
        if not code:
            raise ValueError(f'Found "{term}", missing Code.')
        if not self._CUI_PATTERN.match(code):
            raise ValueError(f'Found "{term}", Code "{code}" invalid format.')
        return self.performNcimIdLookup(code)

    def performNcimIdLookup(self, cui: str) -> Any:
        """Read one concept by CUI. MATLAB: NCIm.performNcimIdLookup.

        The id is always the CUI asked for, as in MATLAB; a record whose code
        differs warns and keeps the CUI.
        """
        from . import OntologyResult

        if not cui:
            raise ValueError("a CUI cannot be empty")
        data = self._http_get_json(
            f"{NCImProvider.CONCEPT_URL}{quote(cui, safe='')}", params={"include": "full"}
        )
        if not isinstance(data, dict) or not data:
            raise ValueError(f'Received invalid response from EVS Concept API for CUI "{cui}".')
        code = data.get("code") or cui
        if code != cui:
            warnings.warn(f'Code "{code}"!= CUI "{cui}".', stacklevel=2)
        definitions = data.get("definitions")
        definition = ""
        if isinstance(definitions, list) and definitions and isinstance(definitions[0], dict):
            definition = definitions[0].get("definition") or ""
        synonyms: list[str] = []
        syns = data.get("synonyms")
        if isinstance(syns, list) and syns and isinstance(syns[0], dict) and "name" in syns[0]:
            synonyms = [str(x.get("name") or "") for x in syns if x.get("name")]
        return OntologyResult(
            # Bare concept code, no "NCIm:" prefix, as MATLAB returns it.
            id=cui,
            name=data.get("name") or "",
            prefix="NCIm",
            definition=definition,
            synonyms=synonyms,
        )


class NCBITaxonProvider(OntologyProvider):
    """NCBI Taxonomy, read from NCBI E-utilities.

    MATLAB equivalent: +ndi/+ontology/NCBITaxon.m

    A TaxID is fetched directly; a scientific name is searched first. "Not
    found" is an empty result; anything else MATLAB raises for -- an HTTP
    error, an unexpected response -- raises here too.
    """

    name = "NCBITaxon"

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        if re.fullmatch(r"\d+", term):
            return self._lookup_taxid(term)
        return self._search_name(term)

    def _lookup_taxid(self, taxid: str) -> Any:
        import defusedxml.ElementTree as ET
        import requests

        from . import OntologyResult

        resp = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db": "taxonomy", "id": taxid, "retmode": "xml"},
            timeout=30,
        )
        resp.raise_for_status()
        # MATLAB: IDNotFound when efetch reports an error or holds no <Taxon>
        if not resp.text or "<Error>" in resp.text or "<Taxon>" not in resp.text:
            return OntologyResult()
        root = ET.fromstring(resp.text)
        taxon = root.find(".//Taxon")
        if taxon is None:
            return OntologyResult()

        name = taxon.findtext("ScientificName", "")

        return OntologyResult(
            id=f"NCBITaxon:{taxid}",
            name=name,
            prefix="NCBITaxon",
            synonyms=self.parseOtherNames(resp.text),
        )

    # The kinds of <Name> entry that name the same taxon. MATLAB: keptKinds in
    # NCBITaxon.parseOtherNames.
    _KEPT_KINDS = (
        "genbank common name",
        "common name",
        "synonym",
        "genbank synonym",
        "equivalent name",
        "acronym",
        "genbank acronym",
    )

    @staticmethod
    @pydantic.validate_call
    def parseOtherNames(xml_response: str) -> list[str]:
        """The other names of a taxon in an efetch record.

        MATLAB equivalent: ndi.ontology.NCBITaxon.parseOtherNames

        Reads the first ``<OtherNames>`` block of an E-utilities efetch taxonomy
        record and returns its names in the order they appear, without
        duplicates. NCBI tags each name with its kind, either as its own element
        (``<GenbankCommonName>house mouse</GenbankCommonName>``) or as a
        ``<Name>`` entry with a ``<ClassCDE>`` and a ``<DispName>``. The kinds
        kept are those naming the same taxon: common names, synonyms (such as a
        former genus, 'Rhabditis elegans'), equivalent names and acronyms.
        Authority citations ('Mus musculus Linnaeus, 1758'), misspellings, and
        ``<Includes>`` (narrower groups such as 'nude mice') are left out.
        Public so the parsing can be tested without the network.

        Regular expressions rather than an XML parser, as MATLAB does, so the
        two read the same record the same way.
        """
        block = re.search(r"<OtherNames>(.*?)</OtherNames>", xml_response, re.S)
        if block is None:
            return []
        block_text = block.group(1)
        # <Name> entries carry their kind in <ClassCDE>
        entry_names = []
        for entry in re.findall(r"<Name>(.*?)</Name>", block_text, re.S):
            kind = re.search(r"<ClassCDE>(.*?)</ClassCDE>", entry, re.S)
            disp_name = re.search(r"<DispName>(.*?)</DispName>", entry, re.S)
            if (
                kind is not None
                and disp_name is not None
                and kind.group(1).strip().lower() in NCBITaxonProvider._KEPT_KINDS
            ):
                entry_names.append(disp_name.group(1))
        # the elements named by their kind, outside the <Name> entries
        block_text = re.sub(r"<Name>.*?</Name>", "", block_text, flags=re.S)
        tagged = re.findall(
            r"<(GenbankCommonName|CommonName|Synonym|GenbankSynonym|"
            r"EquivalentName|Acronym|GenbankAcronym)>(.*?)</\1>",
            block_text,
            re.S,
        )
        names = [_unescape_xml(n).strip() for _, n in tagged] + [
            _unescape_xml(n).strip() for n in entry_names
        ]
        return list(dict.fromkeys(n for n in names if n))

    def _search_name(self, name: str) -> Any:
        import defusedxml.ElementTree as ET
        import requests

        from . import OntologyResult

        resp = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db": "taxonomy", "term": f"{name}[Scientific Name]", "retmode": "xml"},
            timeout=30,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        # MATLAB's regex spans the whole <IdList>, so it captures only the
        # first <Id> and its NameNotUnique branch cannot fire; taking the
        # first id is therefore the parity behaviour, not a shortcut.
        id_list = root.findall(".//IdList/Id")
        if not id_list:
            if any(m in resp.text for m in ("<ErrorList>", "<PhraseNotFound>", "<Count>0</Count>")):
                return OntologyResult()  # MATLAB: NameNotFound
            raise ValueError(f'Unexpected/empty esearch response for name "{name}".')
        found = self._lookup_taxid(id_list[0].text or "")
        if not found:
            # MATLAB: PostSearchLookupFailed -- a TaxID the search returned
            # that efetch cannot read is an error, not "not found".
            raise ValueError(
                f'Found name "{name}" (TaxID: {id_list[0].text}), but failed subsequent '
                f"efetch lookup."
            )
        return found


class WormBaseProvider(OntologyProvider):
    """WormBase strains, read from WormMine.

    MATLAB equivalent: ndi-ontology-matlab src/ndi/+ndi/+ontology/WormBase.m

    Serves the ``WBStrain`` and ``wormbase`` prefixes. Strains are read from
    WormMine, the Alliance of Genome Resources' InterMine copy of WormBase
    (https://wormmine.alliancegenome.org). The WormBase site and REST API
    (wormbase.org, rest.wormbase.org) answer programmatic requests with a
    Cloudflare browser challenge (HTTP 403), so every lookup through them
    failed.
    """

    name = "WormBase"

    SERVICE_URL = "https://wormmine.alliancegenome.org/wormmine/service/query/results"
    _ID_PREFIX = "WBStrain"
    _VIEW = (
        "Strain.primaryIdentifier Strain.name Strain.genotype "
        "Strain.otherName Strain.mutagen Strain.outcrossed"
    )

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        """Look up a strain in WormBase by its ID or public name.

        ``term`` is the part after the prefix:

        - ``WBStrain:00000001`` -- an eight-digit ID
        - ``WBStrain:N2`` -- a strain name, matched ignoring case
        - ``wormbase:WBStrain00000001`` -- the Bioregistry CURIE (prefix
          ``wormbase``; Bioregistry has no ``wbstrain``)

        The id is in the form asked for: ``WBStrain:00000001`` for the first
        two, ``wormbase:WBStrain00000001`` for the third. The name is the strain
        name, the definition its genotype, mutagen and outcrossing, and the
        synonyms its other name, if it has one.

        No strain found is an empty result, which lookup() raises on. Every
        other failure MATLAB raises for raises here too.
        """
        from . import OntologyResult

        id_prefix = self._ID_PREFIX
        term = term.strip()
        if "*" in term:
            raise ValueError(f'A strain name or ID cannot contain "*" ("{term}").')
        is_curie = re.fullmatch(rf"{id_prefix}\d{{8}}", term) is not None
        if is_curie:
            term = term[len(id_prefix) :]
        elif re.fullmatch(r"CE\d{5}|WB[A-Z][a-z]+\d+", term):
            # another kind of WormBase id, such as a gene (WBGene00000001)
            raise ValueError(
                f'"{term}" is a WormBase id but not a strain id '
                f"(WBStrain followed by eight digits)."
            )
        is_id_lookup = re.fullmatch(r"\d{8}", term) is not None
        if is_id_lookup:
            path, value = "Strain.primaryIdentifier", id_prefix + term
        else:
            path, value = "Strain.name", term

        strains = self.queryWormMine(path, value)
        if not strains:
            return OntologyResult()
        if len(strains) > 1:
            raise ValueError(
                f'{len(strains)} WormBase strains match "{term}"; use the WBStrain ID instead.'
            )

        id_, name, definition, synonyms = self.parseStrain(strains[0])
        if is_curie:
            id_ = "wormbase:" + id_.replace(":", "")
        if not is_id_lookup and name.lower() != term.lower():
            raise ValueError(
                f'WormMine returned strain "{name}" for the name "{term}". '
                f"Try the WBStrain ID instead."
            )
        return OntologyResult(
            id=id_,
            name=name,
            prefix=prefix or id_prefix,
            definition=definition,
            synonyms=synonyms,
        )

    @staticmethod
    @pydantic.validate_call
    def parseStrain(strain: dict) -> tuple[str, str, str, list[str]]:
        """The lookup outputs for one WormMine strain record.

        MATLAB equivalent: ndi.ontology.WormBase.parseStrain

        ``strain`` is one record of a WormMine ``jsonobjects`` query: a dict
        with keys primaryIdentifier, name, genotype, otherName, mutagen and
        outcrossed, any of which may be missing or None. Returns
        ``(id, name, definition, synonyms)``. Public so the parsing can be
        tested without the network.

        Raises:
            ValueError: the record has no valid WBStrain ID, or no name.
        """
        id_prefix = WormBaseProvider._ID_PREFIX

        def field(key: str) -> str:
            value = strain.get(key)
            return "" if value is None else str(value).strip()

        wb_id = field("primaryIdentifier")
        if not re.fullmatch(rf"{id_prefix}\d{{8}}", wb_id):
            raise ValueError(f'WormMine returned a strain without a valid WBStrain ID ("{wb_id}").')
        id_ = f"{id_prefix}:{wb_id[len(id_prefix):]}"

        name = field("name")
        if not name:
            raise ValueError(f"WormMine returned strain {id_} without a name.")

        parts = []
        if field("genotype"):
            parts.append("Genotype: " + field("genotype"))
        if field("mutagen"):
            parts.append("Mutagen: " + field("mutagen"))
        if field("outcrossed"):
            parts.append("Outcrossed: " + field("outcrossed"))
        definition = ". ".join(parts).replace("..", ".")
        if definition and not definition.endswith("."):
            definition += "."

        synonyms = [field("otherName")] if field("otherName") else []
        return id_, name, definition, synonyms

    def queryWormMine(self, path: str, value: str) -> list[dict]:
        """The WormMine strain records whose ``path`` equals ``value``.

        MATLAB equivalent: ndi.ontology.WormBase.queryWormMine (private there)
        """
        query = (
            f'<query model="genomic" view="{self._VIEW}">'
            f'<constraint path="{path}" op="=" value="{escape(value, {chr(34): "&quot;"})}"/>'
            f"</query>"
        )
        response = self._http_get_json(
            self.SERVICE_URL, params={"query": query, "format": "jsonobjects"}
        )
        if not isinstance(response, dict) or "results" not in response:
            raise ValueError("WormMine returned an unexpected response.")
        if response.get("wasSuccessful") is False:
            raise ValueError(f"WormMine reported an error: {response.get('error')}")
        return list(response["results"] or [])


class RRIDProvider(OntologyProvider):
    """Research Resource Identifiers, read from the SciCrunch resolver.

    MATLAB equivalent: +ndi/+ontology/RRID.m
    """

    name = "RRID"
    RESOLVER_URL = "https://scicrunch.org/resolver/"

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        id_, name, definition, synonyms, _, _ = self.performRridResolverLookup(
            "RRID:" + term.strip()
        )
        if not id_:
            return OntologyResult()
        return OntologyResult(
            id=id_, name=name, prefix="RRID", definition=definition, synonyms=synonyms
        )

    @pydantic.validate_call
    def lookupSpecies(self, term_or_id_or_name: str) -> tuple[str | list[str], str]:
        """The species an RRID resource is from: (scientificName, commonName).

        MATLAB: RRID.lookupSpecies. scientificName is a list when the record
        lists several species (MATLAB returns a cell array); either is empty
        when the record does not say.
        """
        _, _, _, _, scientific_name, common_name = self.performRridResolverLookup(
            "RRID:" + term_or_id_or_name.strip()
        )
        return scientific_name, common_name

    def performRridResolverLookup(
        self, full_rrid: str
    ) -> tuple[str, str, str, list[str], str | list[str], str]:
        """Resolve FULL_RRID. MATLAB: RRID.performRridResolverLookup.

        Returns (id, name, definition, synonyms, scientificName, commonName),
        all empty when the resolver has no hit. Errors propagate, as MATLAB's
        rethrow does.
        """
        id_, name, definition = "", "", ""
        synonyms: list[str] = []
        scientific_name: str | list[str] = ""
        common_name = ""
        response = self._http_get_json(
            f"{RRIDProvider.RESOLVER_URL}{quote(full_rrid, safe='')}.json"
        )
        hits = (response.get("hits") or {}).get("hits") if isinstance(response, dict) else None
        if not hits:
            return id_, name, definition, synonyms, scientific_name, common_name

        source = hits[0].get("_source") or {}
        item = source.get("item") or {}
        id_ = full_rrid
        name = str(item.get("name") or "")
        definition = str(item.get("description") or "")

        primary = (source.get("organisms") or {}).get("primary")
        if primary:
            info = primary[0] if isinstance(primary, list) else primary
            scientific_name = str((info.get("species") or {}).get("name") or "")
            common_name = str((info.get("common") or {}).get("name") or "")
        elif item.get("species"):
            species = item["species"]
            scientific_name = (
                [str(x) for x in species] if isinstance(species, list) else str(species)
            )

        syn = item.get("synonyms")
        if isinstance(syn, list):
            synonyms = [str(x.get("name") or "") if isinstance(x, dict) else str(x) for x in syn]
        elif isinstance(syn, dict) and "name" in syn:
            synonyms = [str(syn["name"])]
        return id_, name, definition, synonyms, scientific_name, common_name


class PubChemProvider(OntologyProvider):
    """PubChem compounds, read from the PUG REST API.

    MATLAB equivalent: +ndi/+ontology/PubChem.m

    A CID is given bare ('2244') or after 'cid' ('cid 2244'); anything else
    is a name, which must name exactly one CID.
    """

    name = "PubChem"
    PUG_REST_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        processed = term.strip()
        if processed.lower().startswith("cid"):
            cid = processed[3:].strip()
            if not re.fullmatch(r"\d+", cid):
                # MATLAB: InvalidCidPrefixFormat. 'cid:2244' lands here too,
                # as it does in MATLAB.
                raise ValueError(
                    f'Input remainder "{term}" starts with "cid" but is not followed by a '
                    f"valid numeric ID."
                )
        elif re.fullmatch(r"\d+", processed):
            cid = processed
        else:
            cid = ""

        if cid:
            try:
                return self.performPubChemCidLookup(cid)
            except LookupError:
                # MATLAB: ndi:ontology:PubChem:CIDNotFound
                return OntologyResult()

        try:
            data = self._http_get_json(
                f"{PubChemProvider.PUG_REST_BASE}/compound/name/"
                f"{quote(processed, safe='')}/cids/JSON"
            )
        except Exception as exc:
            if _is_404(exc):
                return OntologyResult()  # MATLAB: NameNotFound
            raise
        cids = (data.get("IdentifierList") or {}).get("CID") if isinstance(data, dict) else None
        if not cids:
            return OntologyResult()
        if len(cids) > 1:
            raise ValueError(
                f'Name "{processed}" matched multiple ({len(cids)}) CIDs. Requires unique '
                f"exact match or CID."
            )
        # A CID found by search that then cannot be read is an error, not a
        # "not found" (MATLAB: PostSearchLookupFailed).
        return self.performPubChemCidLookup(str(cids[0]))

    def performPubChemCidLookup(self, cid: str) -> Any:
        """Read one compound. MATLAB: PubChem.performPubChemCidLookup.

        Title, description and synonyms are three requests, each allowed to
        fail with a warning, as in MATLAB. The name falls back to the first
        synonym. Raises LookupError (MATLAB: IDNotFound) only when a request
        404'd and nothing at all came back.
        """
        from . import OntologyResult

        if not cid:
            raise ValueError("a CID cannot be empty")
        base = f"{PubChemProvider.PUG_REST_BASE}/compound/cid/{cid}"
        api_error = False

        def fetch(what: str, url: str) -> Any:
            nonlocal api_error
            try:
                return self._http_get_json(url)
            except Exception as exc:
                warnings.warn(f"Could not fetch {what} for CID {cid}: {exc}", stacklevel=3)
                if _is_404(exc):
                    api_error = True
                return None

        name = ""
        data = fetch("Title", f"{base}/property/Title/JSON")
        if isinstance(data, dict):
            props = (data.get("PropertyTable") or {}).get("Properties")
            if props and isinstance(props[0], dict):
                name = str(props[0].get("Title") or "")

        definition = ""
        data = fetch("description", f"{base}/description/JSON")
        if isinstance(data, dict):
            info = (data.get("InformationList") or {}).get("Information")
            if info and isinstance(info[0], dict):
                definition = str(info[0].get("Description") or "")

        synonyms: list[str] = []
        data = fetch("synonyms", f"{base}/synonyms/JSON")
        if isinstance(data, dict):
            info = (data.get("InformationList") or {}).get("Information")
            if info and isinstance(info[0], dict):
                raw = info[0].get("Synonym")
                if isinstance(raw, list):
                    synonyms = [str(x) for x in raw if x]
                elif isinstance(raw, str) and raw:
                    synonyms = [raw]

        if not name and synonyms:
            name = synonyms[0]
            warnings.warn(
                f'Title not found for CID {cid}. Using first synonym "{name}".', stacklevel=2
            )
        elif not name:
            warnings.warn(f"Could not determine name for CID {cid}.", stacklevel=2)
        if api_error and not (name or definition or synonyms):
            raise LookupError(f"Could not retrieve any data for PubChem CID {cid}.")

        return OntologyResult(
            # Bare CID, no "PubChem:" prefix, as MATLAB returns it.
            id=cid,
            name=name,
            prefix="PubChem",
            definition=definition,
            synonyms=synonyms,
        )


class EMPTYProvider(OntologyProvider):
    """Experimental Measurements, Purposes, and Treatments ontologY (EMPTY).

    MATLAB equivalent: +ndi/+ontology/EMPTY.m

    Fetches the EMPTY ontology as JSON from the Waltham-Data-Science
    GitHub repository and caches it in memory. Supports lookup by
    numeric ID (e.g. ``"0000074"``), full OBO-style ID
    (e.g. ``"EMPTY_0000074"``), or label substring
    (e.g. ``"Optogenetic Tetanus Stimulation Target Location"``).
    """

    name = "EMPTY"

    _JSON_URL = (
        "https://raw.githubusercontent.com/Waltham-Data-Science/empty-ontology"
        "/main/empty-base.json"
    )

    # Class-level cache shared across instances
    _cache: dict[str, Any] | None = None

    def _load_ontology(self) -> dict[str, Any]:
        """Fetch and parse empty-base.json, caching in class variable.

        A failed download raises and caches nothing, so the next lookup tries
        again; lookup() turns the raise into NDIOntologyLookupError with the
        cause chained. This used to cache an empty index instead, which made
        one timeout or 429 a permanent "not found" for every EMPTY term for
        the life of the process, beyond the reach of clearCache() -- and it
        is how a 404'ing URL once hid behind three vacuously passing
        not-found cases. MATLAB's EMPTY.m caches nothing and downloads on
        every lookup; the cache here is a deliberate difference, kept because
        a failure can no longer be what it holds. clearCache() resets it.
        """
        if EMPTYProvider._cache is not None:
            return EMPTYProvider._cache

        data = self._http_get_json(self._JSON_URL, timeout=30)

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
# OLS-backed providers ported from ndi-ontology-matlab
# ---------------------------------------------------------------------------


class UberonProvider(OLSProvider):
    """Uberon multi-species anatomy.

    MATLAB equivalent: +ndi/+ontology/Uberon.m, which sets
    ontology_prefix = 'UBERON' and ontology_name_ols = 'uberon' and defers to
    the shared preprocessLookupInput / searchOLSAndPerformIRILookup helpers.
    """

    name = "Uberon"
    ols_ontology = "uberon"
    ols_prefix = "UBERON"


class NCITProvider(OLSProvider):
    """NCI Thesaurus.

    MATLAB equivalent: +ndi/+ontology/NCIT.m -- prefix 'NCIT', OLS id 'ncit'.
    """

    name = "NCIT"
    ols_ontology = "ncit"
    ols_prefix = "NCIT"


class STATOProvider(OLSProvider):
    """Statistics Ontology.

    MATLAB equivalent: +ndi/+ontology/STATO.m -- prefix 'STATO', OLS id 'stato'.
    """

    name = "STATO"
    ols_ontology = "stato"
    ols_prefix = "STATO"


class MICROProvider(OLSProvider):
    """MicrO, the Ontology of Prokaryotic Phenotypic and Metabolic Characters.

    MATLAB equivalent: +ndi/+ontology/MICRO.m -- prefix 'MICRO', OLS id 'micro'.
    Includes culture media components such as peptone (MICRO:0000178).
    """

    name = "MICRO"
    ols_ontology = "micro"
    ols_prefix = "MICRO"


class MCOProvider(OLSProvider):
    """Microbial Conditions Ontology.

    MATLAB equivalent: +ndi/+ontology/MCO.m -- prefix 'MCO', OLS id 'mco'.
    Describes the conditions of microbial cultures, such as OD600 (MCO:0000059).
    """

    name = "MCO"
    ols_ontology = "mco"
    ols_prefix = "MCO"


class OBIProvider(OLSProvider):
    """Ontology for Biomedical Investigations.

    MATLAB equivalent: +ndi/+ontology/OBI.m -- prefix 'OBI', OLS id 'obi'.
    """

    name = "OBI"
    ols_ontology = "obi"
    ols_prefix = "OBI"


class ZECOProvider(OLSProvider):
    """Zebrafish Experimental Conditions Ontology.

    MATLAB equivalent: +ndi/+ontology/ZECO.m -- prefix 'ZECO', OLS id 'zeco'.
    Its conditions are general, not zebrafish-specific, such as food
    availability (ZECO:0000113) and fasting (ZECO:0000114).
    """

    name = "ZECO"
    ols_ontology = "zeco"
    ols_prefix = "ZECO"


class WBlsProvider(OLSProvider):
    """C. elegans Development Ontology: WormBase's life stages.

    MATLAB equivalent: +ndi/+ontology/WBls.m -- prefix 'WBls', OLS id 'wbls'.
    """

    name = "WBls"
    ols_ontology = "wbls"
    ols_prefix = "WBls"


# ---------------------------------------------------------------------------
# OWL-file providers
# ---------------------------------------------------------------------------


class _OWLTermProvider(OntologyProvider):
    """Shared machinery for providers that parse a downloaded OWL file.

    EDAM and IAO both fetch an OWL document, pull `owl:Class` blocks out of it
    with a regex, and index the results by numeric id and by lower-cased label.
    MATLAB implements each separately; the duplicated half is factored out here
    so the two subclasses carry only what actually differs between them --
    where the file comes from, how a local id maps to a numeric id, and which
    element holds the definition.

    The parse is regex-over-XML in both languages. That is not how one would
    choose to read OWL from scratch, but it is what MATLAB does, and a parser
    that accepted a different set of terms would be a divergence that the
    shared case table could not see.
    """

    #: URLs tried in order; the first that answers with a body wins.
    owl_urls: tuple[str, ...] = ()
    #: Prefix used to build the returned id, e.g. "EDAM" -> "EDAM:1929".
    id_prefix: str = ""

    _cache: dict[str, dict[str, Any]] | None = None

    @classmethod
    def _fetch_owl(cls) -> str:
        import requests

        for url in cls.owl_urls:
            try:
                resp = requests.get(url, timeout=60)
                if resp.status_code == 200 and resp.text:
                    return resp.text
            except Exception:
                continue
        return ""

    @classmethod
    def _class_blocks(cls, owl: str) -> list[tuple[str, str]]:
        """Override: yield (local_identifier, block_body) pairs."""
        raise NotImplementedError

    @classmethod
    def _numeric_id(cls, local_id: str) -> str:
        """Override: map a local identifier to its bare numeric id, or ''."""
        raise NotImplementedError

    @classmethod
    def _definition(cls, content: str) -> str:
        """Override: pull the definition out of a class block."""
        return ""

    @classmethod
    def _synonyms(cls, content: str) -> list[str]:
        return []

    @classmethod
    def _index(cls) -> dict[str, dict[str, Any]]:
        """Return {"by_id": ..., "by_name": ...}, downloading once per process."""
        if cls._cache is not None:
            return cls._cache

        owl = cls._fetch_owl()
        by_id: dict[str, dict[str, Any]] = {}
        by_name: dict[str, dict[str, Any]] = {}

        for local_id, content in cls._class_blocks(owl):
            numeric = cls._numeric_id(local_id)
            if not numeric:
                continue
            label_match = re.search(r"<rdfs:label[^>]*>(.*?)</rdfs:label>", content, re.S)
            label = _unescape_xml(label_match.group(1).strip()) if label_match else ""
            if not label:
                # Anonymous or unlabelled terms are skipped, as MATLAB does.
                continue
            term = {
                "id": f"{cls.id_prefix}:{numeric}",
                "numeric_id": numeric,
                "name": label,
                "definition": cls._definition(content),
                "synonyms": cls._synonyms(content),
            }
            by_id.setdefault(numeric, term)
            by_name.setdefault(label.lower(), term)

        cls._cache = {"by_id": by_id, "by_name": by_name}
        return cls._cache

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        index = self._index()
        term = term.strip()
        if re.match(r"^\d+$", term):
            found = index["by_id"].get(term)
        else:
            found = index["by_name"].get(term.lower())
        if not found:
            return OntologyResult(prefix=self.id_prefix)
        return OntologyResult(
            id=found["id"],
            name=found["name"],
            prefix=self.id_prefix,
            definition=found["definition"],
            synonyms=list(found["synonyms"]),
        )


def _is_404(exc: BaseException) -> bool:
    """Whether EXC is an HTTP 404, the error MATLAB's providers read as "not found"."""
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 404


def _unescape_xml(text: str) -> str:
    """The five predefined XML entities, matching MATLAB's unescapeXML."""
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


class EDAMProvider(_OWLTermProvider):
    """EDAM bioinformatics ontology.

    MATLAB equivalent: +ndi/+ontology/EDAM.m.

    EDAM IRIs carry a sub-namespace -- format_1929, data_1234, operation_0004,
    topic_0091 -- but the returned id drops it: MATLAB builds
    `[ONTOLOGY_PREFIX ':' numeric_id]`, so both `EDAM:1929` and `format:1929`
    resolve to `EDAM:1929`. The `format` prefix is an alias registered in
    ontology_list.json, not a separate ontology.
    """

    name = "EDAM"
    id_prefix = "EDAM"
    owl_urls = ("https://raw.githubusercontent.com/edamontology/edamontology/main/EDAM_dev.owl",)
    _IRI_BASE = "http://edamontology.org/"

    _cache: dict[str, dict[str, Any]] | None = None

    @classmethod
    def _class_blocks(cls, owl: str) -> list[tuple[str, str]]:
        pattern = (
            r'<owl:Class\s+rdf:about="' + re.escape(cls._IRI_BASE) + r'([^"]+)">(.*?)</owl:Class>'
        )
        return re.findall(pattern, owl, re.S)

    @classmethod
    def _numeric_id(cls, local_id: str) -> str:
        m = re.match(r"^(\w+)_(\d+)$", local_id)
        return m.group(2) if m else ""

    @classmethod
    def _definition(cls, content: str) -> str:
        m = re.search(
            r"<oboInOwl:hasDefinition[^>]*>.*?<rdfs:label[^>]*>(.*?)</rdfs:label>.*?"
            r"</oboInOwl:hasDefinition>",
            content,
            re.S,
        )
        if not m:
            m = re.search(r"<obo:IAO_0000115[^>]*>(.*?)</obo:IAO_0000115>", content, re.S)
        return _unescape_xml(m.group(1).strip()) if m else ""


class IAOProvider(_OWLTermProvider):
    """Information Artifact Ontology.

    MATLAB equivalent: +ndi/+ontology/IAO.m.

    Two URLs are tried in MATLAB's order. The obolibrary PURL is authoritative;
    the GitHub raw copy is the fallback, and is what answers when the PURL is
    unreachable.

    IAO terms appear both as `owl:Class` and as `rdf:Description` blocks; the
    latter are only taken when they carry an rdfs:label, matching MATLAB.
    """

    name = "IAO"
    id_prefix = "IAO"
    owl_urls = (
        "http://purl.obolibrary.org/obo/iao.owl",
        "https://raw.githubusercontent.com/information-artifact-ontology/IAO/master/iao.owl",
    )

    _cache: dict[str, dict[str, Any]] | None = None

    @classmethod
    def _class_blocks(cls, owl: str) -> list[tuple[str, str]]:
        blocks = re.findall(
            r"<owl:Class\s+rdf:about=['\"]([^'\"]*IAO_\d+[^'\"]*)['\"]\s*>(.*?)</owl:Class>",
            owl,
            re.S,
        )
        for about, content in re.findall(
            r"<rdf:Description\s+rdf:about=['\"]([^'\"]*IAO_\d+[^'\"]*)['\"]\s*>"
            r"(.*?)</rdf:Description>",
            owl,
            re.S,
        ):
            if "<rdfs:label" in content:
                blocks.append((about, content))
        return blocks

    @classmethod
    def _numeric_id(cls, local_id: str) -> str:
        m = re.search(r"IAO_(\d+)", local_id)
        return m.group(1) if m else ""

    @classmethod
    def _definition(cls, content: str) -> str:
        m = re.search(r"<obo:IAO_0000115[^>]*>(.*?)</obo:IAO_0000115>", content, re.S)
        return _unescape_xml(m.group(1).strip()) if m else ""

    @classmethod
    def _synonyms(cls, content: str) -> list[str]:
        return [
            _unescape_xml(t.strip())
            for t in re.findall(
                r"<oboInOwl:has(?:Exact|Related)Synonym[^>]*>(.*?)"
                r"</oboInOwl:has(?:Exact|Related)Synonym>",
                content,
                re.S,
            )
        ]


# ---------------------------------------------------------------------------
# schema.org
# ---------------------------------------------------------------------------


class SchemaOrgProvider(OntologyProvider):
    """Schema.org terms, via each term's own JSON-LD document.

    MATLAB equivalent: +ndi/+ontology/SchemaOrg.m.

    Not OLS-backed and not an OWL file: schema.org serves a JSON-LD document
    per term at https://schema.org/<Term>, whose @graph holds that term plus
    everything it references. The entry to read is the one whose @id matches
    the term, in either the compact form (`schema:Person`) or the full IRI
    (`https://schema.org/Person`) -- MATLAB checks for both, because the
    response uses them interchangeably.

    The id is the term as given, not a canonicalised form: MATLAB returns
    `['schema:' term_name]`. `name` falls back to the term itself when the
    document carries no rdfs:label, which is MATLAB's behaviour too.
    """

    name = "SchemaOrg"

    _BASE_URL = "https://schema.org/"

    @staticmethod
    def _find_graph_entry(data: Any, compact: str, full: str) -> dict | None:
        """Locate the @graph entry whose @id is the term, compact or full."""
        candidates: list[Any] = []
        if isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                candidates = graph
            else:
                candidates = [data]
        elif isinstance(data, list):
            candidates = data

        for item in candidates:
            if isinstance(item, dict) and item.get("@id") in (compact, full):
                return item
        return None

    @staticmethod
    def _by_keyword(item: dict, keyword: str) -> str:
        """Read rdfs:label / rdfs:comment however the document spells the key."""
        for key, value in item.items():
            if keyword not in key.lower():
                continue
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                inner = value.get("@value")
                if isinstance(inner, str):
                    return inner
        return ""

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        from . import OntologyResult

        term_name = term.strip()
        if not term_name:
            return OntologyResult(prefix="schema")

        compact = f"schema:{term_name}"
        full = f"https://schema.org/{term_name}"

        try:
            import requests

            resp = requests.get(
                f"{self._BASE_URL}{term_name}",
                timeout=30,
                headers={"Accept": "application/ld+json"},
            )
            resp.raise_for_status()
            body = resp.text
        except Exception:
            return OntologyResult(prefix="schema")

        # MATLAB checks the raw body for the @id before decoding, so a page
        # that exists but describes something else is a miss rather than a
        # partial result.
        id_pattern = rf'"@id"\s*:\s*"(?:{re.escape(compact)}|{re.escape(full)})"'
        if not re.search(id_pattern, body):
            return OntologyResult(prefix="schema")

        name = term_name
        definition = ""
        try:
            item = self._find_graph_entry(resp.json(), compact, full)
            if item:
                label = self._by_keyword(item, "label")
                if label:
                    name = label
                definition = self._by_keyword(item, "comment")
        except Exception:
            pass

        return OntologyResult(id=compact, name=name, prefix="schema", definition=definition)


# ---------------------------------------------------------------------------
# Fixed-list providers (no lookup service; terms held here)
# ---------------------------------------------------------------------------


class CREDITProvider(OntologyProvider):
    """The 14 CRediT contributor roles (ANSI/NISO Z39.104-2022).

    MATLAB equivalent: +ndi/+ontology/CREDIT.m

    Identified as Bioregistry's ``credit`` prefix does, by the role's slug, e.g.
    ``credit:conceptualization``, which resolves to
    https://credit.niso.org/contributor-roles/conceptualization/. No lookup
    service indexes these identifiers (OLS holds only an older numbering,
    CREDIT_00000001 ... CREDIT_00000014, inside the Contributor Role Ontology),
    so the names and definitions are held here, as MATLAB holds them. That
    older numbering is accepted as an alias.
    """

    name = "CREDIT"

    #: slug, name, definition (credit.niso.org), in the standard's order;
    #: row k (1-based) is CRO's CREDIT_0000000k
    ROLES: tuple[tuple[str, str, str], ...] = (
        (
            "conceptualization",
            "Conceptualization",
            "Ideas; formulation or evolution of overarching research goals and aims.",
        ),
        (
            "data-curation",
            "Data curation",
            "Management activities to annotate (produce metadata), scrub data and maintain "
            "research data (including software code, where it is necessary for interpreting "
            "the data itself) for initial use and later re-use.",
        ),
        (
            "formal-analysis",
            "Formal analysis",
            "Application of statistical, mathematical, computational, or other formal "
            "techniques to analyse or synthesize study data.",
        ),
        (
            "funding-acquisition",
            "Funding acquisition",
            "Acquisition of the financial support for the project leading to this publication.",
        ),
        (
            "investigation",
            "Investigation",
            "Conducting a research and investigation process, specifically performing the "
            "experiments, or data/evidence collection.",
        ),
        (
            "methodology",
            "Methodology",
            "Development or design of methodology; creation of models.",
        ),
        (
            "project-administration",
            "Project administration",
            "Management and coordination responsibility for the research activity planning "
            "and execution.",
        ),
        (
            "resources",
            "Resources",
            "Provision of study materials, reagents, materials, patients, laboratory samples, "
            "animals, instrumentation, computing resources, or other analysis tools.",
        ),
        (
            "software",
            "Software",
            "Programming, software development; designing computer programs; implementation "
            "of the computer code and supporting algorithms; testing of existing code "
            "components.",
        ),
        (
            "supervision",
            "Supervision",
            "Oversight and leadership responsibility for the research activity planning and "
            "execution, including mentorship external to the core team.",
        ),
        (
            "validation",
            "Validation",
            "Verification, whether as a part of the activity or separate, of the overall "
            "replication/reproducibility of results/experiments and other research outputs.",
        ),
        (
            "visualization",
            "Visualization",
            "Preparation, creation and/or presentation of the published work, specifically "
            "visualization/data presentation.",
        ),
        (
            "writing-original-draft",
            "Writing – original draft",
            "Preparation, creation and/or presentation of the published work, specifically "
            "writing the initial draft (including substantive translation).",
        ),
        (
            "writing-review-editing",
            "Writing – review & editing",
            "Preparation, creation and/or presentation of the published work by those from "
            "the original research group, specifically critical review, commentary or "
            "revision – including pre- or post-publication stages.",
        ),
    )

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        """Look up a CRediT role by slug, name or number.

        ``term`` is the part after the ``credit:`` prefix. It may be the slug
        ('writing-review-editing'), the role's name in any of its usual
        spellings ('Writing - review & editing', 'writing review and editing
        role'), or CRO's number ('00000014', '14'). The id is always
        'credit:<slug>'; the synonyms hold CRO's identifier for the role.

        A term that is not one of the 14 roles raises, as MATLAB does.
        """
        from . import OntologyResult
        from .name_utils import name2variableName

        k = CREDITProvider.find(term)
        if k is None:
            raise ValueError(f'CREDIT lookup failed: "{term}" is not one of the 14 CRediT roles.')
        slug, role_name, definition = CREDITProvider.ROLES[k - 1]
        return OntologyResult(
            id=f"credit:{slug}",
            name=role_name,
            prefix=prefix or "credit",
            definition=definition,
            synonyms=[f"CREDIT:{k:08d}"],
            short_name=name2variableName(role_name),
        )

    @staticmethod
    @pydantic.validate_call
    def find(term: str) -> int | None:
        """The row of ROLES that TERM names, 1-based as in MATLAB, or None."""
        roles = CREDITProvider.ROLES
        term = term.strip()
        if not term:
            return None
        n = re.fullmatch(r"(?:CREDIT[_:])?0*(\d{1,2})", term, re.I)
        if n:
            v = int(n.group(1))
            return v if 1 <= v <= len(roles) else None
        key = CREDITProvider.normalise(term)
        for r, (slug, role_name, _definition) in enumerate(roles, start=1):
            if key in (CREDITProvider.normalise(slug), CREDITProvider.normalise(role_name)):
                return r
        return None

    @staticmethod
    @pydantic.validate_call
    def normalise(s: str) -> str:
        """Lower case, words only: dashes, '&', 'and' and a trailing 'role'
        do not distinguish one role from another."""
        words = [w for w in re.sub(r"[^a-z]+", " ", s.lower()).split() if w != "and"]
        if words and words[-1] == "role":
            words.pop()
        return " ".join(words)


class OWLTimeProvider(OntologyProvider):
    """The interval relations of OWL-Time, the W3C Time Ontology.

    MATLAB equivalent: +ndi/+ontology/OWLTime.m

    Allen's thirteen relations (time:intervalBefore ... time:intervalEquals)
    and OWL-Time's two unions of them, time:intervalIn and
    time:intervalDisjoint. A term is identified as OWL-Time names it,
    ``time:<localName>``, which resolves to
    http://www.w3.org/2006/time#<localName>. OWL-Time is not on OLS and the
    relations are a fixed list, so they are held here, as MATLAB holds them.
    """

    name = "OWLTime"

    IRI_BASE = "http://www.w3.org/2006/time#"

    #: local name, label, definition (skos:definition in the OWL-Time file)
    RELATIONS: tuple[tuple[str, str, str], ...] = (
        (
            "intervalBefore",
            "interval before",
            "If a proper interval T1 is intervalBefore another proper interval T2, then the "
            "end of T1 is before the beginning of T2.",
        ),
        (
            "intervalAfter",
            "interval after",
            "If a proper interval T1 is intervalAfter another proper interval T2, then the "
            "beginning of T1 is after the end of T2.",
        ),
        (
            "intervalMeets",
            "interval meets",
            "If a proper interval T1 is intervalMeets another proper interval T2, then the "
            "end of T1 is coincident with the beginning of T2.",
        ),
        (
            "intervalMetBy",
            "interval met by",
            "If a proper interval T1 is intervalMetBy another proper interval T2, then the "
            "beginning of T1 is coincident with the end of T2.",
        ),
        (
            "intervalOverlaps",
            "interval overlaps",
            "If a proper interval T1 is intervalOverlaps another proper interval T2, then the "
            "beginning of T1 is before the beginning of T2, the end of T1 is after the "
            "beginning of T2, and the end of T1 is before the end of T2.",
        ),
        (
            "intervalOverlappedBy",
            "interval overlapped by",
            "If a proper interval T1 is intervalOverlappedBy another proper interval T2, then "
            "the beginning of T1 is after the beginning of T2, the beginning of T1 is before "
            "the end of T2, and the end of T1 is after the end of T2.",
        ),
        (
            "intervalStarts",
            "interval starts",
            "If a proper interval T1 is intervalStarts another proper interval T2, then the "
            "beginning of T1 is coincident with the beginning of T2, and the end of T1 is "
            "before the end of T2.",
        ),
        (
            "intervalStartedBy",
            "interval started by",
            "If a proper interval T1 is intervalStarted another proper interval T2, then the "
            "beginning of T1 is coincident with the beginning of T2, and the end of T1 is "
            "after the end of T2.",
        ),
        (
            "intervalDuring",
            "interval during",
            "If a proper interval T1 is intervalDuring another proper interval T2, then the "
            "beginning of T1 is after the beginning of T2, and the end of T1 is before the "
            "end of T2.",
        ),
        (
            "intervalContains",
            "interval contains",
            "If a proper interval T1 is intervalContains another proper interval T2, then the "
            "beginning of T1 is before the beginning of T2, and the end of T1 is after the "
            "end of T2.",
        ),
        (
            "intervalFinishes",
            "interval finishes",
            "If a proper interval T1 is intervalFinishes another proper interval T2, then the "
            "beginning of T1 is after the beginning of T2, and the end of T1 is coincident "
            "with the end of T2.",
        ),
        (
            "intervalFinishedBy",
            "interval finished by",
            "If a proper interval T1 is intervalFinishedBy another proper interval T2, then "
            "the beginning of T1 is before the beginning of T2, and the end of T1 is "
            "coincident with the end of T2.",
        ),
        (
            "intervalEquals",
            "interval equals",
            "If a proper interval T1 is intervalEquals another proper interval T2, then the "
            "beginning of T1 is coincident with the beginning of T2, and the end of T1 is "
            "coincident with the end of T2.",
        ),
        (
            "intervalIn",
            "interval in",
            "If a proper interval T1 is intervalIn another proper interval T2, then the "
            "beginning of T1 is after the beginning of T2 or is coincident with the beginning "
            "of T2, and the end of T1 is before the end of T2, or is coincident with the end "
            "of T2, except that end of T1 may not be coincident with the end of T2 if the "
            "beginning of T1 is coincident with the beginning of T2.",
        ),
        (
            "intervalDisjoint",
            "interval disjoint",
            "If a proper interval T1 is intervalDisjoint another proper interval T2, then the "
            "beginning of T1 is after the end of T2, or the end of T1 is before the beginning "
            "of T2, i.e. the intervals do not overlap in any way, but their ordering "
            "relationship is not known.",
        ),
    )

    @pydantic.validate_call
    def lookup_term(self, term: str, prefix: str = "") -> Any:
        """Look up an OWL-Time interval relation by local name or label.

        ``term`` is the part after the ``time:`` prefix: the local name
        ('intervalDuring') or the label ('interval during'), in any case, with
        or without spaces. The id is always 'time:<localName>'; the name is
        OWL-Time's label; the synonyms hold the term's IRI.

        A term that is not one of the relations raises, as MATLAB does.
        """
        from . import OntologyResult
        from .name_utils import name2variableName

        k = OWLTimeProvider.find(term)
        if k is None:
            raise ValueError(
                f'OWL-Time lookup failed: "{term}" is not one of OWL-Time\'s interval relations.'
            )
        local, label, definition = OWLTimeProvider.RELATIONS[k - 1]
        return OntologyResult(
            id=f"time:{local}",
            name=label,
            prefix=prefix or "time",
            definition=definition,
            synonyms=[OWLTimeProvider.IRI_BASE + local],
            short_name=name2variableName(label),
        )

    @staticmethod
    @pydantic.validate_call
    def find(term: str) -> int | None:
        """The row of RELATIONS that TERM names, 1-based as in MATLAB, or None.

        Case, spaces and underscores do not distinguish one relation from
        another, so 'intervalDuring', 'interval during' and 'INTERVAL_DURING'
        are the same relation.
        """
        key = re.sub(r"[\s_]+", "", term.strip().lower())
        if not key:
            return None
        for r, (local, _label, _definition) in enumerate(OWLTimeProvider.RELATIONS, start=1):
            if key == local.lower():
                return r
        return None


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
        "WormBase": WormBaseProvider,
        "SNOMED": SNOMEDProvider,
        "RRID": RRIDProvider,
        "EFO": EFOProvider,
        "PATO": PATOProvider,
        "PubChem": PubChemProvider,
        "EMPTY": EMPTYProvider,
        "Uberon": UberonProvider,
        "NCIT": NCITProvider,
        "STATO": STATOProvider,
        "EDAM": EDAMProvider,
        "IAO": IAOProvider,
        "SchemaOrg": SchemaOrgProvider,
        "MICRO": MICROProvider,
        "MCO": MCOProvider,
        "OBI": OBIProvider,
        "ZECO": ZECOProvider,
        "WBls": WBlsProvider,
        "OWLTime": OWLTimeProvider,
        "CREDIT": CREDITProvider,
    }
)
