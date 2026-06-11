"""WGMM 算法默认参数."""

DEFAULT_DIMENSION_WEIGHTS = {
	"day": 0.5,
	"week": 1.0,
	"month_week": 0.3,
	"year_month": 0.2,
}

DEFAULT_SIGMAS = {
	"day": 0.8,
	"week": 1.0,
	"month_week": 1.5,
	"year_month": 2.0,
}

DEFAULT_WGMM_CONFIG = {
	"dimension_weights": DEFAULT_DIMENSION_WEIGHTS,
	"sigmas": DEFAULT_SIGMAS,
	"last_lambda": 0.0001,
	"last_pos_variance": 0.0,
	"last_neg_variance": 0.0,
	"last_update": 0,
	"next_check_time": 0,
	"is_manual_run": True,
	"discovered_periods": [],
}

LAMBDA_BASE = 0.0001
MAPPING_CURVE = 2.0
MIN_HISTORY_COUNT = 10
PRUNE_THRESHOLD = 1000
LOOKAHEAD_DAYS = 15
SECONDS_IN_DAY = 86400
FALLBACK_INTERVAL = 3600

# 风险率间隔上限(ADR 008): 间隔 <= HAZARD_CAP_K / sqrt(h(tau)).
# K 越大上限越松(请求越省、延迟越大); K=130 在 702 天回测上
# 以 +13% 请求换均值检测延迟 -57%/P90 -65%.
HAZARD_CAP_K = 130.0
HAZARD_CAP_NN_M = 5
HAZARD_CAP_TAIL_ALPHA = 1.2
HAZARD_CAP_FLOOR = 1800.0
HAZARD_CAP_MAX = float(LOOKAHEAD_DAYS * SECONDS_IN_DAY)
