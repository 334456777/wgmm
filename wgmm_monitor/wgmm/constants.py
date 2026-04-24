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
