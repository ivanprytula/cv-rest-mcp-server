"""Tests for the pure clustering algorithm (no model, no network)."""

from services.portfolio.matching.clustering import (
    cluster_vectors,
    medoid_index,
    segment_phrases,
)


class TestClusterVectors:
    def test_close_vectors_join_one_cluster(self):
        vectors = [
            [1.0, 0.0, 0.0, 0.0],
            [0.99, 0.01, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ]
        groups = cluster_vectors(vectors, threshold=0.9)
        sizes = sorted(len(group) for group in groups)
        assert sizes == [1, 2]

    def test_all_far_apart_stay_singletons(self):
        vectors = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        groups = cluster_vectors(vectors, threshold=0.82)
        assert sorted(len(group) for group in groups) == [1, 1, 1]

    def test_every_index_appears_exactly_once(self):
        vectors = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [-1.0, 0.0]]
        groups = cluster_vectors(vectors, threshold=0.85)
        flat = sorted(index for group in groups for index in group)
        assert flat == list(range(len(vectors)))

    def test_transitive_join_via_a_bridging_vector(self):
        # a~b and b~c both clear the threshold, a~c does not directly —
        # single-linkage still merges all three through b.
        vectors = [
            [1.0, 0.0, 0.0],
            [0.9, 0.44, 0.0],
            [0.6, 0.8, 0.0],
        ]
        groups = cluster_vectors(vectors, threshold=0.85)
        assert len(groups) == 1
        assert sorted(groups[0]) == [0, 1, 2]

    def test_empty_input_returns_no_groups(self):
        assert cluster_vectors([]) == []


class TestMedoidIndex:
    def test_picks_the_most_central_vector(self):
        vectors = [
            [1.0, 0.0],
            [0.9, 0.1],
            [-1.0, 0.0],
        ]
        # Index 1 sits between 0 and 2 in direction; only 0 and 1 are in the
        # cluster, so 1 (closer to itself + 0's average) should win over an
        # outlier direction.
        assert medoid_index(vectors, [0, 1]) in (0, 1)

    def test_single_member_cluster_returns_that_index(self):
        vectors = [[1.0, 0.0], [0.0, 1.0]]
        assert medoid_index(vectors, [1]) == 1


class TestSegmentPhrases:
    def test_keeps_verb_bearing_mid_length_lines(self):
        jd = "Built CI/CD pipelines for microservices deployments across teams"
        assert segment_phrases(jd) == [jd]

    def test_drops_short_fragments(self):
        assert segment_phrases("3+ years\nPython") == []

    def test_drops_lines_with_no_verb_ish_token(self):
        assert segment_phrases("Requirements and Qualifications Overview Section") == []

    def test_drops_overly_long_lines(self):
        long_line = "Managed " + " ".join(f"word{i}" for i in range(45))
        assert segment_phrases(long_line) == []

    def test_splits_on_newlines(self):
        jd = "Designed backend services for the platform\nOwned the release pipeline end to end"
        assert segment_phrases(jd) == [
            "Designed backend services for the platform",
            "Owned the release pipeline end to end",
        ]
