import argparse
from pathlib import Path
from .schema import counts, read_records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    rows = read_records(args.path)
    print(f"Schema validated: {len(rows)} records; class counts: {counts(rows)}")
    if not rows:
        print("No labels yet. This is expected until human annotation begins.")


if __name__ == "__main__":
    main()
