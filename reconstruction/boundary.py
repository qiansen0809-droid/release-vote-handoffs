"""Fixed boundary examples for checking how the frozen extractor handles evidence roles."""
import copy
import hashlib
import json
from pathlib import Path
import infer


def example():
    commit="a"*40
    ref="v1.0.0-RC1"
    final="v1.0.0"
    base="https://github.com/example/widget"
    m=dict(sender="Release manager",date="2024-01-01",subject="[VOTE] Release 1.0.0 RC1",url="mail:opening",
           body="Please vote on this candidate. Tag: "+base+"/tree/"+ref+"\nThe commit hash: "+commit)
    z=dict(sender="Release manager",date="2024-01-03",subject="Re: "+m["subject"],url="mail:conclusion",
           body="The vote has passed.")
    return dict(project="example/widget",version="1.0.0",repository="example/widget",final_tag=final,
                messages=[m,z],tag_observation=dict(queried=base+".git",observed_utc="2024-02-01T00:00:00Z"),
                tags={n:dict(url=base+"/tree/"+n,commit=commit) for n in [ref,final]})


def check():
    original=example()
    d=("Defer","Defer")
    cases=[]
    for name, expected in [
        ("complete",("Reuse","Reuse")),("future_date",d),("wrong_sender",d),("different_rc",d),
        ("quoted_positive",d),("conditional_positive",d),("ballot_only",d),("planned_replacement",d),
        ("conflicting_conclusions",d),("duplicate_openings",d),("foreign_candidate",d),
        ("candidate_ref_missing",("Defer","Reuse")),("final_ref_missing",d),
        ("withdrawn_missing_refs",("DoNotReuse","DoNotReuse")),("moved_candidate",("Defer","Reuse")),
        ("commit_in_fingerprint",("Reuse","Defer")),("contradictory_dated_hashes",d),
        ("wrong_git_repository",d)]:
        family=copy.deepcopy(original)
        opener,close=family["messages"]
        if name=="future_date": opener["date"]="2024-01-10"
        if name=="wrong_sender": close["sender"]="Another contributor"
        if name=="different_rc": close["subject"]=close["subject"].replace("RC1","RC2")
        if name=="quoted_positive": close["body"]="Thank you.\n> The vote has passed."
        if name=="conditional_positive": close["body"]="If the vote has passed we should release."
        if name=="ballot_only": close["body"]="+1 (binding). I have verified the release."
        if name=="planned_replacement": close["body"]="I will prepare the next candidate."
        if name=="conflicting_conclusions": family["messages"].append(dict(close,url="mail:other",body="I cancel this vote."))
        if name=="duplicate_openings": family["messages"].append(dict(opener,url="mail:duplicate"))
        if name=="foreign_candidate": opener["body"]=opener["body"].replace("example/widget","unrelated/widget")
        if name=="candidate_ref_missing": del family["tags"]["v1.0.0-RC1"]
        if name=="final_ref_missing": del family["tags"]["v1.0.0"]
        if name=="withdrawn_missing_refs":
            family["tags"].clear()
            close["body"]="I cancel this vote."
        if name=="moved_candidate": family["tags"]["v1.0.0-RC1"]["commit"]="b"*40
        if name=="commit_in_fingerprint": opener["body"]=opener["body"].replace("The commit hash:","Signing key fingerprint:")
        if name=="contradictory_dated_hashes": opener["body"]+="\nThe commit hash: "+"c"*40
        if name=="wrong_git_repository": family["tag_observation"]["queried"]="https://github.com/other/widget.git"
        report=infer.family_report(family)
        row=next(x for x in report["motions"] if x["rc"]==1)
        actual=tuple(row[s]["action"] for s in infer.REQUIRED)
        assert actual==expected,(name,actual,expected)
        cases.append(dict(check=name,actions=list(actual)))
    return cases


if __name__=="__main__":
    print(json.dumps(check(),indent=2))

