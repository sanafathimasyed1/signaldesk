"""Stream a bounded prefix of the provided .json.zst; persist allowlisted fields."""

import argparse
import hashlib
import json
import sys
import urllib.request
from compression import zstd
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from salesintel.accounts import normalize

SOURCE = ("https://f001.backblazeb2.com/b2api/v1/b2_download_file_by_id?"
          "fileId=4_z53658c377a6f469082f90a15_f203f57b98e5fb869_d20261008_m141631_c001_v0001097_t0036_u01791468991916")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=12000)
    parser.add_argument("--max-mb", type=int, default=32)
    args = parser.parse_args()
    if not 1 <= args.records <= 100000 or not 1 <= args.max_mb <= 256:
        parser.error("Use 1-100000 records and a 1-256 MB compressed budget")
    maximum = args.max_mb * 1024 * 1024
    request = urllib.request.Request(SOURCE, headers={"Range": f"bytes=0-{maximum-1}"})
    decompressor = zstd.ZstdDecompressor()
    buffer = b""
    observations = []
    count, consumed, invalid = 0, 0, 0
    source_hash = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=90) as response:
        while count < args.records and consumed < maximum:
            block = response.read(min(65536, maximum - consumed))
            if not block:
                break
            consumed += len(block)
            source_hash.update(block)
            # The decompression bound prevents a compressed-bomb record from
            # allocating unlimited memory; drain buffered output before reading on.
            output = decompressor.decompress(block, max_length=4 * 1024 * 1024)
            while True:
                buffer += output
                while b"\n" in buffer and count < args.records:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    count += 1
                    try:
                        observation = normalize(json.loads(line))
                    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                        invalid += 1
                        print(f"Skipping invalid source record {count}: {type(exc).__name__}", file=sys.stderr)
                        continue
                    if observation is not None:
                        observations.append(observation)
                    else:
                        invalid += 1
                if count >= args.records or decompressor.needs_input:
                    break
                output = decompressor.decompress(b"", max_length=4 * 1024 * 1024)
            if len(buffer) > 16 * 1024 * 1024:
                raise RuntimeError("Source record exceeds 16 MB safety limit")
    if not observations:
        raise RuntimeError("No complete valid observations were imported")
    directory = ROOT / "data"
    directory.mkdir(exist_ok=True)
    temporary = directory / "observations.jsonl.tmp"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for observation in observations:
            handle.write(json.dumps(observation, ensure_ascii=True) + "\n")
    temporary.replace(directory / "observations.jsonl")
    metadata = {
        "source_url": SOURCE, "source_name": "2026-10-08T13:00:00.json.zst",
        "records_imported": len(observations), "records_scanned": count, "invalid_records": invalid,
        "sample_strategy": "Bounded sequential prefix, NOT a random or representative market sample",
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "compressed_bytes_read": consumed, "prefix_sha256": source_hash.hexdigest(),
        "normalization_version": "v1", "total_compressed_source_bytes": 11882007675,
        "privacy": "Only allowlisted metadata retained; no IPs, banners, certificate blobs, contacts or credentials",
    }
    (directory / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(observations)} / {count} records from {consumed:,} compressed bytes.")


if __name__ == "__main__":
    main()
