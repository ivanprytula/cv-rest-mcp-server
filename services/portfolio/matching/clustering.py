"""Group paraphrased JD responsibility sentences that share no skill terms.

"Built CI/CD pipelines for microservices" and "Automated deployment workflows
across services" describe the same responsibility but share no content words
beyond stopwords — rapidfuzz scores them ~30 and the term-based gap model
(:mod:`gap`) never links them. Embeddings close that gap; skill *terms* are
deliberately never embedded here (short proper nouns like "Java"/"JavaScript"
embed as near-duplicates, which is strictly worse than the alias map).

Split in two so tests stay hermetic: :func:`embed_phrases` touches the model
and gets no unit test (a thin wrapper over a library call);
:func:`cluster_vectors` is pure and is what the tests exercise.
"""

from __future__ import annotations

import re

import numpy as np

from services.portfolio.matching.normalize import normalize_jd_text


_SEGMENT_BREAK = re.compile(r"[\n]+")

# "-ed"/"-ing" catch most regular past/present-participle verbs ("Owned",
# "Automating"). A bare "-s" plural (e.g. "Requirements") is deliberately
# excluded — it matches nouns far more often than verbs and would defeat the
# filter. Resume bullets lean heavily on irregular past-tense verbs the
# suffix rule can't reach ("Built", "Led", "Drove", "Wrote", "Grew", "Ran",
# "Sped", "Sold"), so those are listed explicitly alongside their present
# forms.
_VERBISH = re.compile(
    r"\b(\w+(?:ed|ing)"
    r"|build|builds|built|lead|leads|led|drive|drives|drove"
    r"|own|owns|design|designs|write|writes|wrote|manage|manages"
    r"|grow|grows|grew|run|runs|ran|speed|speeds|sped|sell|sells|sold)\b",
    re.IGNORECASE,
)

_MIN_WORDS = 5
_MAX_WORDS = 40


def segment_phrases(jd_text: str) -> list[str]:
    """Split a JD into responsibility-sentence candidates.

    Splits on newlines (bullets are already stripped by
    :func:`normalize_jd_text`), keeps 5-40 word segments, and drops segments
    with no verb-ish token — filtering section headers ("Requirements") and
    fragments ("3+ years") that would otherwise pollute the embedding set.
    """
    normalized = normalize_jd_text(jd_text)
    segments = []
    for raw_segment in _SEGMENT_BREAK.split(normalized):
        segment = raw_segment.strip().strip(".,;:")
        if not segment:
            continue
        word_count = len(segment.split())
        if not (_MIN_WORDS <= word_count <= _MAX_WORDS):
            continue
        if not _VERBISH.search(segment):
            continue
        segments.append(segment)
    return segments


def embed_phrases(phrases: list[str]) -> list[list[float]]:
    """Embed each phrase with the baked-in sentence model.

    Thin wrapper over `fastembed`; no unit test (nothing to assert beyond
    "the library ran"). :func:`cluster_vectors` is where the algorithm — the
    only part worth testing without a model — lives.
    """
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return [vector.tolist() for vector in model.embed(phrases)]


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return vectors / norms


def _find(parent: list[int], node: int) -> int:
    """Union-find root lookup with path compression — n is tiny (JD-sentence count)."""
    while parent[node] != node:
        parent[node] = parent[parent[node]]
        node = parent[node]
    return node


# ponytail: O(n^2) cosine matrix + union-find, ~20 lines. Swap for HDBSCAN
# only past ~5k phrases — a JD-scraping pipeline is nowhere close.
def cluster_vectors(
    vectors: list[list[float]], *, threshold: float = 0.82
) -> list[list[int]]:
    """Single-linkage agglomerative clustering over cosine similarity.

    Returns groups of indices into *vectors*. Two vectors join the same
    cluster (directly or transitively) when their cosine similarity meets
    *threshold*.

    Args:
        vectors: Embeddings to cluster; not required to be pre-normalized.
        threshold: Cosine-similarity cutoff for joining a pair. 0.82 is a
            starting point from eyeballing real JD sentences, not a derived
            constant — expect to move it between 0.78-0.88 once real
            clusters are visible.
    """
    if not vectors:
        return []
    normalized = _l2_normalize(np.array(vectors))
    similarity = normalized @ normalized.T

    parent = list(range(len(vectors)))
    rows, cols = np.triu_indices(len(vectors), k=1)
    for i, j in zip(rows.tolist(), cols.tolist(), strict=True):
        if similarity[i, j] >= threshold:
            root_i, root_j = _find(parent, i), _find(parent, j)
            if root_i != root_j:
                parent[root_i] = root_j

    groups: dict[int, list[int]] = {}
    for index in range(len(vectors)):
        groups.setdefault(_find(parent, index), []).append(index)
    return list(groups.values())


def medoid_index(vectors: list[list[float]], indices: list[int]) -> int:
    """The index (into *vectors*) whose vector is most central within *indices*.

    Used to label a cluster with a real JD sentence rather than a summary:
    the medoid is the phrase closest, on average, to every other phrase in
    its own cluster.
    """
    normalized = _l2_normalize(np.array([vectors[i] for i in indices]))
    totals = (normalized @ normalized.T).sum(axis=1)
    return indices[int(np.argmax(totals))]
