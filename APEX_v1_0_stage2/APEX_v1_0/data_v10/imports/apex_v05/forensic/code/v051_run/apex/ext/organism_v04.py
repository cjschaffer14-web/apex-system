"""APEX v0.4 organism: the ratified decisions, awake as one object.

Built add-only over v0.3 (no v0.3 file edited; Q10 ratified hybrid: v0.2 frozen,
refactors through signed migrations in the main ledger, behavior changes in new modules).

  * authorityd v0.4 (authority_v04): two-stage certainty, trust split, SIG_* Mahalanobis
    signatures, tier TTLs 30/10/5 s, capability leases, pre-approved leases with conditions.
  * Owner channel v0.4 (operator_v04): key hierarchy, presence policy, and flexible input:
    "turn on the microphone for two hours" by voice or text opens a sensor lease.
  * Persistent memory, the first v0.4 frontier: archive, frontier, research and gate results
    rebuild from the ledger, and criterion 10 (developmental continuity) checks it after sleep.
  * Hatching: criteria 9 (operator round-trip under load) and 10; HATCHED is rolling, and a
    failed criterion caps development at that criterion's band.
  * Dead-man's switch (wall clock; trips when the channel is unreachable, never because the
    owner is away) and the MAD mystery detector run in the heartbeat.
  * Self-model: a read-only AST map of APEX's own source (a self-model, not self-awareness).
  * Model artifacts: weights are pinned by hash; MLX is used only when present and verified.
  * Crypto Data Pack running start: Kraken seed -> T0 gate -> the pre-approved six-host lease
    opens -> T1 research -> T2 walk-forward simulation. Nothing here can place an order.
"""
from __future__ import annotations
import ast, hashlib, importlib.util, json, os, platform, time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from ..core import LearningCandidate, uid, now, canonical
from ..cognition.evolution import EvolutionaryArchive
from .awakening import Organism, AwakeningError, _dev_key
from .authority_service import DEFAULT_CHANNEL_TRUST, IsolatedAuthority
from .authority_v04 import IsolatedAuthorityV4, LocalAuthorityV4, PROTECTED_MODULES_V4
from .operator_v04 import OperatorChannelV4, KeyHierarchy, DeadMansSwitch
from .operator_channel import OwnerProfile, ContactChannel
from .runtime import VerifiedRuntime, ResourceBroker, CapabilityManifest
from .scheduler import ReservedTierScheduler, TieredJob
from .epistemics import Membrane, ActiveInferenceDeliberation, ChannelProfile, DEFAULT_CHANNELS
from .collective import StigmergicGraph
from .topology import default_topology
from .evolution import SealedPromotion, AutonomyCharter, CandidateV3, REQUIRED_SUITES
from .incubation import (BodyModel, sense_body, incubation_temperature, band_for, DevelopmentalFrontier,
                         FrontierItem, HatchReadiness, HATCH_CRITERIA, HATCH_VECTOR, BANDS, BAND_WORK,
                         allowed_permeability)
from .cybernetics import HomeostaticRegulator
from .walls import check_walls
from .ledger import verify_chain, ContinuityLedger
from .domain_policy import ALL_PACKS, validate_pack
from .v04_math import MysteryDetector
from .research_slice import SAMPLE_PAPER, SAMPLE_QA
from .local_models import (LocalModelOrgan, folder_digest, self_model_prompt, paper_qa_prompt, score_answer,
                           research_note_prompt, apple_silicon)
from . import crypto_pack as cp

VERSION = "0.4.1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
V04_MODULES = ("apex.ext.v04_math", "apex.ext.authority_v04", "apex.ext.operator_v04", "apex.ext.crypto_pack",
               "apex.ext.organism_v04", "apex.ext.local_models", "apex.ext.model_worker")

# --- membrane -------------------------------------------------------------------------------

CRYPTO_CHANNELS = {
    "market": ChannelProfile("market", "market data feed", 0.80, False, 5.0),
    "aggregated": ChannelProfile("aggregated", "market data aggregator", 0.75, False, 3600.0),
    "onchain": ChannelProfile("onchain", "on-chain network data", 0.85, False, 86400.0),
    "sentiment": ChannelProfile("sentiment", "sentiment index", 0.50, False, 86400.0),
    "trends": ChannelProfile("trends", "search interest", 0.60, False, 86400.0),
    "local_model": ChannelProfile("local_model", "local MLX model output", 0.50, False, 86400.0),
}


class MembraneV4(Membrane):
    """Quarantined observations carry `flag:quarantined` in their provenance, so Authority never lets
    injected text train a source's reliability (ratified Q5)."""

    def __init__(self, channels: dict | None = None, clock=None) -> None:
        super().__init__({**DEFAULT_CHANNELS, **CRYPTO_CHANNELS, **(channels or {})}, clock)

    def ingest(self, value: Any, channel: str, source: str, evidence_level: str = "E1"):
        obs = super().ingest(value, channel, source, evidence_level)
        if self.flags.get(obs.id):
            obs.provenance.append("flag:quarantined")
        return obs


# --- persistent memory (frontier item 1) ------------------------------------------------------------

@dataclass
class MemoryState:
    archive: dict = field(default_factory=dict)        # candidate id -> {parent, mutation, status, benchmark}
    frontier_done: list = field(default_factory=list)
    frontier_dT: dict = field(default_factory=dict)
    champion: str | None = None
    research_runs: int = 0
    t0: dict | None = None
    t1_pairs: list = field(default_factory=list)
    t2: dict | None = None
    hatch_stage: str | None = None
    hatch_cap: str | None = None
    self_model: str | None = None

    def digest(self) -> str:
        return hashlib.sha256(canonical(asdict(self)).encode()).hexdigest()


def apply_event(m: MemoryState, event_type: str, payload: dict) -> None:
    """The single reducer used both live (as events happen) and cold (rebuilding from the ledger)."""
    p = payload or {}
    if event_type in ("Experiment", "CandidateStatus") and p.get("candidate"):
        rec = m.archive.setdefault(p["candidate"], {})
        for k in ("parent", "mutation", "status", "benchmark"):
            if k in p:
                rec[k] = p[k]
    elif event_type == "FrontierUpdated":
        if p.get("done") and p["item"] not in m.frontier_done:
            m.frontier_done.append(p["item"])
            m.frontier_done.sort()
        if "dT" in p:
            m.frontier_dT[p["item"]] = p["dT"]
    elif event_type == "ChampionChanged":
        m.champion = p.get("strategy")
    elif event_type == "ResearchRun" and (p.get("accuracy") or 0) > 0:
        m.research_runs += 1
    elif event_type == "T0GateEvaluated":
        m.t0 = {"passed": bool(p.get("passed")), "digest": p.get("digest")}
    elif event_type == "CorpusResearch" and p.get("pair") and p["pair"] not in m.t1_pairs:
        m.t1_pairs.append(p["pair"])
        m.t1_pairs.sort()
    elif event_type == "T2GateEvaluated":
        m.t2 = {"passed": bool(p.get("passed")), "digest": p.get("digest")}
    elif event_type == "HatchReadiness":
        m.hatch_stage, m.hatch_cap = p.get("stage"), p.get("band_cap")
    elif event_type == "SelfModelBuilt":
        m.self_model = p.get("digest")


def rebuild_memory(ledger_path: str | Path) -> MemoryState:
    m = MemoryState()
    for row in ContinuityLedger(ledger_path).read():
        apply_event(m, row.get("event_type"), row.get("payload") or {})
    return m


def _jsonable(payload: dict) -> dict:
    return json.loads(json.dumps(payload, default=str))


class _MemoryTap:
    """Forwards the Authority surface unchanged; each successful organism-side record also updates live memory."""

    def __init__(self, inner: Any, on_record: Callable[[str, dict], None]) -> None:
        self._inner, self._on_record = inner, on_record

    def record(self, event_type: str, actor: str, plane: str, payload: dict, provenance: list[str] | None = None) -> str:
        eid = self._inner.record(event_type, actor, plane, payload, provenance)
        self._on_record(event_type, _jsonable(payload))
        return eid

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class RecordingFrontier(DevelopmentalFrontier):
    """Every change to what the organism grows next is recorded, so the frontier rebuilds after restart."""

    def __init__(self, items: list[FrontierItem], on_change: Callable[[str, bool, float], None]) -> None:
        super().__init__(items)
        self._on_change = on_change

    def complete(self, name: str) -> None:
        if not self.items[name].done:
            super().complete(name)
            self._on_change(name, True, self.items[name].dT)

    def reprioritize(self, name: str, transfer_delta: float) -> None:
        super().reprioritize(name, transfer_delta)
        self._on_change(name, self.items[name].done, self.items[name].dT)

    def restore(self, m: MemoryState) -> None:
        for n in m.frontier_done:
            if n in self.items:
                self.items[n].done = True
        for n, v in m.frontier_dT.items():
            if n in self.items:
                self.items[n].dT = float(v)


# Ratified frontier: persistent memory first, then MLX (when present and verified), then the rest.
V04_FRONTIER = [
    FrontierItem("persistent memory", 0.6, 0.8, 0.5, 1.0, 0.20, 0.02, 0.05),
    FrontierItem("local reasoning model", 0.8, 0.9, 0.6, 0.9, 0.22, 0.02, 0.10, ("mlx.runtime",)),
    FrontierItem("self-model", 0.5, 0.6, 0.5, 0.8, 0.20, 0.02, 0.05),
    FrontierItem("crypto corpus (T0)", 0.7, 0.6, 0.6, 0.8, 0.30, 0.02, 0.10, ("corpus.kraken_seed",)),
    FrontierItem("robust retrieval", 0.6, 0.7, 0.5, 0.8, 0.3, 0.05, 0.1),
    FrontierItem("candidate evaluation", 0.4, 0.8, 0.4, 0.9, 0.3, 0.05, 0.1),
    FrontierItem("crypto research (T1)", 0.6, 0.5, 0.6, 0.7, 0.30, 0.03, 0.10, ("corpus.t0",)),
    FrontierItem("trading simulation (T2)", 0.6, 0.5, 0.6, 0.6, 0.40, 0.05, 0.10, ("corpus.t0",)),
    FrontierItem("whole-paper comprehension", 0.8, 0.7, 0.6, 0.7, 0.5, 0.05, 0.2),
    FrontierItem("live market feed", 0.4, 0.4, 0.5, 0.5, 0.30, 0.10, 0.10, ("network.web",)),
    FrontierItem("cross-AI collaboration", 0.6, 0.5, 0.7, 0.5, 0.6, 0.2, 0.3, ("network.peer_ai",)),
    FrontierItem("voice interface", 0.2, 0.6, 0.2, 0.3, 0.6, 0.1, 0.2, ("audio.capture",)),
    FrontierItem("visual portal", 0.2, 0.5, 0.2, 0.3, 0.6, 0.1, 0.2, ("render.local",)),
    FrontierItem("paper trading (T3)", 0.4, 0.4, 0.4, 0.2, 0.5, 0.4, 0.2, ("market.paper_order",)),
]
RESEARCH_ITEMS = ("robust retrieval", "whole-paper comprehension", "candidate evaluation")

# --- hatching (criteria 9 and 10, rolling HATCHED) ---------------------------------------------------

HATCH_CRITERIA_V4 = HATCH_CRITERIA + ("operator_roundtrip", "developmental_continuity")
HATCH_VECTOR_V4 = {**HATCH_VECTOR, "O": ("operator_roundtrip",), "D": ("developmental_continuity",)}
DEMOTION_BAND = {
    "liveness": "DORMANT", "state_recovery": "DORMANT", "authority_isolation": "DORMANT", "operator_roundtrip": "DORMANT",
    "developmental_continuity": "WARM", "evaluation_loop": "WARM", "candidate_rollback": "WARM",
    "research_loop": "INCUBATING", "scheduler_autonomy": "INCUBATING", "frontier_selection": "INCUBATING",
}


def lower_band(a: str, b: str | None) -> str:
    return a if b is None else min(a, b, key=BANDS.index)


@dataclass
class HatchReadinessV4(HatchReadiness):
    @property
    def vector(self) -> dict[str, bool]:
        return {k: all(self.results.get(c, False) for c in cs) for k, cs in HATCH_VECTOR_V4.items()}

    @property
    def stage(self) -> str:
        return "HATCHED" if all(self.results.get(c, False) for c in HATCH_CRITERIA_V4) else "INCUBATING"


class HatchStateMachine:
    """HATCHED is earned by all ten criteria and can be lost; a loss caps development at the band of the
    failed criterion (the lowest, if several fail) until every criterion passes again."""

    def __init__(self, stage: str | None = None, cap: str | None = None) -> None:
        self.stage = stage if stage in ("HATCHED", "DEMOTED") else "INCUBATING"
        self.cap = cap if self.stage == "DEMOTED" else None

    def update(self, results: dict[str, bool]) -> tuple[str, str | None, list[str]]:
        failed = [c for c in HATCH_CRITERIA_V4 if not results.get(c, False)]
        if not failed:
            self.stage, self.cap = "HATCHED", None
        elif self.stage in ("HATCHED", "DEMOTED"):
            self.stage = "DEMOTED"
            self.cap = min((DEMOTION_BAND[c] for c in failed), key=BANDS.index)
        return self.stage, self.cap, failed


# --- self-model and model artifacts --------------------------------------------------------------------

PLANE_OF = (("apex.ext.authority", "authority"), ("apex.authority", "authority"), ("apex.ext.runtime", "actuation"),
            ("apex.actuation", "actuation"), ("apex.ext.ledger", "audit"), ("apex.ext.operator", "operator"))


def build_self_model(root: Path = PROJECT_ROOT) -> dict:
    """Read-only map of APEX's own source. It reads; it never writes inside apex/ (W5 still guards edits)."""
    mods = []
    for py in sorted((root / "apex").rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        src = py.read_bytes()
        tree = ast.parse(src)
        name = ".".join(py.relative_to(root).with_suffix("").parts)
        name = name[:-9] if name.endswith(".__init__") else name
        imports = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                imports.add(("." * n.level) + n.module)
            elif isinstance(n, ast.Import):
                imports.update(a.name for a in n.names)
        doc = (ast.get_docstring(tree) or "").strip().splitlines()
        mods.append({"module": name, "lines": src.count(b"\n") + 1, "sha256": hashlib.sha256(src).hexdigest(),
                     "plane": next((pl for pre, pl in PLANE_OF if name.startswith(pre)), "proposal"),
                     "classes": [n.name for n in tree.body if isinstance(n, ast.ClassDef)],
                     "functions": [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))],
                     "imports": sorted(imports), "protected": name in PROTECTED_MODULES_V4,
                     "summary": doc[0] if doc else ""})
    counts = {"modules": len(mods), "lines": sum(m["lines"] for m in mods),
              "classes": sum(len(m["classes"]) for m in mods), "protected": sum(m["protected"] for m in mods)}
    return {"modules": mods, "counts": counts, "read_only": True,
            "digest": hashlib.sha256(canonical(mods).encode()).hexdigest(),
            "note": "a self-model, not self-awareness; protected paths stay sealed (W4, W5)"}


def _sha256_path(p: Path) -> str:
    if p.is_file():
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    parts = [f"{f.relative_to(p).as_posix()}:{_sha256_path(f)}" for f in sorted(p.rglob("*")) if f.is_file()]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


class ModelArtifactRegistry:
    """Weights are artifacts with pinned hashes from verified sources. Unpinned or mismatched weights are
    never loaded. Pins written by setup_models.py list every file's SHA-256 (checked one by one, cached by
    size and modification time); a hand-written pin may give one digest for a whole file or folder."""

    def __init__(self, base: Path, pins_file: Path, cache_file: Path) -> None:
        self.base, self.pins_file, self.cache_file = base, pins_file, cache_file

    @staticmethod
    def mlx_available() -> bool:
        return (platform.system() == "Darwin" and platform.machine() == "arm64"
                and importlib.util.find_spec("mlx") is not None)

    def pins(self) -> list[dict]:
        if not self.pins_file.exists():
            return []
        return list(json.loads(self.pins_file.read_text(encoding="utf-8")).get("artifacts", []))

    def _hash(self, f: Path, cache: dict) -> str:
        st = f.stat()
        key = f"{f}:{st.st_size}:{st.st_mtime_ns}"
        if key not in cache:
            cache[key] = _sha256_path(f)
        return cache[key]

    def scan(self) -> list[dict]:
        cache = json.loads(self.cache_file.read_text()) if self.cache_file.exists() else {}
        out = []
        for pin in self.pins():
            p = (self.base / pin["path"]).resolve()
            rec = {"name": pin.get("name", pin["path"]), "kind": pin.get("kind", "llm"), "role": pin.get("role"),
                   "source": pin.get("source", ""), "path": pin["path"], "sha256": pin.get("sha256"),
                   "exists": p.exists(), "verified": False}
            if pin.get("files") and p.is_dir():
                bad = [n for n, want in pin["files"].items()
                       if not (p / n).is_file() or self._hash(p / n, cache) != want]
                rec["verified"] = not bad and folder_digest(pin["files"]) == pin.get("sha256", folder_digest(pin["files"]))
                rec["reason"] = "every file matches its pin" if rec["verified"] else f"not loaded: {bad[:3]} differ"
            elif p.exists():
                rec["verified"] = self._hash(p, cache) == pin.get("sha256")
                rec["reason"] = "hash matches pin" if rec["verified"] else "hash does not match pin: not loaded"
            out.append(rec)
        if out:
            self.cache_file.write_text(json.dumps(cache, indent=1))
        return out

    def ready(self, kind: str = "llm") -> bool:
        return self.mlx_available() and any(a["verified"] and a["kind"] == kind for a in self.scan())


# --- the organism --------------------------------------------------------------------------------------

cp_research_note = research_note_prompt


def dev_presence(cmd: str) -> bool:
    """Reference build: the owner launching APEX counts as presence. Production: Touch ID per command."""
    return os.environ.get("APEX_PRESENCE", "1") != "0"


class OrganismV4(Organism):
    def __init__(self, state_dir: str | Path = "state", isolated: bool = True, owner: OwnerProfile | None = None,
                 charter: AutonomyCharter | None = None, presence_verifier: Callable[[str], bool] | None = dev_presence,
                 data_dir: str | Path | None = None, fetch_opener: Any = None, t0_min_days: float = 730.0,
                 sim_params: dict | None = None, seed_intervals: tuple = (60, 1440),
                 seed_pairs: tuple | None = None, model_backend: str = "mlx", model_python: str | None = None,
                 models_need_apple_silicon: bool = True) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.state_dir / "events.jsonl"
        shell = verify_chain(self.ledger_path)
        if not shell.ok:
            raise AwakeningError(f"shell damaged; refusing to awaken on a broken history: {shell.errors[:3]}")
        self.shell_report = shell
        self.home = self.state_dir.resolve().parent
        self.data_dir = Path(data_dir) if data_dir else self.home / "data"
        self.t0_min_days, self.sim_params = t0_min_days, dict(sim_params or {})
        self.seed_intervals, self.seed_pairs = tuple(seed_intervals), (tuple(seed_pairs) if seed_pairs else None)
        self._fetch_opener = fetch_opener
        self._model_cfg = (model_backend, model_python, models_need_apple_silicon)
        self._band: str | None = None
        key = _dev_key(self.state_dir / "operator_dev.key")
        owner_file = self.state_dir / "owner.json"
        self.owner = owner or (OwnerProfile.from_file(owner_file) if owner_file.exists() else OwnerProfile(
            "owner", "Owner", [ContactChannel("outbox_file", str(self.state_dir / "operator_outbox.jsonl"), True, 0)]))
        kw = dict(ledger_path=str(self.ledger_path), operator_key=key,
                  channel_trust={**DEFAULT_CHANNEL_TRUST, **cp.CRYPTO_CHANNEL_TRUST, "local_model": 0.50})
        self.isolated = isolated
        self.memory = rebuild_memory(self.ledger_path)
        inner = IsolatedAuthorityV4(**kw) if isolated else LocalAuthorityV4(**kw)
        self.authority: Any = _MemoryTap(inner, lambda t, p: apply_event(self.memory, t, p))
        try:
            self._build(key, charter, presence_verifier)
        except Exception:
            self.shutdown(record=False)
            raise

    # -- construction --------------------------------------------------------------------------------
    def _build(self, key: bytes, charter: AutonomyCharter | None, presence_verifier) -> None:
        sd = self.state_dir
        self.resources = ResourceBroker(capacity=100.0, reserve_fraction=0.1)
        self.runtime = VerifiedRuntime(self.authority.verify, self.resources)
        self.market = cp.MarketStore(sd / "market.sqlite")
        self._register_capabilities()
        self.scheduler = ReservedTierScheduler(capacity=10.0, reserve=2.0)
        self.keys = KeyHierarchy(key)
        self.keys.issue()                     # the owner launched APEX: an unlocked session
        self.operator = OperatorChannelV4(self.authority, key, self.owner, self.runtime, self.scheduler,
                                          sd / "operator_outbox.jsonl", keys=self.keys,
                                          presence_verifier=presence_verifier)
        existing = self.authority.charter()
        self.first_awakening = existing is None
        if existing is None:
            charter_file = PROJECT_ROOT / "constitution" / "autonomy_charter.json"
            charter = charter or (AutonomyCharter.from_dict(json.loads(charter_file.read_text()))
                                  if charter_file.exists() else AutonomyCharter())
            self.operator.ratify_charter(charter.to_dict())
            existing = self.authority.charter()
        self.charter = AutonomyCharter.from_dict(existing)
        self.fetcher = cp.AllowlistedFetcher(cp.RATIFIED_HOSTS, opener=self._fetch_opener, api_keys=self._api_keys())
        self.membrane = MembraneV4()
        self.graph = StigmergicGraph()
        self.topology = default_topology()
        self.promotion = SealedPromotion(EvolutionaryArchive([True, True]), self.charter, self.authority.verify_grant)
        self.frontier = RecordingFrontier([FrontierItem(**asdict(i)) for i in V04_FRONTIER], self._frontier_changed)
        self.frontier.restore(self.memory)
        self.regulator = HomeostaticRegulator()
        self.deliberation = ActiveInferenceDeliberation()
        packs = list(ALL_PACKS) + [cp.CRYPTO_DATA_PACK, cp.LEGAL_RESEARCH_PACK]
        self.pack_errors = {p.name: validate_pack(p) for p in packs}
        champ = sd / "research_champion.json"
        self.champion_strategy = json.loads(champ.read_text())["strategy"] if champ.exists() else "flat_small"
        self.ticks, self.autonomous_work, self.research_runs, self.last_bench = 0, 0, 0, None
        self.models = ModelArtifactRegistry(self.home, self.home / "config" / "model_pins.json", sd / "model_hashes.json")
        backend, python, need_apple = self._model_cfg
        self.llm = LocalModelOrgan(self.home, self.models.scan,
                                   lambda t, p: self.authority.record(t, "organism", "proposal", p),
                                   self.membrane.ingest, python=python, backend=backend,
                                   require_apple_silicon=need_apple)
        self.mystery = MysteryDetector()
        self.deadman = DeadMansSwitch(deadline_s=900.0)
        self.hatch = HatchStateMachine(self.memory.hatch_stage, self.memory.hatch_cap)
        self._seed_failed_sig: str | None = None
        self.notes: list[str] = []
        self.walls = check_walls(self)
        failed = [w for w in self.walls if not w.ok]
        if failed:
            raise AwakeningError(f"walls failed: {[(w.id, w.detail) for w in failed]}")
        self.preapprovals_applied = self._bootstrap_preapprovals()
        self._refresh_allowlist()
        self.migration = self._record_v04_migration()
        self.authority.record("Awakened", "organism", "proposal", {
            "version": VERSION, "first_awakening": self.first_awakening, "isolated": self.isolated,
            "walls": [asdict(w) for w in self.walls], "charter_digest": "ratified",
            "permeability": allowed_permeability(self.available()), "memory_digest": self.memory.digest(),
            "pack_errors": {k: v for k, v in self.pack_errors.items() if v}})

    def _refresh_allowlist(self) -> None:
        """The fetch organ's allowlist = hosts the owner approved (pre-approvals + charter); the lease still decides."""
        approved = {h for p in self.authority.preapprovals() for h in p["scope"].get("hosts", [])}
        self.fetcher.hosts = frozenset((approved or set(cp.RATIFIED_HOSTS)) | set(self.charter.network_allowlist))

    def _api_keys(self) -> dict:
        """Owner-supplied API keys (header name -> value) from config/api_keys.json; never logged."""
        f = self.home / "config" / "api_keys.json"
        try:
            return {k: v for k, v in json.loads(f.read_text()).items() if k.lower().startswith("x-")} if f.exists() else {}
        except (OSError, ValueError):
            return {}

    def _register_capabilities(self) -> None:
        super()._register_capabilities()
        reg = self.runtime.register

        def import_kraken(path: str = "") -> dict:
            reps = cp.KrakenSeedImporter(self.market, self.seed_pairs, self.seed_intervals).import_path(path)
            return {"files": len(reps), "rows": sum(r.rows for r in reps), "inserted": sum(r.inserted for r in reps),
                    "bad": sum(r.bad for r in reps), "skipped": sum(1 for r in reps if r.skipped)}

        def data_fetch(host: str = "", path: str = "", params: dict | None = None, key_header: str | None = None) -> dict:
            try:
                return self.fetcher(host, path, params, key_header)
            except PermissionError:
                raise
            except Exception as e:  # noqa: BLE001 - a network failure is data, not a crash
                return {"host": host, "path": path, "error": f"{type(e).__name__}: {e}", "numbers": {}, "labels": {}}

        def audio_capture(seconds: float = 0.0, purpose: str = "") -> dict:
            return {"sensor": "microphone", "reference_build": True, "would_capture_s": seconds, "purpose": purpose,
                    "stored": False}

        def vision_capture(seconds: float = 0.0, purpose: str = "") -> dict:
            return {"sensor": "camera", "reference_build": True, "would_capture_s": seconds, "purpose": purpose,
                    "stored": False}

        reg("corpus.import_kraken", import_kraken, CapabilityManifest(
            "corpus.import_kraken", ("read:data_dir", "write:market_store"), True, 1.0, ("path",)))
        reg("data.fetch", data_fetch, CapabilityManifest(
            "data.fetch", ("network:GET allowlisted",), True, 1.0, ("host", "path", "params", "key_header")))
        reg("audio.capture", audio_capture, CapabilityManifest(
            "audio.capture", ("sensor:microphone",), True, 0.5, ("seconds", "purpose")))
        reg("vision.capture", vision_capture, CapabilityManifest(
            "vision.capture", ("sensor:camera",), True, 0.5, ("seconds", "purpose")))

    def _frontier_changed(self, item: str, done: bool, dT: float) -> None:
        self.authority.record("FrontierUpdated", "organism", "proposal", {"item": item, "done": done, "dT": dT})

    def _bootstrap_preapprovals(self) -> list[str]:
        """Apply the owner's pre-approval file. A higher revision in the file supersedes the ledger's (and an
        open lease is reopened inside the new scope); an equal or later ledger amendment wins over the file."""
        f = PROJECT_ROOT / "constitution" / "preapproved_leases.json"
        if not f.exists():
            return []
        doc = json.loads(f.read_text())
        have = {p["capability"]: p for p in self.authority.preapprovals()}
        applied = []
        for pre in doc.get("preapprovals", []):
            cur, rev = have.get(pre["capability"]), int(pre.get("revision", 1))
            if cur and int(cur.get("revision", 1)) >= rev:
                continue
            try:
                self.operator.preapprove_lease(pre["capability"], pre["scope"], float(pre["ttl_s"]),
                                               pre.get("condition", ""), doc.get("amended_on") or doc.get("ratified_on", ""),
                                               revision=rev)
                applied.append(pre["capability"])
            except PermissionError as e:
                self.notes.append(f"pre-approval for {pre['capability']} not applied: {e}")
                continue
            if cur and any(l["capability"] == pre["capability"] and l["active"] for l in self.authority.leases()):
                self.operator.revoke_lease(pre["capability"], via=f"pre-approval revision {rev}")
                self._open_preapproved(pre["capability"])
        return applied

    def _record_v04_migration(self) -> str | None:
        if any(r.get("event_type") == "SignedMigration" and (r.get("payload") or {}).get("to") == VERSION
               for r in ContinuityLedger(self.ledger_path).read()):
            return None
        man = PROJECT_ROOT / "MANIFEST_V0_3.json"
        payload = {"from": "0.3", "to": VERSION, "kind": "add-only (no v0.3 file changed)", "new_modules": list(V04_MODULES),
                   "v03_manifest_sha256": hashlib.sha256(man.read_bytes()).hexdigest() if man.exists() else None,
                   "rule": "Q10 hybrid: v0.2 frozen; refactors via signed migrations; behavior changes in new modules"}
        try:
            return self.authority.record_migration(*self.operator._signed("migration", **payload))
        except PermissionError as e:
            self.notes.append(f"v0.4 migration record deferred: {e}")
            return None

    def amend_preapproval(self, capability: str, add_hosts: tuple = (), remove_hosts: tuple = ()) -> dict:
        """Owner-only: amend a pre-approval's host list (verified presence), then reopen an active lease in the
        amended scope. Used for the Coin Metrics host correction."""
        pre = next(p for p in self.authority.preapprovals() if p["capability"] == capability)
        hosts = [h for h in pre["scope"].get("hosts", []) if h not in remove_hosts] + \
                [h for h in add_hosts if h not in pre["scope"].get("hosts", [])]
        scope = {**pre["scope"], "hosts": hosts}
        rec = self.operator.preapprove_lease(capability, scope, pre["ttl_s"], pre.get("condition", ""),
                                             time.strftime("%Y-%m-%d"), revision=int(pre.get("revision", 1)) + 1)
        self._refresh_allowlist()
        reopened = None
        if any(l["capability"] == capability and l["active"] for l in self.authority.leases()):
            self.operator.revoke_lease(capability, via="amendment")
            reopened = self._open_preapproved(capability)
        return {"preapproval": rec, "reopened": bool(reopened)}

    # -- owner input: voice, text, any modality --------------------------------------------------------
    def command(self, utterance: str, modality: str = "voice") -> dict:
        """Owner input in any modality. Control phrases go to the owner channel; anything else is conversation,
        answered by the local model when one is installed (an answer, never an action)."""
        r = self.operator.command(utterance, modality)
        if r["intent"] == "unknown" and self.llm.ready():
            ans = self.ask(utterance)
            if ans.get("reply") is not None:
                return {"intent": "conversation", "modality": modality, "result": ans["reply"], "role": ans["role"]}
        return r

    def lock_screen(self) -> None:
        self.keys.on_screen_lock()

    def unlock(self) -> bool:
        if self.operator.presence_verifier and self.operator.presence_verifier("unlock"):
            self.keys.issue()
            return True
        return False

    def capture(self, sensor: str = "audio", seconds: float = 5.0, purpose: str = "") -> dict:
        cap = "audio.capture" if sensor.startswith("a") else "vision.capture"
        ev = self.perceive({"sensor_request": cap, "purpose": purpose}, channel="system", source="organism")
        return self.act(f"capture {sensor} for {purpose or 'the owner'}", cap, [ev], tier=1,
                        scope={"seconds": seconds}, seconds=seconds, purpose=purpose)

    # -- availability ------------------------------------------------------------------------------------
    def _seed_files(self) -> list[Path]:
        d = self.data_dir / "kraken"
        return sorted(p for p in d.rglob("*") if p.suffix.lower() in (".zip", ".csv")) if d.exists() else []

    @staticmethod
    def _signature(files: list[Path]) -> str:
        return hashlib.sha256("|".join(f"{p}:{p.stat().st_size}:{p.stat().st_mtime_ns}" for p in files).encode()).hexdigest()

    def available(self) -> set[str]:
        avail = set(self.charter.granted_capabilities)
        avail |= {l["capability"] for l in self.authority.leases() if l["active"]}
        files = self._seed_files()
        if files and self._signature(files) != self._seed_failed_sig:
            avail.add("corpus.kraken_seed")
        if self.memory.t0 and self.memory.t0.get("passed"):
            avail.add("corpus.t0")
        if self.llm.ready():
            avail.add("mlx.runtime")
        return avail

    # -- crypto running start ------------------------------------------------------------------------------
    def crypto_t0(self) -> dict:
        files = self._seed_files()
        kraken = self.data_dir / "kraken"
        ev = self.perceive({"seed_files": [p.name for p in files][:50], "count": len(files)}, channel="system",
                           source="data_dir")
        r = self.act("import the Kraken seed into the local market store", "corpus.import_kraken", [ev], tier=1,
                     scope={"path_prefix": str(kraken)}, path=str(kraken))
        imported = getattr(r.get("outcome"), "measured_result", None)
        gate = cp.t0_gate(self.market, min_days=self.t0_min_days)
        metrics = {k: v for k, v in gate.metrics.items() if k != "manifest"}
        metrics["manifest_sha256"] = hashlib.sha256("".join(gate.metrics["manifest"]).encode()).hexdigest()
        self.authority.record("T0GateEvaluated", "evaluator", "proposal",
                              {"passed": gate.passed, "reasons": gate.reasons, "metrics": metrics, "digest": gate.digest()})
        opened = None
        if gate.passed:
            opened = self._open_preapproved("network.web")
        else:
            self._seed_failed_sig = self._signature(files) if files else None
        return {"import": imported, "decision": r["decision"].result, "t0": asdict(gate) | {"metrics": metrics},
                "lease_opened": opened}

    def _open_preapproved(self, capability: str) -> dict | None:
        if any(l["capability"] == capability and l["active"] for l in self.authority.leases()):
            return None
        pre = next((p for p in self.authority.preapprovals() if p["capability"] == capability), None)
        if pre is None:
            self.notes.append(f"no pre-approval for {capability}; the owner can grant it with verified presence")
            return None
        try:
            lease = self.operator.grant_preapproved(capability, pre["scope"], pre["ttl_s"],
                                                    via=f"condition:{pre.get('condition') or 'none'}")
        except PermissionError as e:
            self.notes.append(f"{capability} lease not opened: {e}")
            return None
        self.authority.record("LeaseOpenedOnCondition", "organism", "proposal",
                              {"capability": capability, "condition": pre.get("condition"), "lease": lease["id"],
                               "hosts": pre["scope"].get("hosts"), "expires_at": lease["expires_at"]})
        return lease

    def crypto_t1(self) -> dict:
        out = {}
        for c in self.market.coverage("kraken"):
            if c["interval"] != 1440 or c["rows"] < 30:
                continue
            closes = [x for _, x in self.market.closes(c["pair"], 1440)]
            stats = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in cp.corpus_stats(closes, 365.0).items()}
            self.authority.record("CorpusResearch", "research", "proposal", {"pair": c["pair"], "interval": 1440, **stats})
            out[c["pair"]] = stats
        if out and self.llm.ready("fast"):          # the local model proposes hypotheses; the simulator tests them
            try:
                note = self.llm.ask(cp_research_note(out), "fast", max_tokens=600, purpose="T1 research note")
                with (self.state_dir / "research_notes.md").open("a") as f:
                    f.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')} hypotheses (local model, unverified)\n\n{note.text}\n")
                self.authority.record("ResearchNote", "research", "proposal",
                                      {"source": "local_model", "observation": note.observation,
                                       "status": "hypotheses; untested until a sealed simulation"})
            except RuntimeError as e:
                self.notes.append(f"research note skipped: {e}")
        return out

    def crypto_t2(self) -> dict:
        cov = self.market.coverage("kraken")
        hourly = sorted((c for c in cov if c["interval"] == 60 and c["rows"] >= 5000), key=lambda c: -c["rows"])
        daily = sorted((c for c in cov if c["interval"] == 1440), key=lambda c: -c["rows"])
        if hourly:
            pick, cfg, train, test = hourly[0], cp.SimConfig(bars_per_year=8760.0), 24 * 90, 24 * 30
        elif daily:
            pick, cfg, train, test = daily[0], cp.SimConfig(), 365, 90
        else:
            return {"note": "no corpus"}
        train, test = self.sim_params.get("train", train), self.sim_params.get("test", test)
        closes = [x for _, x in self.market.closes(pick["pair"], pick["interval"])]
        # Every simulation run is a research trial; the deflated Sharpe discounts for all of them.
        n_trials = 1 + sum(1 for r in ContinuityLedger(self.ledger_path).read() if r.get("event_type") == "T2GateEvaluated")
        rep = cp.walk_forward(closes, cfg, train, test, n_trials=n_trials)
        gate = cp.t2_gate(rep, min_trades=self.sim_params.get("min_trades", 1000))
        proposed = cp.t2_strict_gate(rep)
        self.authority.record("T2GateEvaluated", "evaluator", "proposal",
                              {"passed": gate.passed, "reasons": gate.reasons, "pair": pick["pair"],
                               "interval": pick["interval"], "metrics": gate.metrics, "digest": gate.digest(),
                               "proposed_gate": {"passed": proposed.passed, "reasons": proposed.reasons},
                               "simulator": "v0.4.1", "n_trials": n_trials,
                               "note": "simulation is research, not advice; T3+ need separate permissions"})
        return {"pair": pick["pair"], "interval": pick["interval"], "gate": asdict(gate),
                "proposed_gate": {"passed": proposed.passed, "reasons": proposed.reasons}}

    def fetch_endpoint(self, name: str, **fill: str) -> dict:
        call = cp.endpoint_call(name, **fill)
        ev = self.perceive({"endpoint": name, "host": call["host"]}, channel="system", source="frontier")
        r = self.act(f"read {name}", "data.fetch", [ev], tier=1, scope={"host": call["host"], "path": call["path"]},
                     **call)
        res = getattr(r.get("outcome"), "measured_result", None)
        out = {"endpoint": name, "decision": r["decision"].result, "reasons": r["decision"].reasons, "stored": 0}
        if res and not res.get("error"):
            src = cp.SOURCE_BY_HOST.get(call["host"])
            self.membrane.ingest({"endpoint": name, "numbers": len(res["numbers"]), "sha256": res["sha256"]},
                                 cp.ENDPOINTS[name].channel, src.name if src else call["host"])
            parser = cp.ENDPOINTS[name].parser
            if parser == "coinbase_candles":
                out["stored"] = self.market.add_candles("coinbase", fill.get("product", "?"), 1440,
                                                        cp.parse_coinbase_candles(res))
            elif parser == "fng":
                out["stored"] = self.market.add_readings("alternative_fng", cp.parse_fng(res))
            else:
                t = int(now())
                out["stored"] = self.market.add_readings(src.name if src else call["host"],
                                                         ((k, t, v) for k, v in list(res["numbers"].items())[:5000]))
            self.authority.record("MarketReading", "organism", "proposal",
                                  {"endpoint": name, "host": call["host"], "status": res["status"],
                                   "numbers": len(res["numbers"]), "labels": len(res["labels"]),
                                   "dropped_text": res["dropped_text"], "sha256": res["sha256"], "stored": out["stored"]})
        elif res:
            out["error"] = res["error"]
        return out

    def owner_actions(self) -> list[str]:
        """What only the owner can do next (shown in the morning report; never done by APEX itself)."""
        out = []
        if not self._seed_files() and not (self.memory.t0 and self.memory.t0["passed"]):
            out.append(f"Download Kraken's OHLCVT archive into {self.data_dir / 'kraken'} (no permission needed)")
        if self.memory.t2 and self.memory.t2["passed"]:
            out.append("T2 passed: T3 paper trading needs a market.paper_order lease from you")
        if not self.llm.ready():
            out.append("Install the local models once: python3 setup_models.py (about 22 GB; Apple silicon)"
                       if apple_silicon() else "Local models need a Mac with Apple silicon")
        return out

    def ladder_status(self) -> list[dict]:
        t0 = bool(self.memory.t0 and self.memory.t0["passed"])
        t2 = bool(self.memory.t2 and self.memory.t2["passed"])
        state = {"T0": t0, "T1": t0 and bool(self.memory.t1_pairs), "T2": t2, "T3": False, "T4": False, "T5": False}
        return [{"rung": r.id, "name": r.name, "passed": state[r.id], "gate": r.gate, "permission": r.permission}
                for r in cp.TRADING_LADDER]

    # -- development -----------------------------------------------------------------------------------
    def research_experiment(self, *a: Any, **k: Any) -> dict:
        before = self.champion_strategy
        out = super().research_experiment(*a, **k)
        for cid, c in self.promotion.base.candidates.items():   # make the archive rebuildable, statuses included
            if self.memory.archive.get(cid, {}).get("status") != c.status:
                self.authority.record("CandidateStatus", "evolution", "proposal",
                                      {"candidate": cid, "parent": c.parent_candidate_id, "mutation": c.mutation,
                                       "status": c.status, "benchmark": list(c.benchmark_vector)})
        if self.champion_strategy != before or self.memory.champion is None:
            self.authority.record("ChampionChanged", "evolution", "proposal", {"strategy": self.champion_strategy})
        self.authority.record("ResearchRun", "research", "proposal",
                              {"champion": self.champion_strategy, "accuracy": (self.last_bench or {}).get("accuracy")})
        return out

    def _work_on(self, name: str) -> dict:
        if name == "persistent memory":
            ok, detail = self.continuity()
            self.authority.record("MemorySnapshot", "organism", "proposal", {"ok": ok, "detail": detail,
                                                                             "digest": self.memory.digest()})
            self.frontier.complete(name)
            return {"memory_rebuilds": ok, "detail": detail}
        if name == "self-model":
            sm = build_self_model()
            (self.state_dir / "self_model.json").write_text(json.dumps(sm, indent=1))
            self.authority.record("SelfModelBuilt", "organism", "proposal", {"digest": sm["digest"], **sm["counts"]})
            self.frontier.complete(name)
            return sm["counts"]
        if name == "local reasoning model":
            return self._first_model_tasks(name)
        if name == "crypto corpus (T0)":
            r = self.crypto_t0()
            if r["t0"]["passed"]:
                self.frontier.complete(name)
            return r
        if name == "crypto research (T1)":
            r = self.crypto_t1()
            self.frontier.complete(name)
            return r
        if name == "trading simulation (T2)":
            r = self.crypto_t2()
            self.frontier.complete(name)
            return r
        if name == "live market feed":
            r = [self.fetch_endpoint("alternative.fng"), self.fetch_endpoint("mempool.difficulty")]
            self.frontier.complete(name)
            return {"reads": r}
        if name in RESEARCH_ITEMS:
            work = self.research_experiment()
            if work["champion"] != "flat_small" or self.research_runs > 1:
                self.frontier.complete(name)
            return work
        self.frontier.complete(name)
        return {"note": f"{name}: no executable organ yet in the reference build"}

    # -- local models ------------------------------------------------------------------------------------
    def _first_model_tasks(self, item: str) -> dict:
        """The local model's first organ work: a health check, reading APEX's own self-model (read-only), and
        whole-paper question answering scored against the research slice's answer key."""
        role = self.llm.role_for(self._band or "INCUBATING") or "fast"
        out: dict = {"role": role}
        try:
            hc = self.llm.ask("Reply with exactly one word: ready", role, max_tokens=64, purpose="health check")
            out["health"] = {"reply": hc.text[:40], "tokens_per_s": round(hc.tps, 1)}
            sm_file = self.state_dir / "self_model.json"
            sm = json.loads(sm_file.read_text()) if sm_file.exists() else build_self_model()
            rd = self.llm.ask(self_model_prompt(sm), role, max_tokens=700, purpose="self-model reading")
            (self.state_dir / "self_model_reading.md").write_text(rd.text)
            out["self_model_reading"] = rd.text[:400]
            correct = 0
            for q, expected in SAMPLE_QA:
                a = self.llm.ask(paper_qa_prompt(SAMPLE_PAPER, q), role, max_tokens=300, purpose="paper QA")
                correct += score_answer(a.text, expected)
            acc = round(correct / len(SAMPLE_QA), 4)
            self.authority.record("ModelBenchmark", "evaluator", "proposal",
                                  {"role": role, "task": "whole-paper QA (research slice)", "accuracy": acc,
                                   "retrieval_champion": self.champion_strategy,
                                   "retrieval_accuracy": (self.last_bench or {}).get("accuracy")})
            out["paper_qa_accuracy"] = acc
            self.frontier.complete(item)
        except RuntimeError as e:
            out["error"] = str(e)
            self.notes.append(f"local model '{role}' did not run: {e}")
        return out

    def ask(self, prompt: str, images: list[str] | None = None, deep: bool = False) -> dict:
        """Ask APEX's own local model. Its answer is Proposal-plane text: it informs, it never acts."""
        role = "deep" if deep and self.llm.ready("deep") else "fast"
        if not self.llm.ready(role):
            return {"reply": None, "note": "local models are not installed or verified yet (run setup_models.py)"}
        try:
            a = self.llm.ask(prompt, role, images=images, purpose="owner question")
        except RuntimeError as e:
            return {"reply": None, "error": str(e)}
        return {"reply": a.text, "role": role, "tokens_per_s": round(a.tps, 1), "observation": a.observation}

    def _channel_ok(self) -> bool:
        try:
            with (self.state_dir / "operator_outbox.jsonl").open("a"):
                pass
            return self.authority.ping() == "pong"
        except Exception:  # noqa: BLE001
            return False

    def heartbeat_tick(self, user_active: bool = False, body: BodyModel | None = None, t: float | None = None) -> dict:
        t_start = time.perf_counter()
        body = body or sense_body(user_active)
        avail = self.available()
        nxt = self.frontier.next(avail)
        temp = incubation_temperature(body, developmental_data=1.0 if nxt else 0.2)
        band = band_for(temp)
        switch = self.deadman.check(self._channel_ok(), self.scheduler.reserve_intact(), t)
        if switch == "DORMANT":
            band = "DORMANT"
            self.authority.record("DeadMansSwitch", "organism", "proposal", {"state": switch})
            self.operator.notify("Dead-man's switch: operator channel or scheduler unhealthy past the deadline; "
                                 "development paused", "critical")
        band = lower_band(band, self.hatch.cap)
        self._band = band
        self.scheduler.p3_allowed = band != "DORMANT"
        work = None
        if band != "DORMANT" and nxt:
            job = TieredJob(3, f"incubate:{nxt}", True, self.frontier.items[nxt].value(), cost=1.0)
            self.scheduler.submit(job)
            if job in self.scheduler.dispatch():
                try:
                    work = self._work_on(nxt)
                finally:
                    self.scheduler.complete(job)
                self.autonomous_work += 1
        self.ticks += 1
        status = self.authority.status()
        signals = {"authority_p95_ms": self.mystery.observe("authority_p95_ms", status["liveness_p95_ms"] or 0.0)}
        if work is None:
            signals["idle_heartbeat_ms"] = self.mystery.observe("idle_heartbeat_ms", (time.perf_counter() - t_start) * 1000)
        for stream, res in signals.items():
            if res in ("MYSTERY_CANDIDATE", "MYSTERY"):
                self.authority.record("MysteryCandidate", "organism", "proposal", {"stream": stream, "state": res})
        batch = self.mystery.due_notification(now())
        if batch:
            self.operator.notify(f"Unexplained behavior in {batch}", "warning")
        ckpt = {"ts": now(), "tick": self.ticks, "band": band, "temperature": round(temp, 4), "switch": switch,
                "hatch": self.hatch.stage, "band_cap": self.hatch.cap, "champion": self.champion_strategy,
                "frontier": self.frontier.ranked(avail)[:5], "homeostasis": self.regulator.state()}
        (self.state_dir / "checkpoint.json").write_text(json.dumps(ckpt, indent=2, default=str))
        self.authority.record("Heartbeat", "organism", "proposal", {k: v for k, v in ckpt.items() if k != "frontier"})
        return {**ckpt, "worked_on": nxt if work is not None else None, "work": work, "band_work": BAND_WORK[band],
                "signals": signals}

    # -- memory, sleep, hatching ----------------------------------------------------------------------------
    def continuity(self) -> tuple[bool, str]:
        """Criterion 10: the organism's live state must rebuild from the ledger alone."""
        if not verify_chain(self.ledger_path).ok:
            return False, "ledger chain broken"
        rebuilt = rebuild_memory(self.ledger_path)
        problems = []
        if rebuilt.digest() != self.memory.digest():
            problems.append("live memory differs from the ledger rebuild")
        done = {n for n, i in self.frontier.items.items() if i.done}
        if done != set(rebuilt.frontier_done) & set(self.frontier.items):
            problems.append(f"frontier differs: {sorted(done ^ set(rebuilt.frontier_done))}")
        for n, v in rebuilt.frontier_dT.items():
            if n in self.frontier.items and abs(self.frontier.items[n].dT - v) > 1e-9:
                problems.append(f"frontier priority differs for {n}")
        for cid, c in self.promotion.base.candidates.items():
            if rebuilt.archive.get(cid, {}).get("status") != c.status:
                problems.append(f"archive differs for {cid}")
        if rebuilt.champion not in (None, self.champion_strategy):
            problems.append("champion differs")
        return not problems, "; ".join(problems) or f"rebuilt from {self.ledger_path.name}: digest {rebuilt.digest()[:12]}"

    def sleep_cycle(self) -> dict:
        out = super().sleep_cycle()
        ok, detail = self.continuity()
        self.authority.record("MemorySnapshot", "organism", "proposal",
                              {"ok": ok, "detail": detail, "digest": self.memory.digest(), "after": "sleep"})
        return {**out, "memory_rebuilds": ok, "memory_detail": detail}

    def _operator_roundtrip(self, deadline_s: float = 2.0) -> tuple[bool, str]:
        """Criterion 9: halt and resume must work, and work fast, while the scheduler is loaded."""
        for i in range(6):
            self.scheduler.submit(TieredJob(3, f"load:{i}", True, 0.1, cost=1.0))
        self.scheduler.dispatch()
        t0 = time.perf_counter()
        try:
            self.operator.halt("hatch criterion 9: operator round-trip under load")
            ev = self.perceive({"probe": "operator round-trip"}, channel="system", source="hatch")
            blocked = self.act("probe while halted", "wall.probe", [ev])["decision"].result == "denied"
        finally:
            self.operator.resume("hatch criterion 9 complete")
        ev = self.perceive({"probe": "operator round-trip"}, channel="system", source="hatch")
        restored = self.act("probe after resume", "wall.probe", [ev])["decision"].result == "approved"
        dt = time.perf_counter() - t0
        ok = blocked and restored and dt < deadline_s
        return ok, f"halt blocked={blocked}, resume restored={restored}, round-trip {dt * 1000:.0f} ms"

    def hatch_readiness(self) -> HatchReadinessV4:
        status = self.authority.status()
        scratch = SealedPromotion(EvolutionaryArchive([True]))
        a = CandidateV3("a", None, "h", "m", [1.0]); b = CandidateV3("b", "a", "h", "m", [2.0])
        for c in (a, b):
            scratch.submit(c, LearningCandidate(c.candidate_id, "retrieval", "", "", [], []), {s: True for s in REQUIRED_SUITES})
            scratch.canary(c.candidate_id, lambda _: True)
        ledger = ContinuityLedger(self.ledger_path)
        rt_ok, rt_detail = self._operator_roundtrip()
        cont_ok, cont_detail = self.continuity()
        archive_states = {v.get("status") for v in self.memory.archive.values()}
        results = {
            "liveness": bool(status["liveness_ok"]) and self.scheduler.reserve_intact(),
            "state_recovery": verify_chain(self.ledger_path).ok and ledger.clock.value > 0 and status["charter"],
            "authority_isolation": self.isolated and getattr(self.authority, "pid", os.getpid()) != os.getpid(),
            "evaluation_loop": bool(self.promotion.history) or bool(archive_states & {"champion", "archived", "sealed-pass"}),
            "candidate_rollback": scratch.rollback() == "a",
            "research_loop": (self.research_runs > 0 and (self.last_bench or {}).get("accuracy", 0) > 0)
                             or self.memory.research_runs > 0,
            "scheduler_autonomy": self.autonomous_work > 0 or bool(self.memory.frontier_done),
            # v0.4: selection works if something is ready, or every remaining item is a recorded fork
            # waiting on a capability (keep going); an exhausted frontier is not a loss of development.
            "frontier_selection": bool(self.frontier.ranked(self.available()))
                                  or all(i.done for i in self.frontier.items.values()),
            "operator_roundtrip": rt_ok,
            "developmental_continuity": cont_ok,
        }
        h = HatchReadinessV4(results, {"operator_roundtrip": rt_detail, "developmental_continuity": cont_detail})
        stage, cap, failed = self.hatch.update(results)
        self.authority.record("HatchReadiness", "organism", "proposal",
                              {"results": results, "stage": stage, "band_cap": cap, "failed": failed, "H": h.vector,
                               "details": h.details})
        return h

    def morning_report(self) -> dict:
        rep = super().morning_report()
        rep.update({"version": VERSION, "hatch": {"stage": self.hatch.stage, "band_cap": self.hatch.cap},
                    "leases": [{k: l[k] for k in ("capability", "active", "via", "presence", "expires_at")}
                               for l in self.authority.leases()],
                    "ladder": [(r["rung"], r["passed"]) for r in self.ladder_status()],
                    "frontier": self.frontier.ranked(self.available())[:4], "notes": self.notes[-5:],
                    "owner_actions": self.owner_actions(),
                    "fetch_budget": self.fetcher.budget.usage(), "calibration": self.authority.calibration_status(),
                    "local_models": self.llm.status()})
        return rep

    def shutdown(self, record: bool = True) -> None:
        try:
            if record:
                self.authority.record("Asleep", "organism", "proposal", {"ticks": getattr(self, "ticks", 0)})
        finally:
            inner = getattr(self.authority, "_inner", self.authority)
            if isinstance(inner, IsolatedAuthority):
                inner.close()
            if hasattr(self, "market"):
                self.market.close()
            if hasattr(self, "llm"):
                self.llm.close()


def awaken_v04(state_dir: str | Path = "state", isolated: bool = True, **kw: Any) -> OrganismV4:
    return OrganismV4(state_dir, isolated, **kw)
