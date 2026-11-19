"""Build one small US-English MP3 for every vocabulary row."""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory


def read_words(html_file):
    match = re.search(
        r"^const ITEMS\s*=\s*(\[.*\]);$", html_file.read_text(encoding="utf-8"), re.MULTILINE
    )
    if not match:
        raise ValueError("Could not find the vocabulary data in index.html")
    return [item["en"] for item in json.loads(match.group(1))]


def make_clip(row, output, scratch):
    index, word = row
    text = re.sub(r"\(([^)]*)\)", r"\1", word.replace("/", ", "))
    text_file = scratch / f"{index}.txt"
    text_file.write_text(text, encoding="utf-8")
    wav_file = scratch / f"{index}.wav"
    clip = output / f"{index}.mp3"
    subprocess.run(
        ["flite", "-voice", "slt", "-f", str(text_file), "-o", str(wav_file)],
        check=True,
    )
    subprocess.run(
        ["lame", "--quiet", "-m", "m", "-b", "32", str(wav_file), str(clip)],
        check=True,
    )
    text_file.unlink()
    wav_file.unlink()
    if clip.stat().st_size < 512:
        raise ValueError(f"Empty pronunciation clip for row {index}: {word}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not shutil.which("flite") or not shutil.which("lame"):
        parser.error("Flite and LAME are required")

    words = read_words(args.html)
    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="cet6-audio-") as scratch:
        with ThreadPoolExecutor(max_workers=args.workers) as workers:
            for _ in workers.map(
                lambda row: make_clip(row, args.output, Path(scratch)), enumerate(words)
            ):
                pass
    print(f"Generated {len(words)} US-English MP3 pronunciation clips.")


if __name__ == "__main__":
    main()
