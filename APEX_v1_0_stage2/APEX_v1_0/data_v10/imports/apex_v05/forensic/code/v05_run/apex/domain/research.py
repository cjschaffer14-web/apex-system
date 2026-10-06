from .base import DomainPack

RESEARCH_PACK = DomainPack(
    name="research",
    schemas=["document","section","paragraph","figure","table","equation","citation","claim"],
    tools=["document.read","symbolic.calculate","retrieval.search"],
    models=["local_reasoner","optional_cloud_peer"],
    evaluators=["whole_paper_synthesis","citation_grounding","equation_consistency"],
    risk_policy={"external_actuation":False},
    memory_rules={"preserve_page_refs":True,"reopen_raw_when_uncertain":True},
    benchmarks=["cross_section_synthesis","figure_text_integration","distant_evidence"],
    capabilities=["filesystem.read","retrieval.search"]
)
