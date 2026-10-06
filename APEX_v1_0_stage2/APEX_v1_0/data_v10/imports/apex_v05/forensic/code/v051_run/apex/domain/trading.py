from .base import DomainPack

TRADING_PACK = DomainPack(
    name="trading",
    schemas=["market_event","signal","order_proposal","fill","position","pnl"],
    tools=["market.historical","market.live_data","market.paper_order"],
    models=["time_series","sentiment_adapter","strategy_researcher"],
    evaluators=["walk_forward","fees_slippage","partial_fill","reconciliation","drawdown"],
    risk_policy={"live_default":False,"kelly_is_domain_policy":True},
    memory_rules={"live_state_in_retrieval":True,"staleness_seconds":5},
    benchmarks=["T0_corpus","T1_research","T2_sim","T3_paper","T4_shadow","T5_live_authorized"],
    capabilities=["market.paper_order"]
)
