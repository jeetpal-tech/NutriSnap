import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import demo_queries

if __name__ == "__main__":
    for query in demo_queries():
        print(f"\n## {query['title']}")
        for row in query["rows"]:
            print(row)
