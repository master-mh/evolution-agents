from mitosis.genome import canonical_genome_json, compute_genome_hash
from mitosis.models import CellType


def test_same_cell_type_yields_same_hash():
    a = compute_genome_hash(canonical_genome_json(CellType.EXPLORER))
    b = compute_genome_hash(canonical_genome_json(CellType.EXPLORER))
    assert a == b


def test_different_cell_types_yield_different_hashes():
    a = compute_genome_hash(canonical_genome_json(CellType.EXPLORER))
    b = compute_genome_hash(canonical_genome_json(CellType.BUILDER))
    assert a != b


def test_hash_is_sha256_hex():
    h = compute_genome_hash(canonical_genome_json(CellType.AUDITOR))
    assert len(h) == 64
    int(h, 16)  # raises if not valid hex
