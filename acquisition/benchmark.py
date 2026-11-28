"""Replay same-policy extraction costs with every motion held out in turn."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations, product
from pathlib import Path
import json
import sys

from acquire import Block, ORDER, Planner, Provider, check, feasible, minimal_support

HERE = Path(__file__).resolve().parent
ART = HERE.parent
sys.path.insert(0,str(ART/"validated"))
from evaluate import FAULTS, damaged
from registry import load, registry as get_registry, request
from sql_baseline import decide as sql_decide


@dataclass
class Case:
    motion: str
    group: str
    name: str
    reference: str
    provider: Provider
    blocks: dict


def fixtures(skip_motion=None, with_sql=True):
    db = get_registry()
    originals = load(ART/"receipt"/"cases.json")
    motions = list(dict.fromkeys(c["motion"] for c in originals))
    rows = []
    def add(group, name, archive, packet):
        provider = Provider(archive,packet)
        blocks = {k:provider.read(k) for k in ORDER} if provider.envelope().status == "valid" else {}
        reference = sql_decide(archive,packet) if with_sql else None
        rows.append(Case(packet["motion"],group,name,reference,provider,blocks))
    for c in originals:
        motion = c["motion"]
        if motion == skip_motion:
            continue
        packet = request(db,motion,c["older"],c["newer"])
        add("complete", c["older"]+" -> "+c["newer"], db, packet)
        if c["continuity"] == "Reuse":
            foreign = motions[(motions.index(motion)+1)%len(motions)]
            for fault in FAULTS:
                add("single_fault",fault,*damaged(db,packet,fault,foreign))
    for motion in ("polaris-ipmc-rc5","otava-ipmc-rc3"):
        if motion == skip_motion:
            continue
        older,newer=db["motions"][motion]["refs"]
        packet=request(db,motion,older,newer)
        add("documented_negative",older+" -> "+newer, db,packet)
        for fault in ("missing_result","conflicting_registered_result","no_git_observations"):
            add("negative_control",fault,*damaged(db,packet,fault))
    if skip_motion is None:
        assert len(rows)==71
    return rows


def abstract_check():
    """Generate full worlds independently, query SQLite, then project and compare set equality."""
    a,b = "a"*40, "b"*40
    urls = ("uri:a","uri:b")
    openings = [Block("invalid")]
    closings = [Block("invalid")]
    for u in urls:
        openings += [Block("unbound",u), Block("bound",u,a), Block("bound",u,b)]
        closings += [Block("pass",u),Block("negative",u)]
    pins = [Block("invalid"),Block("valid","",a),Block("valid","",b)]
    subsets=[keys for n in range(5) for keys in combinations(ORDER,n)]
    targets=defaultdict(set)
    full_count=0
    for close,opening,older,newer in product(closings,openings,pins,pins):
        records=[]
        if opening.status!="invalid":
            records.append(dict(motion="m",role="opening",url=opening.url,candidate_commit=opening.oid))
        if close.status!="invalid":
            records.append(dict(motion="m",role="result",url=close.url,
                                outcome="passed" if close.status=="pass" else "withdrawn"))
        db={"motions":{"m":{"repository":"repo","refs":{"o":{"commit":older.oid},"n":{"commit":newer.oid}}}},
            "records":records}
        packet={"motion":"m","repository":"repo","packet":records,
                "snapshots":[{"ref":"o","commit":older.oid},{"ref":"n","commit":newer.oid}]}
        action=sql_decide(db,packet)
        full={"opening":opening,"result":close,"older":older,"newer":newer}
        assert feasible(full)=={action}
        for subset in subsets:
            targets[tuple((k,full[k]) for k in subset)].add(action)
        full_count+=1
    for partial,expected in targets.items():
        actual=feasible(dict(partial))
        assert actual==expected,(partial,actual,expected)
        if len(actual)==1:
            decision=next(iter(actual))
            support=minimal_support(dict(partial),decision)
            for k in support:
                subset=dict((x,dict(partial)[x]) for x in support if x!=k)
                assert len(feasible(subset))>1
    return {"complete_worlds":full_count,"distinct_partial_views":len(targets),"exact_action_sets":len(targets)}


def summarize(check_saved=False):
    cases=fixtures()
    strategies=["eager","opening-first","result-first","fixed","conditional","policy"]
    rows=[]
    orders={}
    total=defaultdict(Counter)
    by_group=defaultdict(lambda:defaultdict(Counter))
    for motion in sorted({c.motion for c in cases}):
        planner=Planner([c.blocks for c in cases if c.motion!=motion and c.blocks])
        orders[motion]=list(planner.fixed)
        for c in (r for r in cases if r.motion==motion):
            row=dict(motion=motion,group=c.group,name=c.name,sqlite=c.reference)
            for strategy in strategies:
                result=check(c.provider,strategy,planner)
                assert result["decision"]==c.reference,(c.motion,c.name,strategy,result,c.reference)
                row[strategy]={k:result[k] for k in ("decision","reads","support")}
                row[strategy]["read_order"]=list(result["trace"])
                for tally in (total[strategy],by_group[c.group][strategy]):
                    tally["rows"]+=1
                    tally["agree_with_sql"]+=1
                    tally["reads"]+=result["reads"]
            rows.append(row)
    by_budget={strategy:{str(b):sum(r[strategy]["reads"]<=b for r in rows) for b in range(1,6)} for strategy in strategies}
    report={"complete_and_partial_world_check":abstract_check(),"totals":total,"by_group":by_group,"certified_by_budget":by_budget,
            "held_out_fixed_orders":orders,"rows":rows}
    target=HERE/"results.json"
    if check_saved:
        assert load(target)==report,"Stored acquisition results differ from this replay."
    else:
        target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"totals":total,"by_group":by_group,"abstract":report["complete_and_partial_world_check"]},indent=2))

