from app.core.database import demo_queries

if __name__ == "__main__":
    for query in demo_queries():
        print(f"\n## {query['title']}")
        for row in query["rows"]:
            print(row)
