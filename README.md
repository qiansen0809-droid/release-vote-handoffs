# Which Revision Did the Release Vote Cover?

Replication materials for the paper by Sen Qian and Yun Xing, Hohai University.

A maintainer taking over a release may need to answer two questions. Do the candidate and final tags point to the same commit at inspection? Does the final tag point to the source that the proposer identified when voting opened? In Hudi 0.15.0 RC3, the two tags pointed to different commits at inspection. The opening named the candidate tag and gave a signing-key fingerprint. To establish the vote-time commit, the maintainer would need a dated source designation. The [worked Hudi example](APPENDIX.md) links the invitation, result and Git comparison.

## Reproduce the results

From the repository root, run the following with Python 3.11 or later and SQLite JSON support. The default run works offline with the Python standard library.

~~~shell
python -B reproduce.py
~~~

| Paper result | Where to look |
| --- | --- |
| Table I. Trace a result notice to its invitation | [Notice records](data/notice_linkage.csv). The April–December 2025 window contains 48 notices. |
| Table II. Compare current tags and historical source | [Opening-level judgments](data/reference_openings.csv). Select the rows marked `panel1` or `panel2` for the 15 motions across ten projects. The [source catalog](data/family_sources.json) gives the mail links and dated Git observations. |
| Table III. Inspect the Kafka handoff | The [receipt verifier](validated/validated_receipt.py) checks both requested revisions. The [replay inputs](receipt/cases.json) and [SQLite rule](validated/decision.sql) are included. |

The default run reads the recorded source judgments and recomputes the summaries. It also replays the controlled handoff decisions. The [evidence rules](scope/rule.md) and the sampling protocols for [panel 1](prospective/protocol.json) and [panel 2](prospective2/protocol.json) document how to interpret the rows. The [archived extractor outputs](data/recovery_predictions.csv) can be matched to the judgments by opening URL and source question.

## Rebuild release-family decisions from public mail

The [source catalog](data/family_sources.json) records the 250 public message URLs across the 17 families, a SHA-256 fingerprint of each original message body, the observed Git refs, and their observation dates. Sender labels have meaning only within a family. The Git observations are frozen so that later tag changes do not alter historical results. The repository links to original correspondence and stores its derived observations. The following command retrieves the original bodies to a local, Git-ignored directory.

~~~shell
python -m pip install beautifulsoup4
python -B hydrate.py --project hudi
python -B reproduce.py --captures local-captures --project hudi
~~~

To run both frozen revisions over every family, replace the last two commands with the following.

~~~shell
python -B hydrate.py --all
python -B reproduce.py --captures local-captures
~~~

The raw replay checks the fingerprints and both revisions' predicted actions for every selected opening, including missing outputs. It stops on an unavailable or changed source. The no-argument replay remains usable offline in that case. To inspect the destination decision for Hudi 0.15.0, run these separate questions against the same opening.

~~~shell
python -B handoff.py local-captures/hudi.json https://www.mail-archive.com/dev@hudi.apache.org/msg05418.html current-tags
python -B handoff.py local-captures/hudi.json https://www.mail-archive.com/dev@hudi.apache.org/msg05418.html dated-source
~~~

The first command emits **Review** with the different Git commits observed at capture. The second emits **Defer** and requests a dated source designation. The output includes the message URLs and next owner. To examine a constructed receipt separately, run the following.

~~~shell
python -B validated/validated_receipt.py lookup kafka 3.9.0 3.9.1
~~~

## Rebuild the Incubator notice analysis

The [monthly source manifest](data/incubator_months.json) records the original mailbox SHA-256 hashes and URLs for December 2024 through December 2025. The commands below retrieve those public Apache mailboxes and generate local working files. The subject-based methods and direct-thread method both use the original correspondence. The Git comparison uses the [archived observation](archive/git_snapshot.json).

~~~shell
python -B archive/collect.py
python -B archive/evaluate.py
python -B archive/resolve_tags.py
python -B archive/joint_check.py
python -B thread_first/replay.py
~~~

Compare the newly generated `archive/manifest.json` with the monthly source manifest if an aggregate differs. Later changes to public archive indexing or mailbox bytes can affect recollection. Public thread URLs in the notice rows allow individual records to be inspected directly. [Apache mailing-list archives](https://lists.apache.org/)

## Existing offline author packet

If you already hold the original author packet, use its extracted directory containing `portable/`, `cohort/`, `prospective/` and `prospective2/` in place of PACKET_ROOT. This reads the same recorded bodies locally. Then the public code replays the same extraction as the online route.

~~~shell
python -B hydrate.py --all --author-artifact PACKET_ROOT
python -B reproduce.py --captures local-captures
~~~

For the full historical pipeline available in that packet, run its own `python -B reproduce.py` from the packet root. The public release retains linked evidence and derived results while fetched correspondence stays in the reader's local working directory.
