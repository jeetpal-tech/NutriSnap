import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import seed
from app.core.knowledge_base import KnowledgeBase

if __name__ == "__main__":
    kb = KnowledgeBase()
    kb.load()
    seed(kb)
    print("NutriSnap database initialized and seeded.")
