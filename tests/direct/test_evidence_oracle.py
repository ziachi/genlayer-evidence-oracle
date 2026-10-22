import json

C = "contracts/evidence_oracle.py"
URL_A = "https://www.bbc.com/news/result"
URL_B = "https://www.reuters.com/world/result"
QUOTE_A = "Team Garuda won the final 2-1 on Sunday"
QUOTE_B = "The final was postponed due to heavy rain"
T0 = "2026-10-20T00:00:00Z"


def hexa(a):
    from genlayer.py.types import Address
    return a.as_hex if hasattr(a, "as_hex") else Address(a).as_hex


def setup(vm, deploy, alice, bob, carol):
    c = deploy(C)
    vm.warp(T0)
    vm.sender, vm.value = alice, 100
    qid = c.ask("Did Team Garuda win the 2026 final?", "YES if they won the final match.",
                ["bbc.com", "reuters.com"], 3600, 50)
    vm.sender, vm.value = bob, 50
    c.propose(qid, "YES", URL_A, QUOTE_A)
    return c, qid


def dispute(vm, c, qid, carol):
    vm.sender, vm.value = carol, 50
    c.dispute(qid, URL_B, QUOTE_B)
    vm.value = 0


def pages(vm, a, b):
    vm.mock_web(r".*bbc\.com.*", {"status": 200, "body": a})
    vm.mock_web(r".*reuters\.com.*", {"status": 200, "body": b})


def test_undisputed_settles_without_llm(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, qid = setup(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie)
    direct_vm.value = 0
    with direct_vm.expect_revert("dispute window still open"):
        c.settle(qid)
    direct_vm.warp("2026-10-20T01:00:01Z")
    c.settle(qid)
    assert c.get_question(qid)["status"] == "SETTLED"
    assert c.get_claimable(hexa(direct_bob)) == 150


def test_input_rules(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, qid = setup(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie)
    direct_vm.sender, direct_vm.value = direct_charlie, 50
    with direct_vm.expect_revert("url not in allowed domains"):
        c.dispute(qid, "https://evilbbc.com/x", QUOTE_B)
    with direct_vm.expect_revert("bond must match"):
        direct_vm.value = 49
        c.dispute(qid, URL_B, QUOTE_B)
    direct_vm.sender, direct_vm.value = direct_bob, 50
    with direct_vm.expect_revert("cannot dispute yourself"):
        c.dispute(qid, URL_B, QUOTE_B)
    direct_vm.warp("2026-10-20T02:00:00Z")
    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("dispute window closed"):
        c.dispute(qid, URL_B, QUOTE_B)


def test_dispute_lost_by_disputer(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, qid = setup(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie)
    dispute(direct_vm, c, qid, direct_charlie)
    pages(direct_vm, f"Sports. {QUOTE_A}. Fans celebrated.", "Old article. Rain forecast.")
    direct_vm.mock_llm(r".*settle a YES/NO.*", json.dumps({"verdict": "YES", "cited_quote": QUOTE_A}))
    assert c.resolve(qid) == "YES"
    q = c.get_question(qid)
    assert q["status"] == "SETTLED" and q["answer"] == "YES" and q["note"] == QUOTE_A
    assert c.get_claimable(hexa(direct_bob)) == 200
    assert c.get_claimable(hexa(direct_charlie)) == 0


def test_dispute_won_by_disputer(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, qid = setup(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie)
    dispute(direct_vm, c, qid, direct_charlie)
    pages(direct_vm, "Preview: who will win the final?", f"{QUOTE_B}. No winner yet.")
    direct_vm.mock_llm(r".*settle a YES/NO.*", json.dumps({"verdict": "NO", "cited_quote": QUOTE_B}))
    assert c.resolve(qid) == "NO"
    assert c.get_claimable(hexa(direct_charlie)) == 200


def test_hallucinated_citation_becomes_unresolvable(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, qid = setup(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie)
    dispute(direct_vm, c, qid, direct_charlie)
    pages(direct_vm, f"{QUOTE_A}.", f"{QUOTE_B}.")
    direct_vm.mock_llm(r".*settle a YES/NO.*",
                       json.dumps({"verdict": "YES", "cited_quote": "Garuda lifted the trophy in front of 80,000 fans"}))
    assert c.resolve(qid) == "UNRESOLVABLE"
    q = c.get_question(qid)
    assert q["status"] == "OPEN"  # can be proposed again
    assert c.get_claimable(hexa(direct_bob)) == 50
    assert c.get_claimable(hexa(direct_charlie)) == 50


def test_fake_quote_loses_bond(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, qid = setup(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie)
    dispute(direct_vm, c, qid, direct_charlie)
    pages(direct_vm, "Nothing about the final here.", f"{QUOTE_B}.")
    direct_vm.mock_llm(r".*settle a YES/NO.*", json.dumps({"verdict": "UNRESOLVABLE", "cited_quote": ""}))
    assert c.resolve(qid) == "UNRESOLVABLE"
    assert c.get_claimable(hexa(direct_bob)) == 0
    assert c.get_claimable(hexa(direct_charlie)) == 100


def test_validator_rejects_leader_that_disagrees_with_its_view(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    c, qid = setup(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie)
    dispute(direct_vm, c, qid, direct_charlie)
    pages(direct_vm, f"{QUOTE_A}.", f"{QUOTE_B}.")
    direct_vm.mock_llm(r".*settle a YES/NO.*", json.dumps({"verdict": "YES", "cited_quote": QUOTE_A}))
    c.resolve(qid)
    assert direct_vm.run_validator() is True
    # leader claims a quote that this validator cannot find
    fake = {"verdict": "YES", "cited_quote": "made up sentence that is not there", "p_found": True, "d_found": True}
    assert direct_vm.run_validator(leader_result=fake) is False
    # leader lies about the deterministic quote check
    lie = {"verdict": "YES", "cited_quote": QUOTE_A, "p_found": False, "d_found": True}
    assert direct_vm.run_validator(leader_result=lie) is False
    # validator's own LLM reaches a different verdict
    direct_vm.clear_mocks()
    pages(direct_vm, f"{QUOTE_A}.", f"{QUOTE_B}.")
    direct_vm.mock_llm(r".*settle a YES/NO.*", json.dumps({"verdict": "UNRESOLVABLE", "cited_quote": ""}))
    assert direct_vm.run_validator() is False
    # leader crashed
    assert direct_vm.run_validator(leader_error=Exception("boom")) is False


def test_cancel_refunds_asker(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = direct_deploy(C)
    direct_vm.sender, direct_vm.value = direct_alice, 100
    qid = c.ask("Q?", "criteria", ["bbc.com"], 600, 10)
    direct_vm.value = 0
    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("only asker"):
            c.cancel(qid)
    c.cancel(qid)
    assert c.get_question(qid)["status"] == "VOID"
    assert c.get_claimable(hexa(direct_alice)) == 100
