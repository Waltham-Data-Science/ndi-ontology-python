# ndi-ontology-python

Python implementation of `ndi.ontology` — a unified interface for looking up terms across
biological and scientific ontologies.

This is the Python companion to
[ndi-ontology-matlab](https://github.com/Waltham-Data-Science/ndi-ontology-matlab), which is
the source of truth for behaviour. Both are part of the
[NDI (Neuroscience Data Interface)](https://ndi.vhlab.org) ecosystem.

## Why this is a separate repository

`NDI-matlab` no longer contains `+ndi/ontology.m`; the ontology code was extracted into
`ndi-ontology-matlab` and is pulled back in through `requirements.txt`. This repository is the
same split on the Python side, so that the port tracks the repository the MATLAB code now
actually lives in.

### The package is `ndi_ontology`, not `ndi.ontology`

MATLAB merges the `ndi` namespace across every folder on the path, so `ndi-ontology-matlab` can
contribute `+ndi/ontology.m` to the same namespace as NDI-matlab for free. Python has no
equivalent for a *regular* package: `ndi/__init__.py` in NDI-python is the public API surface,
which makes `ndi` a regular package, and a second distribution cannot install into it.

So this distribution installs as top-level `ndi_ontology`, and NDI-python re-exports it at
`ndi.ontology`. Callers in NDI-python keep writing:

```python
from ndi.ontology import lookup
```

which is what keeps the naming aligned with MATLAB's `ndi.ontology`. Used standalone, without
NDI-python, the import is:

```python
from ndi_ontology import lookup
```

The divergence and the reasoning are recorded in
[`src/ndi_ontology/ndi_matlab_python_bridge.yaml`](src/ndi_ontology/ndi_matlab_python_bridge.yaml).

## Installation

```bash
pip install git+https://github.com/Waltham-Data-Science/ndi-ontology-python.git@main
```

NDI-python declares this as a dependency, so installing NDI-python installs it too.

This package deliberately depends on nothing from NDI-python — NDI-python depends on it, and a
dependency in the other direction would be a cycle. `tests/test_ontology.py` enforces that.

## Usage

```python
from ndi_ontology import lookup

result = lookup('CL:0000540')      # Cell Ontology, by ID
result = lookup('CL:neuron')       # ... or by name

result.id        # 'CL:0000540'
result.name      # 'neuron'
result.prefix    # 'CL'
result.definition
result.synonyms
result.short_name
```

## Supported ontologies

| Prefix | Ontology | |
|--------|----------|---|
| `CL` | [Cell Ontology](http://obofoundry.org/ontology/cl.html) | ✅ |
| `CHEBI` | [Chemical Entities of Biological Interest](https://www.ebi.ac.uk/chebi/) | ✅ |
| `PATO` | [Phenotype and Trait Ontology](http://obofoundry.org/ontology/pato.html) | ✅ |
| `NCBITaxon` / `taxonomy` | [NCBI Taxonomy](https://www.ncbi.nlm.nih.gov/taxonomy) | ✅ |
| `NCIm` | [NCI Metathesaurus](https://ncim.nci.nih.gov/ncimbrowser/) | ✅ |
| `OM` | [Ontology of Units of Measure](http://obofoundry.org/ontology/om.html) | ✅ |
| `PubChem` | [PubChem](https://pubchem.ncbi.nlm.nih.gov/) | ✅ |
| `RRID` | [Research Resource Identifiers](https://scicrunch.org/resources) | ✅ |
| `SNOMED` | [SNOMED CT](https://www.snomed.org/) | ✅ |
| `EFO` | [Experimental Factor Ontology](https://www.ebi.ac.uk/efo/) | ✅ |
| `EMPTY` | [Experimental Measurements, Purposes, and Treatments ontologY](https://github.com/Waltham-Data-Science/empty-ontology) | ✅ |
| `NDIC` | NDI Controlled Vocabulary (local) | ✅ |
| `WBStrain` | [WormBase Strain Database](https://wormbase.org) | ✅ |
| `UBERON` | [Uberon Multi-Species Anatomy Ontology](http://obofoundry.org/ontology/uberon.html) | ✅ |
| `NCIT` | [NCI Thesaurus](http://obofoundry.org/ontology/ncit.html) | ✅ |
| `EDAM` / `format` | [EDAM Bioinformatics Ontology](http://edamontology.org) | ✅ |
| `IAO` | [Information Artifact Ontology](http://obofoundry.org/ontology/iao.html) | ✅ |
| `STATO` | [Statistics Ontology](http://stato-ontology.org/) | ✅ |
| `schema` | [Schema.org](https://schema.org) | ✅ |

All nineteen ontologies MATLAB implements are ported, as of
[NDI-python#98](https://github.com/Waltham-Data-Science/NDI-python/issues/98). Three mechanisms
are in play, matching MATLAB: most are OLS-backed; `EDAM` and `IAO` download and parse an OWL
file; `schema` reads each term's JSON-LD document from schema.org.

Prefixes are registered in exactly one place — `ontology_list.json`. Adding an ontology means
adding its entry there and a provider class, and nothing else. `UBERON` and `NCIT` used to be
registered with no provider behind them, so those lookups resolved a prefix to nothing and
returned an empty result; a test now fails if any registered prefix loses its provider.

One caveat inherited from the port, and still open: `lookup()` answers an unresolvable prefix,
a network failure and a genuinely absent term with the same empty `OntologyResult`, where
MATLAB raises. That is the remaining item of NDI-python#98.

## Key concepts: ID (node) vs. name (label)

`lookup` always returns both an **ID** and a **NAME**.

- **ID** (the "node"): the canonical, unique identifier for a concept — the string you store in
  data or use in code to reference the term unambiguously.
- **NAME** (the "label"): the human-readable text describing the concept.

Ontologies differ in what their IDs look like, but `lookup` presents them the same way:

**Numbered nodes** (CL, UBERON, CHEBI, PATO, EMPTY, NCIT, EFO, …) — a numeric code with a
separate label:

```
  lookup('CL:0000540')  or  lookup('CL:neuron')
  id   = 'CL:0000540'    ← the numbered node, always canonical
  name = 'neuron'        ← the human-readable label
```

**Term-style nodes** (OM) — the node itself is readable:

```
  lookup('OM:Temperature')
  id   = 'OM:Temperature'  ← canonical casing
  name = 'temperature'     ← normalized lowercase label
```

**External database lookups** (PubChem, NCIm, NCBITaxon, RRID, NDIC, …) — the ID is the source
database's native identifier, and the prefix may not appear in it:

```
  lookup('PubChem:Aspirin')  or  lookup('PubChem:2244')
  id   = '2244'      ← PubChem compound ID (CID)
  name = 'aspirin'
```

In every case you may look up by ID or by name; `lookup` works out which you gave it.

## Data files

`ontology_list.json` (the prefix registry) and `NDIC.txt` (the NDI Controlled Vocabulary) ship
**inside the package**, under `src/ndi_ontology/ndi_common/`. This mirrors
`ndi-ontology-matlab`, which carries its own `src/ndi/ndi_common/` and locates it with
`ndi.ontologyToolboxDir()`. The Python equivalent is `ndi_ontology.paths`.

Registering a new ontology should mean editing `ontology_list.json` and adding a provider class
— nowhere else.

## Development

```bash
pip install -e ".[dev]"
black src/ tests/ && ruff check src/ tests/ && pytest tests/ -q -m "not live"
```

### The shared case table (parity with MATLAB)

`ndi-ontology-matlab` drives its own tests from
`tests/+ndi/+unittest/+ontology/ontology_lookup_tests.json` — 66 cases across 15 ontologies,
each naming a lookup string and the exact id and name it must produce. That file is
language-neutral, so this repository runs **the same cases** against the Python port:

```bash
git clone https://github.com/Waltham-Data-Science/ndi-ontology-matlab.git
NDI_ONTOLOGY_MATLAB_DIR=./ndi-ontology-matlab pytest tests/test_shared_cases.py -v -rs
```

This is the parity check for the namespace, and it needs no artifact-exchange machinery: a
lookup's output is two strings, so the expected values live in the fixture and both
implementations are checked against it directly. The file is never vendored here — a second
copy would drift from MATLAB's exactly as `ontology_list.json` did, and a stale *test* fixture
reports a parity that is not there.

In CI the job also sets `NDI_ONTOLOGY_REQUIRE_LIVE=1`, which turns "the ontology APIs are
unreachable" from a skip into a failure. Without it, one throttled probe against OLS silently
reduced the whole job to `6 passed, 61 skipped in 6.56s` — a green check that verified no parity
at all. This mirrors NDI-python's `NDI_SYMMETRY_STRICT=1`: a check that could not run counts as
a failure, not a pass.

Of the 66 cases, 47 run today and 19 skip themselves naming
[NDI-python#98](https://github.com/Waltham-Data-Science/NDI-python/issues/98), so `-rs` output
doubles as a progress meter for the port. Cases whose API is unreachable skip rather than fail,
so only a genuine mismatch turns the job red.

### Porting contract

Anyone (or anything) changing this code should read, in order:

| | |
|---|---|
| [`AGENTS.md`](AGENTS.md) | the workflow for this repository, including how to add a provider |
| [`docs/developer_notes/PYTHON_PORTING_GUIDE.md`](docs/developer_notes/PYTHON_PORTING_GUIDE.md) | the MATLAB→Python protocol: naming, Pydantic, sync hashes |
| [`docs/developer_notes/ndi_xlang_principles.md`](docs/developer_notes/ndi_xlang_principles.md) | cross-language rules: indexing, counting, hard-fail semantics |
| [`docs/developer_notes/ndi_matlab_python_bridge.yaml`](docs/developer_notes/ndi_matlab_python_bridge.yaml) | the spec for bridge files themselves |
| [`src/ndi_ontology/ndi_matlab_python_bridge.yaml`](src/ndi_ontology/ndi_matlab_python_bridge.yaml) | **the contract for this namespace** — every class, provider, data file and test, mapped to its MATLAB source with a sync hash |

The bridge file is the one to read first when porting. It records which providers have actually
been examined against their MATLAB source (most have not, and say so) rather than implying a
parity that was never checked.

## License

CC BY-NC-SA 4.0 — see [LICENSE](LICENSE).
