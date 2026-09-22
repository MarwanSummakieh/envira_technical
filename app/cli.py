"""Print one asset's exposure as the same JSON returned by the HTTP service."""
import argparse
import os
from pathlib import Path
import sys

from app.data import load_source_tables, prepare_data
from app.main import ExposureResponse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_id", help="Asset ID from assets.csv")
    parser.add_argument(
        "--data-dir", type=Path, default=Path(os.environ.get("ENVIRA_DATA_DIR", "data")),
        help="CSV directory (default: ENVIRA_DATA_DIR, or ./data)",
    )
    args = parser.parse_args(argv)
    try:
        prepared = prepare_data(load_source_tables(args.data_dir))
        try:
            exposure = prepared.exposure(args.asset_id)
        except KeyError:
            print(f"Error: Unknown asset {args.asset_id}", file=sys.stderr)
            return 2
        response = ExposureResponse.model_validate(exposure)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(response.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
