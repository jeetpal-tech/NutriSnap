from app.core.database import seed
from app.core.knowledge_base import KnowledgeBase

if __name__ == "__main__":
    kb = KnowledgeBase()
    kb.load()
    seed(kb)
    print("NutriSnap database initialized and seeded.")
