"""Emit only deterministic tar bytes; guest verifies the prepared full-stream hash."""
import argparse
import json
from pathlib import Path
import sys
from model_bundle import stream


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',required=True,type=Path)
    args=parser.parse_args();bundle=json.loads(args.bundle.read_text())
    if bundle['transport']!='DETERMINISTIC_TAR_STREAM':raise ValueError('Unexpected model transport')
    result=stream(bundle['model_directory'],bundle['corpus_path'],sys.stdout.buffer)
    sys.stdout.buffer.flush()
    if result['sha256']!=bundle['model_archive_sha256'] or result['bytes']!=bundle['model_archive_bytes']:
        raise ValueError('Model stream changed since local preparation')


if __name__=='__main__':main()
