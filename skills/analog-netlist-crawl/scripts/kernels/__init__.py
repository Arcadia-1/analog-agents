"""Format-agnostic kernels.  Each consumes a Circuit and returns aggregates."""
from .r_network import (
    effective_resistance,
    resistance_matrix,
    within_net_pin_r,
    net_prescription,
    batch_prescription,
    _build_canonical_node_map,
    per_net_r_sum,
)
from .cg import per_net_cg_sum, cg_count_per_net
from .cc import per_pair_cc_sum, cc_count_per_pair

__all__ = [
    "effective_resistance",
    "resistance_matrix",
    "within_net_pin_r",
    "net_prescription",
    "_build_canonical_node_map",
    "per_net_r_sum",
    "per_net_cg_sum",
    "cg_count_per_net",
    "per_pair_cc_sum",
    "cc_count_per_pair",
]
