def attribute(terminal,initial,success_costs,failure_loss,holding_cost):
    # Costs/losses must be mutually exclusive realized amounts, not EV inputs.
    return {'terminal_minus_initial':terminal-initial,'success_costs':-success_costs,'failure_loss':-failure_loss,'holding_cost':-holding_cost,'net_usd':terminal-initial-success_costs-failure_loss-holding_cost}
