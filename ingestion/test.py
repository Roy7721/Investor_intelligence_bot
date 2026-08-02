from vector_store.vector_store import _client, _embedder

collection = _client.get_or_create_collection(name="investor_intelligence", embedding_function=_embedder)
print("Total chunks in collection:", collection.count())

# also pull a few real documents to see what's actually stored
# find the income statement chunk directly
all_tables = collection.get(where={"content_type": "table"}, limit=48)
for doc in all_tables["documents"]:
    if "391,035" in doc or "net income" in doc.lower():
        print("FOUND IT:")
        print(doc[:400])
        print("=" * 80)
