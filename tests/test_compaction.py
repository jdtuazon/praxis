"""Compaction folds old runs into a digest, keeping the baseline + recent runs."""

from conftest import make_agent

from praxis.memory import Memory
from praxis.memory.signature import compute_signature
from praxis.platform.fake import FakeLinear


def test_compaction_folds_old_runs_but_keeps_baseline():
    mem = Memory(":memory:")
    instr = "Create a high-priority bug titled 'Boom' in Engineering"
    sig = compute_signature(instr)
    for _ in range(15):
        make_agent(mem, FakeLinear()).run(instr)
    assert mem.store.counts()["executions"] == 15

    baseline_before = mem.execution.first_run(sig)
    notes = mem.compactor.compact(keep_recent=5)

    assert notes, "interim runs should be folded into a digest"
    assert mem.store.counts()["executions"] < 15, "execution rows reduced"
    assert mem.compactor.digests(), "a digest summary was produced"

    # the learning baseline (first run of the signature) must survive
    baseline_after = mem.execution.first_run(sig)
    assert baseline_after is not None and baseline_after.id == baseline_before.id
