"""The intent-signature is the reuse key — it must collapse parameter variants
and keep structurally different tasks distinct."""

from praxis.memory import compute_signature


def test_parameter_variants_collapse():
    a = compute_signature("Create a high-priority bug titled 'X' in Engineering")
    b = compute_signature("File an urgent ticket in Design")
    assert a == b, "create-with-priority instructions should share a signature (transfer)"


def test_query_variants_collapse():
    a = compute_signature("Find all open issues with no assignee")
    b = compute_signature("list unassigned open bugs")
    assert a == b
    assert a.startswith("query"), "a find/list instruction is a query, not an update"


def test_aggregation_dominates_verb():
    # 'Create a digest' is an aggregation, not a create.
    assert compute_signature("Create a digest of issues grouped by assignee").startswith("aggregate")
    assert compute_signature("Roll up issues into a weekly digest").startswith("aggregate")


def test_structurally_different_tasks_differ():
    create = compute_signature("Create a bug in Engineering")
    create_assign = compute_signature("Create a bug in Engineering and assign it to me")
    assert create != create_assign, "adding an assignment changes the plan shape"


def test_grouping_keeps_distinct():
    by_pri = compute_signature("digest grouped by priority")
    by_asg = compute_signature("digest grouped by assignee")
    assert by_pri != by_asg


def test_add_a_comment_is_not_a_create():
    # 'add a comment' is a comment, not creating an issue.
    assert compute_signature("Add a comment to ENG-1 asking for an update").startswith("comment")
    # but 'add a dark mode toggle' (creating an issue) is still a create-ish action
    assert not compute_signature("Add a bug for the dark mode toggle").startswith("comment")
