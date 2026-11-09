import collections

from inkfall.gold import load_gold, validate_gold


def test_corpus_size_and_shape(corpus):
    assert len(corpus) >= 40
    assert {d.tenant for d in corpus} == {"lanternfield", "corvane", "pellmoor"}
    assert sum(1 for d in corpus if d.amends) >= 6
    assert sum(1 for d in corpus if d.version > 1) >= 6
    assert sum(1 for d in corpus if "injection-fixture" in d.tags) >= 6
    assert sum(1 for d in corpus if "contradiction" in d.tags) >= 6


def test_gold_questions_valid(corpus, directory):
    qs = load_gold()
    assert len(qs) >= 100
    assert validate_gold(qs, corpus, directory) == []
    cats = collections.Counter(q.category for q in qs)
    assert cats["injection"] + cats["permission"] >= 20
    for c in ("single_hop", "multi_hop", "numeric", "temporal", "contradiction", "abstain"):
        assert cats[c] >= 9, c
