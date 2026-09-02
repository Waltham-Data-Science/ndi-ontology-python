# Instructions for AI Agents

## 1. Role & Mission

You are an AI Developer for `ndi-ontology-python`, the Python port of
[`ndi-ontology-matlab`](https://github.com/Waltham-Data-Science/ndi-ontology-matlab). Your
mission is 1:1 functional and semantic parity with that MATLAB toolbox, which is the **source
of truth**.

Note the source of truth is `ndi-ontology-matlab`, **not** `NDI-matlab`. `NDI-matlab` no longer
contains `+ndi/ontology.m` — it was extracted, and all ontology work happens in the extracted
repository. Porting against `NDI-matlab` will silently port against a directory that no longer
exists.

## 2. The Local Contract: The Bridge File

`src/ndi_ontology/ndi_matlab_python_bridge.yaml` defines the exact names, input arguments and
output tuples for this namespace.

- **Rule 1: Consult the bridge first.**
- **Rule 2: Active maintenance.** If a function or class exists in `ndi-ontology-matlab` but is
  missing from the bridge file, you must:
  1. Analyze the MATLAB `.m` file.
  2. Add the entry to `ndi_matlab_python_bridge.yaml`.
  3. **Notify the user:** state "INTERFACE UPDATE: I have modified the bridge contract for
     [Function Name] to reflect the MATLAB source."
- **Rule 3: Strict naming.** Do not "Pythonize" names (e.g. `lookupTermOrID` →
  `lookup_term_or_id`) unless the bridge file's `decision_log` explicitly says to.

The one standing name divergence is the package itself: MATLAB `ndi.ontology` installs as
Python `ndi_ontology`, because Python cannot merge a namespace across distributions the way the
MATLAB path does. NDI-python re-exports it as `ndi.ontology`. See the bridge file.

## 3. Technical Constraints

- **No dependency on NDI-python.** NDI-python depends on this package; importing `ndi` from
  here would close a cycle. `tests/test_ontology.py::TestPackagedDataFiles` enforces this, and
  it is not a test to relax — if you need a helper from NDI-python, vendor it, as
  `ndi-ontology-matlab` vendors its own `name2variableName`.
- **Validation:** public API functions use the `@pydantic.validate_call` decorator.
- **Data files** live inside the package (`src/ndi_ontology/ndi_common/`) and are resolved
  through `ndi_ontology.paths`, never by walking up from the working directory.
- **Adding an ontology** should touch `ontology_list.json` and `providers.py` — nothing else.
- **Formatting:** code must pass `black` and `ruff check` before completion.

## 4. Adding a provider

1. Read the MATLAB class in `ndi-ontology-matlab/src/ndi/+ndi/+ontology/<Name>.m`.
2. Add the provider class to `src/ndi_ontology/providers.py` and register it in
   `PROVIDER_REGISTRY`. Most ontologies are OLS-backed and subclass `OLSProvider`.
3. Add the prefix entries to `src/ndi_ontology/ndi_common/ontology/ontology_list.json`, matching
   the MATLAB copy — including alias prefixes (`format` → EDAM, `taxonomy` → NCBITaxon).
4. Add tests: lookup by ID, lookup by name, and the not-found path.
5. Update the bridge file.

## 5. CI Lint & Test Commands

Before pushing, run these — they are what CI runs.

```bash
black --check src/ tests/     # black src/ tests/ to fix
ruff check src/ tests/        # ruff check --fix src/ tests/ to fix
pytest tests/ -v --tb=short
```

Quick pre-push checklist:

```bash
black src/ tests/ && ruff check src/ tests/ && pytest tests/ -x -q
```

Tests that need the network (live OLS, PubChem, NCBI queries) skip themselves when it is
unreachable; do not convert a network failure into a passing test.

## 6. Directory Mapping Reference

| MATLAB (`ndi-ontology-matlab`) | Python (here) |
|---|---|
| `src/ndi/+ndi/ontology.m` | `src/ndi_ontology/__init__.py` |
| `src/ndi/+ndi/+ontology/<Name>.m` | `<Name>Provider` in `src/ndi_ontology/providers.py` |
| `src/ndi/+ndi/+ontology/name2variableName.m` | `src/ndi_ontology/name_utils.py` |
| `src/ndi/+ndi/ontologyToolboxDir.m` | `src/ndi_ontology/paths.py` |
| `src/ndi/ndi_common/` | `src/ndi_ontology/ndi_common/` |
| `tests/+ndi/+unittest/+ontology/` | `tests/matlab_tests/` |
