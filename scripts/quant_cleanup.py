"""Inspect Quant storage. Only --apply-temporary reclaims terminal task inputs."""
import argparse
import json
from finance_analysis.quant.datasets.cleanup import cleanup_inputs, legacy_inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply-temporary', action='store_true')
    parser.add_argument('--legacy-inventory', action='store_true')
    args = parser.parse_args()
    result = legacy_inventory() if args.legacy_inventory else cleanup_inputs(dry_run=not args.apply_temporary)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
