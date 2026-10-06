import tempfile, unittest
from pathlib import Path
from apex.core import *
from apex.authority.constitution import Constitution
from apex.authority.gatekeeper import Gatekeeper
from apex.authority.broker import CapabilityBroker
from apex.actuation.runtime import ExecutionRuntime
from apex.scheduler import ResourceScheduler, Job


class ApexTests(unittest.TestCase):
    def test_no_token_no_execution(self):
        r=ExecutionRuntime(); r.register("x",lambda:1)
        with self.assertRaises(PermissionError): r.execute(None)

    def test_authority_ignores_advisory_confidence(self):
        p=Proposal(uid("p"),"m","g","x",["e"],["demo.echo"],1,True,0.0,1.0,1.0,{})
        b=EvidenceBundle(uid("e"),["trusted"],1,1,0,1,[],1,"low",None,1,"E0",["o"])
        d,_,_=Gatekeeper(Constitution()).evaluate(p,[b])
        self.assertEqual(d.result,"approved")

    def test_forbidden_authority_capability(self):
        p=Proposal(uid("p"),"m","g","x",["e"],["authority.mint"],1,True,1,0,1,{})
        b=EvidenceBundle(uid("e"),["x"],1,1,0,1,[],1,"low",None,1,"E0",["o"])
        d,_,_=Gatekeeper(Constitution()).evaluate(p,[b])
        self.assertEqual(d.result,"denied")

    def test_graph_authorizes_is_authority_only(self):
        g=ModelGraph(); g.add_node("a","Entity",{}); g.add_node("b","Capability",{})
        with self.assertRaises(PermissionError):
            g.add_edge("a","b","authorizes",Plane.PROPOSAL)

    def test_p3_checkpointable(self):
        s=ResourceScheduler()
        with self.assertRaises(ValueError):
            s.submit(Job(3,"train",False,1.0))


if __name__ == "__main__":
    unittest.main()
