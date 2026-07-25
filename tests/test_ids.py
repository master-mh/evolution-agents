import re
import uuid

import pytest

from mitosis import ids

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@pytest.fixture(autouse=True)
def _reset_generator():
    ids.reset()
    yield
    ids.reset()


def test_default_generator_produces_distinct_uuid4_shaped_strings():
    a, b = ids.new_id(), ids.new_id()
    assert a != b
    assert UUID_RE.match(a)
    assert UUID_RE.match(b)
    assert uuid.UUID(a).version == 4


def test_seed_is_deterministic_across_separate_calls():
    ids.seed(123)
    first = [ids.new_id() for _ in range(5)]
    ids.seed(123)
    second = [ids.new_id() for _ in range(5)]
    assert first == second


def test_different_seeds_diverge():
    ids.seed(1)
    a = ids.new_id()
    ids.seed(2)
    b = ids.new_id()
    assert a != b


def test_seed_output_is_still_uuid4_shaped():
    ids.seed(7)
    generated = ids.new_id()
    assert UUID_RE.match(generated)
    assert uuid.UUID(generated).version == 4


def test_reset_returns_to_random_generation():
    ids.seed(9)
    seeded_value = ids.new_id()
    ids.reset()
    ids.new_id()  # consume a random id; must not affect what re-seeding replays below
    ids.seed(9)
    replay = ids.new_id()
    assert seeded_value == replay


def test_seeded_context_manager_scopes_and_restores():
    ids.reset()
    before = ids.new_id()
    with ids.seeded(55):
        inside_first = ids.new_id()
    with ids.seeded(55):
        inside_second = ids.new_id()
    after = ids.new_id()

    assert inside_first == inside_second
    assert before != inside_first
    assert after != inside_first


def test_seeded_context_manager_restores_a_prior_seed_not_just_random():
    ids.seed(1)
    outer_first = ids.new_id()
    with ids.seeded(2):
        ids.new_id()
    outer_second = ids.new_id()

    ids.seed(1)
    ids.new_id()  # replay outer_first
    replay_outer_second = ids.new_id()

    assert outer_second == replay_outer_second
