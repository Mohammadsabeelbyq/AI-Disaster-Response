"""FAISS / semantic-search module (folder is NOT named `faiss` on purpose: that would shadow
the real `faiss` library on import).

Nothing in the incident-submission code imports this package. A future feature calls it:

    from app.faiss_search import service
    service.add_report(report.id, report.searchable_text)
    service.search("water entering houses near the road", k=5)   # -> [(report_id, score), ...]
    service.rebuild(db_reports)                                  # e.g. after bulk import

Files:  embeddings.py = text -> vector   |   index.py = FAISS index + save/load
        service.py    = the only API other code should call
"""
