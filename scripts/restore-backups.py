"""Restore a checksum-verified archived backend backup into a NEW directory."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
parser=argparse.ArgumentParser()
parser.add_argument('archive',type=Path)
parser.add_argument('destination',type=Path)
args=parser.parse_args()
root=args.destination.resolve()
if root.exists():raise SystemExit('Destination must not exist; no existing files are overwritten.')
with zipfile.ZipFile(args.archive) as bundle:
    manifest=json.loads(bundle.read('manifest.json'))
    # Validate every entry before creating the destination.
    for name,digest in manifest.items():
        target=(root/name).resolve()
        if not target.is_relative_to(root) or target==root:raise SystemExit('Invalid archive path')
        content=bundle.read('objects/'+digest)
        if hashlib.sha256(content).hexdigest()!=digest:raise SystemExit('Checksum mismatch')
    for name,digest in manifest.items():
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(bundle.read('objects/'+digest))
print('Restored',len(manifest),'verified files.')
