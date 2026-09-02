# NDI MATLAB to Python Porting Guide

> **Scope in this repository.** This is NDI-python's porting guide, kept here
> verbatim so that this repository's contract does not drift from the
> ecosystem's. Two things are specific to `ndi-ontology-python`:
>
> 1. **The source of truth is
>    [`ndi-ontology-matlab`](https://github.com/Waltham-Data-Science/ndi-ontology-matlab),
>    not `NDI-matlab`.** `NDI-matlab` no longer contains `+ndi/ontology.m` — the
>    ontology code was extracted and is pulled back in through its
>    `requirements.txt`. Porting against `NDI-matlab` will silently port against
>    a directory that no longer exists. Every `matlab_path` in the bridge file is
>    relative to `ndi-ontology-matlab` unless the entry says otherwise.
> 2. **The package name is the one sanctioned divergence from the Mirror Rule
>    in §2.** MATLAB `ndi.ontology` installs as Python `ndi_ontology`, because
>    Python cannot add a subpackage to a regular package from a second
>    distribution the way the MATLAB path merges namespaces. NDI-python
>    re-exports it as `ndi.ontology`, so call sites still mirror MATLAB. The
>    reasoning, and the rejected PEP 420 alternative, are recorded under
>    `project_metadata.package_name_divergence` in
>    `src/ndi_ontology/ndi_matlab_python_bridge.yaml`. Do not "fix" it by
>    renaming; do not extend it to anything else.
>
> See also `AGENTS.md` for the workflow specific to adding a provider.

## 1. The Core Philosophy: Lead-Follow Architecture

The MATLAB codebase is the **Source of Truth**. The Python version is a "faithful mirror." When a conflict arises between "Pythonic" style and MATLAB symmetry, **symmetry wins**.

- **Lead-Follow:** MATLAB defines the logic, hierarchy, and naming.
- **The Contract:** Every package contains an `ndi_matlab_python_bridge.yaml`. This file is the binding contract for function names, arguments, and return types for that specific namespace.

## 2. Naming & Discovery (The Mirror Rule)

Function and class names must match MATLAB exactly.

- **Naming Source:** Refer to the local `ndi_matlab_python_bridge.yaml`.
- **Missing Entries:** If a function is not in the bridge file, refer to the MATLAB source to determine the name, add the entry to the bridge file, and notify the user of the addition for their review.
- **Case Preservation:** Use `ListAllDocuments`, not `list_all_documents`. Use `savetofile`, not `save_to_file`.
- **Directory Parity:** Python file paths must mirror MATLAB `+namespace` paths (e.g., `+ndi/+cloud` → `src/ndi/cloud/`).

## 3. The Porting Workflow (The Bridge Protocol)

To port or update a function, agents must follow these steps:

1. **Check the Bridge:** Open the `ndi_matlab_python_bridge.yaml` in the target package.
2. **Sync the Interface:** If the function is missing or outdated, update the YAML entry first based on the MATLAB `.m` file.
3. **Record the Sync Hash:** Store the short git hash of the MATLAB `.m` file being ported in the `matlab_last_sync_hash` field. Obtain it with: `git log -1 --format="%h" -- <path-to-matlab-file>`. This allows future comparison to detect upstream MATLAB changes.
4. **Implement:** Write the Python code to satisfy the `input_arguments` and `output_arguments` defined in the YAML.
5. **Log & Notify:** Record the sync date in the YAML's `decision_log` (e.g., `"Synchronized with MATLAB main as of 2026-03-12."`). ndi_document any intentional divergences. Explicitly tell the user what changes were made to the bridge file so they can review the contract.

## 4. Input Validation: Pydantic is Mandatory

To replicate the robustness of the MATLAB `arguments` block, use Pydantic for all public-facing API functions.

- **Decorator:** Use the `@pydantic.validate_call` decorator on all functions.
- **Type Mirroring:**
  - MATLAB `double`/`numeric` → Python `float | int`
  - MATLAB `char`/`string` → Python `str`
  - MATLAB `{member1, member2}` → Python `Literal["member1", "member2"]`
- **Union Types:** Implement multiple allowed types as a Type Union (e.g., `str | int`).
- **Coercion:** Allow Pydantic's default casting (e.g., allowing a string `"1"` to satisfy a `bool` type).
- **Arbitrary Types:** For types like `numpy.ndarray`, use `config=ConfigDict(arbitrary_types_allowed=True)`.

## 5. Multiple Returns (Outputs)

MATLAB allows multiple return values natively. In Python, these must be returned as a **tuple** in the exact order defined in the `output_arguments` section of the bridge YAML.

## 6. Code Style & Linting

All Python code must pass formatting and linting before being committed.

- **Black:** The sole code formatter. Line length is **100**, set in `pyproject.toml`, matching NDI-python's actual configuration rather than black's default of 88.
- **Ruff:** The primary linter. Run `ruff check --fix` before committing.

## 7. Error Handling & Documentation

- **Hard Fails:** If a MATLAB function throws an error, the Python version must raise a corresponding Exception (`ValueError`, `TypeError`, or `NDIError`).
- **Docstring Symmetry:** Include the original MATLAB documentation in the Python docstring. Add a "Python-specific Notes" section at the bottom for library-specific details.
