# What RAPTOR Actually Does (plain-English explainer)

> A jargon-free explanation for non-biologists — useful for pitching. For the technical
> validation rubric see `EVAL_RUBRIC.md`; for the evidence base see
> `reference/eval-rubric-evidence-base.md`.

## The problem, in one picture

Every person's DNA is a **3-billion-letter instruction book**. A **variant** is a typo in that book.
Most typos are harmless. A few break the instructions and cause disease.

For **Tuberous Sclerosis Complex (TSC)** — a serious genetic condition — the important typos sit in two
genes, **TSC1** and **TSC2**. Today there are **~6,700 TSC typos that nobody can yet call**: harmful or
harmless? They sit in a limbo bucket the field calls a **"Variant of Uncertain Significance" (VUS)**.
A patient with a VUS gets an answer of "we don't know" — which means no clear guidance on surveillance
or treatment.

**RAPTOR's job is to sort that limbo bucket** — turn "we don't know" into a defensible "likely harmful"
or "likely harmless," with a full audit trail for every call.

## Two kinds of typo — one easy, one hard

- **Truncating typo** — like ripping the last chapters out of the instruction book. Almost always
  breaks things. **Easy to call.** Most TSC is caused by this kind.
- **Missense typo** — swaps *one letter for another*. The book still reads, but the meaning might be
  subtly off. Could be harmful, could be fine. **Genuinely hard to call** — even for human experts.

The hard (missense) case is exactly where an automated, consistent, auditable engine earns its keep.

## Why you can trust the output: it is tested before it is trusted

RAPTOR is not allowed to touch the 6,700 unknowns until it **passes an exam on typos where the answer
is already known** — like making a new hire pass a test with an answer key before doing real casework.

Those "known-answer" typos come from public expert-reviewed databases. RAPTOR classifies them, we
compare to the known answers, and we measure how often it's right — **separately for the easy and hard
kinds**, because lumping them together would hide weakness on the hard ones.

## The honesty feature (the part regulators care about)

RAPTOR's rules and its accuracy bar are **fixed in advance and in writing**, *before* it sees the exam
answers — so it can never be quietly tuned to look good on the test. And if it doesn't have **enough
known examples to statistically prove** it's accurate on a given kind of typo, it **says so and
refuses** — rather than guessing and pretending. "Not enough evidence" is a first-class answer.

Grounded in the field's own standards: the ACMG/AMP guideline defines "Likely" calls as **>90%**
confidence and definitive calls as **>99%**. RAPTOR's bar is set to those same anchors, and every call
carries its reasoning and its sources.

## What that buys you

- **Consistency** — the same variant always gets the same call, with the same cited reasoning (unlike
  ad-hoc manual review that varies by analyst and by day).
- **Scale** — thousands of variants sorted, not a handful.
- **Auditability** — every decision is traceable to fixed rules, public evidence, and a pre-registered
  accuracy bar. Nothing is a black box.
- **Safety by design** — it validates before it runs, stratifies easy vs hard, and abstains when the
  evidence (or the statistical power) isn't there.

## One honest caveat we lead with, not hide

Because TSC is mostly caused by the *easy* (truncating) kind, nature simply hasn't left many
known-answer examples of the *hard* (missense) kind to test against. So RAPTOR is proven strongest on
the common cases and holds the hard cases to the same evidence bar — flagging for human review anything
it cannot prove. That candor is the point: an auditable engine tells you what it does and does not know.

## Where things stand today

RAPTOR has taken its first "exam" — the leakage-safe held-out test described above. The frozen counts
provide supportive post-hoc evidence for the truncating-pathogenic scope, while the hard missense
scopes did not have enough called examples to estimate performance. That truncating evidence is not
yet prospectively validated or authorized. We've re-described the same exam result more precisely,
separating "not enough evidence yet" from "actively failed," without generating new evidence. The
next real test — on a fresh, not-yet-published batch of known-answer typos — is registered but has not
happened yet, and RAPTOR does not sort any real unknowns for outside use until it clears that test.
