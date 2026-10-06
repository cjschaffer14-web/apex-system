# The Egg (developmental model) — E3/E4, explains, never authorizes

> The Egg is not the system's container. It is its developmental state.

| Part | Meaning | Code |
|---|---|---|
| Shell | continuity: event history, audit chain, checkpoints, lineage, model versions, memory, graph, config, benchmark history. A reboot cools the egg; it does not kill it. | `ledger.ContinuityLedger`, `verify_chain`, `checkpoint.json`, authority restore-from-history |
| Membrane | controlled contact with reality. Web ≠ truth; camera ≠ truth; LLM ≠ truth; sensor ≠ ground truth. Everything is an observation through an instrument. | `epistemics.Membrane` |
| Yolk / DNA | the small genome: Proposal ≠ Authority ≠ Actuation; no token → no action; preserve provenance, operator control, rollback, evaluator independence, audit | `constitution/invariants.json`, `walls.WALLS` |
| White | metabolic reserve: compute, memory, storage, bandwidth, battery, thermal, cloud credits, API quotas, attention, time, capital | `ResourceBroker` reserve, `ReservedTierScheduler` P-1 |
| Warmth | sustained usable energy for development: W = C·A·D·S | `incubation.incubation_temperature` |
| Heartbeat | keeps the environment in which intelligence develops | `Organism.heartbeat_tick` |
| Sleep | idle time consolidates: replay, compress, re-index, re-run failures, counterfactuals | `Organism.sleep_cycle` |
| Frontier | which organ to grow next, reorderable by expected transfer | `incubation.DevelopmentalFrontier` |
| Branching | failures reroute development instead of killing it | `SealedPromotion` (rejected / awaiting-capability branches kept) |
| Hatching | the developmental loop sustains itself; never escape from governance | `Organism.hatch_readiness` → `HATCHED` |

**Bands**: DORMANT (state only) · WARM (indexing, consolidation) · INCUBATING (research, candidates, evaluation) · ACCELERATED (parallel experiments, training, cross-AI) · HATCHING (readiness tests).

**Organogenesis**: DomainPacks are organs of one organism with a shared genome, history and constitution. They are not rival agents. Research → cortex, Coding → repair system, Memory → long-term nervous system, Scheduler → autonomic system, Authority → regulatory/endocrine system, Portal → face, Audio → ears and voice, Vision → eyes, Trading → specialised metabolic organ, Cloud → reserve tissue.

**The shell cracks; the membrane stays.** Permeability opens rung by rung (local files → approved web → approved cloud → cross-AI → external apps → persistent services) only as capabilities are granted.

**"Hatch regardless"** means: keep seeking a viable path toward developmental continuity despite failed experiments, interrupted compute, missing optional services or an absent owner. It does not mean ignoring constraints until something succeeds.

**One click** is not "Start". It begins incubation.
