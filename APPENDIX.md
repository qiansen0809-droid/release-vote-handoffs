# Online appendix: evidence and replication

This companion to *Which Revision Did the Release Vote Cover?* documents the evidence behind a receiving maintainer's decision. Version `v1.0.0` accompanies the six-page submission. Run `python -B reproduce.py` from the repository root with Python 3.11 or later. The [replication guide](README.md) identifies the inputs to each public check and the procedure for retrieving underlying correspondence.

## What to record for one motion

| Field | Recording rule |
| --- | --- |
| Opening | Identify the invitation for the nominated repository, version and candidate. Keep its archive URL. A tag may exist even if a vote was never opened. |
| Closing | Record the opener's explicit collective result or enacted withdrawal for the same motion. Retain individual ballots, intentions and corrections as contextual evidence. |
| Dated source | Inspect the opening for a full source commit designated for this candidate. A signing fingerprint or a distribution checksum can have a similar appearance. Record an ambiguous attribution separately. |
| Observed references | Record the named candidate and final tags, their repository, peeled commits and observation time. A tag lookup describes the captured state. |
| Action | For a verified pass, compare the pair needed for the chosen question. Equal commits support reuse, unequal commits require review, and missing or conflicting evidence warrants deferral. A verified negative disposition on an identified motion rules out reuse. |

A current-tag request compares the candidate and final refs as observed. A conflicting dated source claim makes the binding uncertain. A historical-source request asks whether the final ref reaches the commit explicitly designated in the opening. A historical decision can remain possible after the candidate tag disappears.

## Worked example: Hudi 0.15.0 RC3

The manager opened a vote on RC3 and later announced that it passed. The opening identifies a candidate tag and a signing-key fingerprint. It provides no unambiguous full Git commit for the voted source. [Opening](https://www.mail-archive.com/dev@hudi.apache.org/msg05418.html) · [Closing](https://www.mail-archive.com/dev@hudi.apache.org/msg05430.html)

The candidate tag resolved to `d0df1d4a94d13cfc061faaf1a9573c886811c104`. The final tag resolved to `38832854be37cb78ad1edd87f515f01ca5ea6a8a`. Their difference is one release-version update affecting 83 Maven POM files. Under strict source identity the current-tag decision is **Review**. The historical-source decision is **Defer** pending a dated source designation. The responsible maintainer can inspect the intervening change. [Commit comparison](https://github.com/apache/hudi/compare/d0df1d4a94d13cfc061faaf1a9573c886811c104...38832854be37cb78ad1edd87f515f01ca5ea6a8a)

## What the denominators mean

| Analysis | Unit and interpretation |
| --- | --- |
| Incubator linkage | 48 notices in the test window, of which 44 had archive-supported reference openings. Direct archive links also helped define the reference. |
| Recovery development | 17 openings in seven release families. This panel informed development of the revised extractors. |
| First external panel | Seven openings in five projects. The first revision was frozen. Errors from this panel informed the second revision. |
| Final external panel | Eight openings in five other projects, including missed openings. The final revision linked seven and the earlier extractor linked three. Both recovered one correct determinate current-tag decision and zero historical-source decisions. |
| Coordination | 37 issues in the development families. Twenty-one had a response from a different participant and 13 had a further message documenting diagnosis, action or recheck. |
| Controlled handoffs | 21 complete requests and 42 single-fault variants, with eight additional negative-motion requests and variants. These test the behavior of the registered policy. |
