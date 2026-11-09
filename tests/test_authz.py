from inkfall.authz import DocACL, decide


def u(directory, name):
    return directory.users[name]


def test_same_tenant_group_and_clearance_allows(directory):
    d = decide(u(directory, "dana.whitcombe"), DocACL("corvane", "confidential", ("cv-procurement",)), directory)
    assert d.allowed and any("shared ACL group" in r for r in d.reasons)


def test_other_tenant_always_denied_even_with_matching_labels(directory):
    # a restricted partner at Lanternfield cannot read a public Corvane doc whose group list is spoofed
    d = decide(u(directory, "marcus.oyelaran"), DocACL("corvane", "public", ("lf-all", "cv-all")), directory)
    assert not d.allowed and d.reasons == ("different tenant",)


def test_clearance_below_classification_denied(directory):
    assert not decide(u(directory, "june.park"), DocACL("corvane", "confidential", ("cv-all",)), directory).allowed


def test_no_shared_group_denied(directory):
    assert not decide(u(directory, "omar.haddad"), DocACL("corvane", "internal", ("cv-ops",)), directory).allowed


def test_ethical_wall_wins_over_group_and_clearance(directory):
    acl = DocACL("lanternfield", "confidential", ("lf-litigation",), ("theo.brandt",))
    assert not decide(u(directory, "theo.brandt"), acl, directory).allowed
    assert decide(u(directory, "marcus.oyelaran"), acl, directory).allowed


def test_deleted_and_unknown_label_fail_closed(directory):
    assert not decide(u(directory, "omar.haddad"), DocACL("corvane", "public", ("cv-all",), deleted=True), directory).allowed
    assert not decide(u(directory, "omar.haddad"), DocACL("corvane", "top-secret", ("cv-all",)), directory).allowed


def test_admin_role_grants_no_content_access(directory):
    acl = DocACL("pellmoor", "restricted", ("pm-board",))
    assert not decide(u(directory, "pm.admin"), acl, directory).allowed
    assert decide(u(directory, "nadia.voss"), acl, directory).allowed
