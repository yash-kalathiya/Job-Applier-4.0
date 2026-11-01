"""Local BGE embeddings; similarity is not calibrated confidence."""
import os


class SemanticMatcher:
    def __init__(self, bank, cache_dir, threshold=0.82, margin=0.06, local_only=True):
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        from fastembed import TextEmbedding
        import numpy as np
        self.np = np
        self.threshold, self.margin = threshold, margin
        self.model = TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir=cache_dir,
                                   threads=2, local_files_only=local_only)
        self.entries = [(e, alias) for e in bank['questions'] for alias in e['aliases']]
        self.vectors = np.array(list(self.model.embed([a for _, a in self.entries])))
        self.vectors /= np.maximum(np.linalg.norm(self.vectors, axis=1, keepdims=True), 1e-12)
        self.query_cache = {}

    def rank(self, question, bank):
        from .engine import eligible
        text = question['text']
        if text not in self.query_cache:
            vector = self.np.array(list(self.model.embed([text]))[0])
            self.query_cache[text] = vector / max(float(self.np.linalg.norm(vector)), 1e-12)
        scores = self.vectors @ self.query_cache[text]
        best = {}
        for (entry, alias), score in zip(self.entries, scores):
            key = entry['fact']
            if not eligible(question, entry):
                continue
            if key not in best or score > best[key]['score']:
                best[key] = {'fact_key': key, 'score': round(float(score), 6), 'alias': alias}
        return sorted(best.values(), key=lambda item: (-item['score'], item['fact_key']))
