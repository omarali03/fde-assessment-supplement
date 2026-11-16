# Assumptions and decisions

Each rule that affects a ranking or a next action has a status:

- **Decided:** confirmed by the client in the Nov 12 reply to my discovery questions.
- **Assumed:** my default where nothing was specified. It's configurable.
- **Open:** needs a client decision. Shown in the app's open-decisions panel.

| # | Decision | Status | What the product does | Why |
|---|---|---|---|---|
| 1 | J1 account-manager note (1 year OK, HCHB trainable) | Decided | Scores candidates against both the **published** and the **proposed** requirements. Anyone who meets only the proposed version is **Conditional**, labeled "pending facility confirmation" | The note isn't an approved change, but hiding it would hide real candidates. Both versions stay visible |
| 2 | Newer messages vs. stale structured fields | Decided | The newest candidate statement is used as evidence, and the older field and the conflict stay visible. Field updates are suggested for recruiter review and never written back | Alex's "Oregon only" field is from March, and his Nov 6 message says Spokane. Recruiters need to see both |
| 3 | Drew's no-contact request | Decided | Drew is blocked from any outreach action until 2027-01-15, even though `contact_allowed=true`. Suggested update: set the field to false | An explicit request from the candidate outranks a stale field |
| 4 | R01–R12 near-identical profiles | Decided | Records are kept separate and badged "possible duplicate – unconfirmed". They're never merged | Identical text doesn't prove they're the same person. To merge I'd need a matching license number, phone, name plus date of birth, or the candidate's own confirmation. Until then the shortlist may overstate how many distinct people are available, and recruiters should avoid contacting several of the profiles about the same job |
| 5 | Pay and start-date mismatches | Decided | Shown as a mismatch, leading to Needs clarification and a question for the account manager. No exception is assumed (`confirmed_exceptions` is empty) | A possibly negotiable gap isn't the same as an approved exception |
| 6 | Dayton one-day coverage | Decided (kept open) | Availability is shown per day. A job-level open question always appears: "would the facility accept one-day coverage?" | The facility hasn't confirmed it (J2-NOTE-01) |
| 7 | "Placed" status | Decided | Placed means availability is unknown, neither available nor unavailable. The candidate is routed to the owning recruiter (Casey → R3) | Placed doesn't show which days are taken (DISC-03). The owner confirms the schedule |
| 8 | Self-reported licenses | Decided | Labeled "self-reported, unverified". The shortlist is provisional, not cleared for submission | No verification data was supplied |
| 9 | Setting experience (home health vs. outpatient) | Decided | Only described work in a résumé, note or message counts as **demonstrated**. An ATS skill tag is **stated (listed only)**: it can't meet a requirement and always generates a question. Missing evidence is **not demonstrated**, which is different from **confirmed absent** | A label doesn't show the actual setting (DISC-01). Testing caught a stale ATS tag giving Alex false outpatient credit |
| 10 | A recommendation isn't permission | Decided | Every action carries "Recommendation only – not authorization to contact or submit" | DISC-05 |
| 11 | Evidence lineage | Assumed | A résumé rendition, or a note repeating a message, counts as one piece of evidence | The packet README says these aren't independent |
| 12 | Ties | Assumed | Scores within the configured tie margin are shown as tied. Explicit tie-breakers come from config. Protected attributes (name, age, gender, race, email, date of birth) are rejected | Avoids false precision between near-identical candidates (R01–R03) |
| 13 | Source precedence | **Open** | Default: the newest evidence wins | DISC-06. The client may want some sources to always win for some fields |
| 14 | Freshness windows | **Open** | No expiry window is applied. Division B uses freshness as a tie-breaker | Known issue: that tie-breaker rewards *any* new evidence, including bad news (Alex's later start date moved him up) |
| 15 | Weights and thresholds | **Open** | Illustrative values in `configs/default.yaml` and `configs/division_b.yaml` | No outcome data to tune against yet |
| 16 | Who approves requirement changes | **Open** | Proposed changes are shown as pending and never applied as published | DISC-02 |
| 17 | Does "no restriction recorded" mean OK to contact? | **Open** | Default: contact is allowed, with the recommendation-only notice | Needs an operations decision |
| 18 | Should pay or start date ever hard-block a candidate? | **Open** | Default: never. Mismatches lead to Needs clarification | Needs a decision per division |