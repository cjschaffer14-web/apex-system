from pathlib import Path
from apex.core import *
from apex.authority.constitution import Constitution
from apex.authority.gatekeeper import Gatekeeper
from apex.authority.broker import CapabilityBroker
from apex.actuation.runtime import ExecutionRuntime


def main():
    ledger = EventLedger(Path("state/events.jsonl"))
    obs = Observation(uid("obs"),"operator","cli","hello",{"type":"nominal"},now(),1,["operator"])
    ledger.append("Observation","operator",Plane.PROPOSAL,{"id":obs.id,"value":obs.value})

    bundle = EvidenceBundle(
        uid("evb"),["operator"],1.0,1.0,0.0,1.0,[],1.0,
        "low","calibration/operator",1.0,"E0",[obs.id]
    )
    proposal = Proposal(
        uid("proposal"),"demo-agent","echo a governed response","echo",
        [bundle.id],["demo.echo"],1,True,0.99,0.01,1.0,{"channel":"cli"}
    )

    gate = Gatekeeper(Constitution())
    decision,risk,constraint = gate.evaluate(proposal,[bundle])
    ledger.append("Decision","authority",Plane.AUTHORITY,asdict(decision),[proposal.id])

    broker = CapabilityBroker(b"development-key-not-production")
    tokens = broker.mint(decision,proposal)

    runtime = ExecutionRuntime()
    runtime.register("demo.echo",lambda text="APEX awake": {"echo":text})
    if tokens:
        outcome = runtime.execute(tokens[0],text="APEX v0.2 governed path is alive.")
        ledger.append("Outcome","actuation",Plane.ACTUATION,asdict(outcome),[tokens[0].id])
        print(outcome.measured_result)
    else:
        print("Denied:",decision.reasons)


if __name__ == "__main__":
    main()
