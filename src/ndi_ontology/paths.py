"""
ndi_ontology.paths - Location of this toolbox's own data files.

MATLAB equivalent: +ndi/ontologyToolboxDir.m

The MATLAB toolbox resolves its data files relative to the folder holding
the ``+ndi`` package, so that ``ontology_list.json`` and ``NDIC.txt`` travel
with the ontology code rather than with NDI-matlab. This module is the same
idea for the Python port: the data files ship inside the ``ndi_ontology``
package, and every path is derived from this file's own location.

Nothing here reaches into NDI-python. That is deliberate -- NDI-python
depends on this package, so a dependency in the other direction would be a
cycle.
"""

from __future__ import annotations

from pathlib import Path

# The directory holding this package. MATLAB's ontologyToolboxDir() returns
# the parent of the +ndi package folder; the Python analogue is the package
# directory itself, since the data files live underneath it.
TOOLBOX_DIR: Path = Path(__file__).resolve().parent

#: Root of the packaged data files, mirroring MATLAB's src/ndi/ndi_common.
COMMON_FOLDER: Path = TOOLBOX_DIR / "ndi_common"

#: ontology_list.json -- the prefix -> ontology registry.
ONTOLOGY_LIST_FILE: Path = COMMON_FOLDER / "ontology" / "ontology_list.json"

#: NDIC.txt -- the NDI Controlled Vocabulary table.
NDIC_FILE: Path = COMMON_FOLDER / "controlled_vocabulary" / "NDIC.txt"


def ontologyToolboxDir() -> Path:
    """Return the root directory of the ndi-ontology-python toolbox.

    MATLAB equivalent: ndi.ontologyToolboxDir

    Returns:
        Absolute path to the directory holding this package; data files are
        located relative to it.
    """
    return TOOLBOX_DIR


__all__ = [
    "TOOLBOX_DIR",
    "COMMON_FOLDER",
    "ONTOLOGY_LIST_FILE",
    "NDIC_FILE",
    "ontologyToolboxDir",
]
