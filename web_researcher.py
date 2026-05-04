from ddgs import DDGS


class Researcher:
    def __init__(self, max_results_per_query: int = 3):
        self.max_results = max_results_per_query

    def research(self, queries: list[str]) -> list[dict]:
        results = []
        for query in queries:
            try:
                with DDGS() as ddgs:
                    hits = list(ddgs.text(query, max_results=self.max_results))
                results.append({"query": query, "hits": hits})
            except Exception as e:
                print(f"[researcher] '{query}' → {e}")
                results.append({"query": query, "hits": []})
        return results
