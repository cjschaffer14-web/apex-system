# Representative models — E4 views over one organism (`apex/ext/views.py`)

Every view is checked like a functor: it must cover all five planes (world, proposal, authority, actuation, operator) and name components that exist. Print any of them with `python awaken.py --view <name>`.

* **Tower**: Observatory = Proposal (light, high entropy); Load-bearing core = authorityd; Street = VerifiedRuntime; Control room = Operator (P-1). No floor above can reach the street except through the core.
* **Cell in a Pressure Vessel** (Gemini's single macro-to-micro analogy): Cytoplasm = generative Proposal plane; Nuclear membrane = the wrapped Gatekeeper; DNA = Constitution + axioms; Hull = VerifiedRuntime + ResourceBroker; Steward = Operator. At the macro end, the multiverse of possible intents; at the micro end, one token check before one capability call.
* **Manifold**: the walls are event horizons, i.e. missing edges in the flow graph. Token minting is the only coordinate transform from the interior to the exterior trajectory. The Operator is the observer outside the formal system.
* **Markov blanket**: sensory = Membrane/EvidenceBundle/PeerEnvelope; active = token → runtime; internal = Authority + Model Graph. `topology.blanket()` checks that Authority never touches World directly.
* **Five systems** (ChatGPT): Perception, Cognition, Authority, Action, Evolution.
* **VSM** (Beer, interpretation only): S1 packs/runtime, S2 scheduler/stigmergy, S3 ResourceBroker/constraints, S3* second-order audit, S4 Proposal plane/frontier, S5 Constitution + Operator.

**The first invariant ("1.")** is a topological property. It is not a rule to remember. The geometry has no path from Proposal to Actuation except through Authority, and `prove_no_bypass` proves it on every awakening.
