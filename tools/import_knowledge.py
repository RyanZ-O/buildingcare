"""Import the supplied Neo4j CSV to an audited local graph snapshot (not Gephi)."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.kg import import_table

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('csv', type=Path)
    parser.add_argument('--output', type=Path, default=Path('data/causal-graph.json'))
    args = parser.parse_args()
    document = import_table(args.csv)
    if document['audit']['errors']:
        raise SystemExit(json.dumps(document['audit'], indent=2))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    args.output.with_name('causal-graph-audit.json').write_text(json.dumps(document['audit'], ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(document['audit'], indent=2))
