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

## 2. The Mandatory Knowledge Base

Before proposing, writing, or refactoring any code, read these in order:

1. **Porting Protocol:** `docs/developer_notes/PYTHON_PORTING_GUIDE.md`
   — technical workflow, naming rules, Pydantic validation, linting. Its opening note records
   the two things specific to this repository: the source of truth is `ndi-ontology-matlab`,
   and the package name is the one sanctioned divergence from the Mirror Rule.
2. **Universal Principles:** `docs/developer_notes/ndi_xlang_principles.md`
   — 0-vs-1 indexing, semantic parity for scientific counting, NumPy usage, and the
   no-silent-failures rule.
3. **Bridge Protocol Spec:** `docs/developer_notes/ndi_matlab_python_bridge.yaml`
   — the specification for bridge files themselves, including the sync-hash mechanism.

These are NDI-python's files, kept here verbatim so this repository's contract does not drift
from the ecosystem's. If they change there, change them here.

## 3. The Local Contract: The Bridge File

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
- **Rule 4: Record the sync hash.** Every entry carries `matlab_last_sync_hash` — the short
  hash of the MATLAB file the Python side was written against. Get it from a checkout of
  `ndi-ontology-matlab`:

  ```bash
  git log -1 --format="%h" -- src/ndi/+ndi/+ontology/<Name>.m
  ```

  A newer hash upstream means the entry needs re-examination. **Do not fill in a hash you have
  not earned.** Most provider entries currently say `NOT EXAMINED` in `sync_status`, because
  the Python providers were written before the MATLAB extraction and have never been read
  against the `.m` files they claim to mirror. Marking a file not-examined is accurate; a hash
  implying an examination that never happened is worse than no hash at all. If you do examine a
  provider, correct its entry — that is real progress and worth recording on its own.

The one standing name divergence is the package itself: MATLAB `ndi.ontology` installs as
Python `ndi_ontology`, because Python cannot merge a namespace across distributions the way the
MATLAB path does. NDI-python re-exports it as `ndi.ontology`. See the bridge file.

## 4. Technical Constraints

- **No dependency on NDI-python.** NDI-python depends on this package; importing `ndi` from
  here would close a cycle. `tests/test_ontology.py::TestPackagedDataFiles` enforces this, and
  it is not a test to relax — if you need a helper from NDI-python, vendor it, as
  `ndi-ontology-matlab` vendors its own `name2variableName`.
- **Validation:** public API functions use the `@pydantic.validate_call` decorator.
- **Failures raise.** `lookup()` raises `NDIOntologyLookupError` rather than returning an empty
  result, matching MATLAB and `ndi_xlang_principles` section 6 ("No Silent Failures"). Do not
  reintroduce an empty-result path: an empty result is indistinguishable from a resolved term
  with blank fields, and that ambiguity hid four defects during the port. Providers may still
  return an empty result internally to mean "not found"; `lookup()` is the single place that
  becomes the raise.
- **Data files** live inside the package (`src/ndi_ontology/ndi_common/`) and are resolved
  through `ndi_ontology.paths`, never by walking up from the working directory.
- **Adding an ontology** should touch `ontology_list.json` and `providers.py` — nothing else.
- **Formatting:** code must pass `black` and `ruff check` before completion.

## 5. Adding a provider

1. Read the MATLAB class in `ndi-ontology-matlab/src/ndi/+ndi/+ontology/<Name>.m`.
2. Add the provider class to `src/ndi_ontology/providers.py` and register it in
   `PROVIDER_REGISTRY`. Most ontologies are OLS-backed and subclass `OLSProvider`.
3. Add the prefix entries to `src/ndi_ontology/ndi_common/ontology/ontology_list.json`, matching
   the MATLAB copy — including alias prefixes (`format` → EDAM, `taxonomy` → NCBITaxon).
4. Add tests: lookup by ID, lookup by name, and the not-found path.
5. Update the bridge file: flip `status` to `ported`, fill in `python_class`, and replace
   `sync_status` with what you actually verified, against the hash you read.
6. Register the alias prefixes too. MATLAB maps `format` → EDAM, `taxonomy` → NCBITaxon,
   `schema` → SchemaOrg; a provider whose aliases are missing looks ported and then fails for
   half its callers.

## 6. CI Lint & Test Commands

Before pushing, run these — they are what CI runs.

```bash
black --check src/ tests/     # black src/ tests/ to fix
ruff check src/ tests/        # ruff check --fix src/ tests/ to fix
pytest tests/ -v --tb=short -m "not live"
```

The `live` marker covers the shared case table — `ndi-ontology-matlab`'s own
`ontology_lookup_tests.json`, run against this port. It needs a checkout of that repository and
reaches live ontology APIs, so it is a separate CI job. Run it before changing any provider:

```bash
NDI_ONTOLOGY_MATLAB_DIR=/path/to/ndi-ontology-matlab pytest tests/test_shared_cases.py -v -rs
```

CI additionally sets `NDI_ONTOLOGY_REQUIRE_LIVE=1`, so an unreachable API fails the job instead
of skipping every case and passing. Do not unset it to get a green run — a job that skipped the
parity cases has checked nothing, which is the one outcome worse than a red one.

A case that fails there is a **port defect** until you have read the MATLAB source and
established otherwise. Known divergences are `xfail(strict=True)` with a reason naming the
MATLAB file and line — strict, so a fixed one turns CI red until its marker is removed. Do not
add a marker to make a red case go away.

Quick pre-push checklist:

```bash
black src/ tests/ && ruff check src/ tests/ && pytest tests/ -x -q
```

Tests that need the network (live OLS, PubChem, NCBI queries) skip themselves when it is
unreachable; do not convert a network failure into a passing test.

## 7. Directory Mapping Reference

| MATLAB (`ndi-ontology-matlab`) | Python (here) |
|---|---|
| `src/ndi/+ndi/ontology.m` | `src/ndi_ontology/__init__.py` |
| `src/ndi/+ndi/+ontology/<Name>.m` | `<Name>Provider` in `src/ndi_ontology/providers.py` |
| `src/ndi/+ndi/+ontology/name2variableName.m` | `src/ndi_ontology/name_utils.py` |
| `src/ndi/+ndi/ontologyToolboxDir.m` | `src/ndi_ontology/paths.py` |
| `src/ndi/ndi_common/` | `src/ndi_ontology/ndi_common/` |
| `tests/+ndi/+unittest/+ontology/` | `tests/matlab_tests/` |
| `tests/+ndi/+unittest/+ontology/ontology_lookup_tests.json` | *(not consumed yet — see the `tests:` section of the bridge file)* |
