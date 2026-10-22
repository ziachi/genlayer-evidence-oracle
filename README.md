# EvidenceOracle

An optimistic YES/NO oracle for GenLayer. Anyone can answer a question by posting a bond and a quote from a trusted site. If nobody disputes it before the deadline, it settles with no LLM call at all. If someone disputes it, validators fetch both evidence pages and decide.

The idea: most answers are uncontroversial, so consensus only needs to run on disputes. That makes it cheap enough to use as a building block for prediction markets, insurance payouts, bounties, or anything that pays out based on a real-world fact.

## Flow

```
ask(text, criteria, domains, liveness, min_bond)   + reward
  -> propose(qid, YES|NO, url, quote)              + bond
       -> no dispute before deadline -> settle()   (deterministic)
       -> dispute(qid, url, quote)                 + same bond
            -> resolve()                           (web + LLM consensus)
withdraw()                                          pull payments
```

| Verdict | Payout |
|---|---|
| matches proposer | proposer gets both bonds + reward |
| matches disputer | disputer gets both bonds + reward |
| UNRESOLVABLE | both refunded, question goes back to OPEN. If only one side's quote is not on its page, that side loses its bond to the other |

## Consensus

`resolve()` uses `gl.vm.run_nondet_unsafe` with a custom validator instead of a generic equality check. The validator:

1. Fetches both evidence pages itself.
2. Re-runs the quote checks (is each side's quote really on its page?). These are deterministic string checks, so they must match the leader exactly.
3. Checks that the leader's `cited_quote` exists in the validator's own copy of the pages. A YES/NO verdict without a real supporting sentence is rejected.
4. Runs its own LLM judgement and compares only the `verdict` field. Free text is ignored, so wording differences between models don't break consensus.

The leader applies the same citation rule to itself: if the model can't point to a sentence that exists, the verdict becomes UNRESOLVABLE.

## Design notes

- Evidence URLs must be `https` and on the asker's domain allowlist (subdomains allowed, `evilbbc.com` is not `bbc.com`).
- Dispute bond must equal the proposer's bond, so both sides risk the same.
- Page text is wrapped in tags and the prompt treats it as data, not instructions. Domain allowlist + citation check limit what a malicious page can do.
- Balances are credited to `claimable` and paid out with `withdraw()`, never pushed inside resolution logic.
- Times come from the transaction timestamp, so `settle`/`dispute` deadlines are deterministic.

## Run

```bash
pip install -r requirements.txt
genvm-lint check contracts/evidence_oracle.py
pytest tests/direct -v
```

Tests run in GenLayer direct mode with mocked web + LLM. They cover the no-dispute path, input rules, both dispute outcomes, hallucinated citations, fake quotes, and the validator itself (`run_validator`) rejecting a leader that lies about quote checks, cites missing text, or disagrees on the verdict.

## Limitations

- Binary questions only. Multi-outcome would need a different payout table.
- Pages that change between leader and validator fetches can cause a disagreement. GenLayer's appeal process covers that.
- `withdraw()` uses a native transfer, which direct mode can't simulate. Test it on Studio.
