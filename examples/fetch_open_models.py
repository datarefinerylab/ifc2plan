#!/usr/bin/env python3
"""
Re-fetch and verify the open-access IFC models in examples/data/open/.

**The models are committed.** You do not need to run this to use them - clone the repo
and they are there. This script exists so they can be re-derived and audited rather than
being five binaries of unexplained origin: it records where each one came from and the
SHA-256 of the file that is in the repo, so anyone can confirm that what we ship is what
the source published.

Why they are here at all: the only other committed model is Schependomlaan, which is
IFC2X3 and declared in millimetres. Every model this tool is actually run against is
IFC4, and some are declared in metres. These cover schema and unit combinations the
Schependomlaan example cannot reach. Licences are recorded in docs/test-models.md.

    python examples/fetch_open_models.py --verify   # check what is in the repo
    python examples/fetch_open_models.py --list     # show sources and terms
    python examples/fetch_open_models.py --force    # re-download everything

A plain run fetches only what is missing, so on a normal checkout it does nothing.
"""

import argparse
import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

DEST = Path(__file__).resolve().parent / "data" / "open"

# sha256 is of the .ifc file that ends up on disk, not of the downloaded archive.
MODELS = {
    "fzk-haus": {
        "url": "https://www.ifcwiki.org/images/e/e3/AC20-FZK-Haus.ifc",
        "filename": "AC20-FZK-Haus.ifc",
        "sha256": "70cc8ff245fc0894201d96496c031005a5cbd7a96b22d8a1b87c5a883fb77994",
        "note": "IFC4, metres, 2 storeys, 7 spaces. Smallest real IFC4 building here.",
    },
    "institute": {
        "url": "https://www.ifcwiki.org/images/9/98/AC20-Institute-Var-2.ifc",
        "filename": "AC20-Institute-Var-2.ifc",
        "sha256": "cfb2124497b25d9a72101075e84be0feb44ff669cb1bd3251be11efebeea945c",
        "note": "IFC4, metres, 5 storeys, 82 spaces. Office building.",
    },
    "smiley-west": {
        "url": "https://www.ifcwiki.org/images/c/c8/AC-20-Smiley-West-10-Bldg.zip",
        "filename": "AC-20-Smiley-West-10-Bldg.ifc",
        "sha256": "26734e67bdc0fd2ab30cb560bddc279a0a4f23eb4d28861509524e4bbe201c48",
        "zip_member": "AC-20-Smiley-West-10-Bldg.ifc",
        "note": "IFC4, metres, 5 storeys, 140 spaces across 10 dwellings (issue #27).",
    },
    "pcert-ifc4": {
        "url": (
            "https://raw.githubusercontent.com/buildingSMART/Sample-Test-Files/main/"
            "IFC%204.0.2.1%20(IFC%204)/PCERT-Sample-Scene/Building-Architecture.ifc"
        ),
        "filename": "PCERT-Building-Architecture-IFC4.ifc",
        "sha256": "3ff9b10bd00c7b96dded51e7ca5a6b69efbea38b049adcdd05fcd247de7e70d5",
        "note": "IFC4 with IfcTriangulatedFaceSet bodies. 220 KB.",
    },
    "pcert-ifc4x3": {
        "url": (
            "https://raw.githubusercontent.com/buildingSMART/Sample-Test-Files/main/"
            "IFC%204.3.2.0%20(IFC4X3_ADD2)/PCERT-Sample-Scene/Building-Architecture.ifc"
        ),
        "filename": "PCERT-Building-Architecture-IFC4X3.ifc",
        "sha256": "a42962f9e2068040ac96636b1e7f6117150b6c0e3371f81088721b22796e463f",
        "note": "IFC4X3_ADD2, the only IFC4X3 model here.",
    },
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(key, spec, force=False):
    target = DEST / spec["filename"]
    if target.exists() and not force:
        if sha256(target) == spec["sha256"]:
            print(f"  ok      {key:14s} {spec['filename']} (already present)")
            return True
        print(f"  stale   {key:14s} checksum differs, re-fetching")

    print(f"  fetch   {key:14s} {spec['url']}")
    try:
        with urllib.request.urlopen(spec["url"], timeout=180) as response:
            payload = response.read()
    except Exception as exc:  # noqa: BLE001 - the host being down is the common case
        print(f"  FAILED  {key:14s} {exc}")
        return False

    if "zip_member" in spec:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            payload = archive.read(spec["zip_member"])

    DEST.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    got = sha256(target)
    if got != spec["sha256"]:
        print(f"  FAILED  {key:14s} sha256 mismatch\n            expected {spec['sha256']}\n            got      {got}")
        print("            The file at the source changed. Check it, then update this script.")
        return False

    print(f"  done    {key:14s} {len(payload) / 1024:.0f} KB -> {target.relative_to(Path.cwd()) if target.is_relative_to(Path.cwd()) else target}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("keys", nargs="*", help="Which models to fetch (default: all)")
    parser.add_argument("--list", action="store_true", help="Show the models and exit")
    parser.add_argument("--force", action="store_true", help="Re-download even if present and valid")
    parser.add_argument("--verify", action="store_true",
                        help="Check the committed files against their recorded checksums, download nothing")
    args = parser.parse_args()

    if args.list:
        for key, spec in MODELS.items():
            print(f"{key:14s} {spec['note']}\n{'':14s} {spec['url']}")
        return 0

    if args.verify:
        bad = 0
        for key, spec in MODELS.items():
            target = DEST / spec["filename"]
            if not target.exists():
                print(f"  MISSING {key:14s} {spec['filename']}")
                bad += 1
            elif sha256(target) != spec["sha256"]:
                print(f"  DIFFERS {key:14s} {spec['filename']} does not match its recorded sha256")
                bad += 1
            else:
                print(f"  ok      {key:14s} {spec['filename']}")
        print(f"\n{len(MODELS) - bad} of {len(MODELS)} verified.")
        return 1 if bad else 0

    unknown = [k for k in args.keys if k not in MODELS]
    if unknown:
        parser.error(f"unknown model(s): {', '.join(unknown)}. Try --list.")

    keys = args.keys or list(MODELS)
    print(f"Fetching {len(keys)} model(s) into {DEST}")
    results = [fetch(k, MODELS[k], force=args.force) for k in keys]

    failed = results.count(False)
    print(f"\n{len(results) - failed} of {len(results)} available."
          + (" Licences and provenance: docs/test-models.md" if not failed else ""))
    if failed:
        print("Some models could not be fetched. They are committed, so a normal checkout\n"
              "already has them - this only matters if you deleted them or used --force.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
