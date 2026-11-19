"""Every tunable number of the verification system lives here, so rules can be tuned without
touching logic. Values marked (spec) come from the product brief; the rest are our assumptions."""
from decimal import Decimal

# Rule 1: reporter must be near the place (spec)
MAX_DISTANCE_M = 500
# A far (or location-less) report's author is treated as this fraction as trustworthy.
FAR_TRUST_FACTOR = Decimal("0.3")

# Rule 2: anomaly filter (spec)
ANOMALY_WINDOW_DAYS = 14
ANOMALY_MAX_DEVIATION = Decimal("0.40")     # more than +-40% from the median -> flagged
ANOMALY_MIN_SAMPLES = 3                     # fewer comparable reports -> no judgement

# Rule 3 + 4: confirmation (spec: 3 independent confirmations, or 1 + photo; trusted authors need fewer)
CONFIRM_THRESHOLD = Decimal("3.0")          # total confirmer weight needed by default
CONFIRM_THRESHOLD_TRUSTED = Decimal("2.0")  # author trust >= TRUST_TRUSTED
CONFIRM_THRESHOLD_EXPERT = Decimal("1.0")   # author trust >= TRUST_EXPERT
TRUST_TRUSTED = 70
TRUST_EXPERT = 90
PHOTO_MIN_CONFIRMATIONS = 1                 # a photo shortens the path to a single confirmation
# Confirmer weight = clamp(trust / 50, MIN, MAX): trust 50 -> 1.0, 100 -> 2.0, 20 -> 0.4
WEIGHT_TRUST_DIVISOR = Decimal("50")
WEIGHT_MIN = Decimal("0.4")
WEIGHT_MAX = Decimal("2.0")

# A flagged report is suspicious by definition: no trust discount, no photo shortcut,
# and it expires if nobody vouches for it.
FLAGGED_CONFIRM_THRESHOLD = Decimal("3.0")
FLAGGED_EXPIRY_HOURS = 48

# Rule 5: one report per user + place + product per window (spec)
RATE_LIMIT_HOURS = 6

# Points, trust and badges (assumptions; spec only says far reports earn no points)
POINTS_PER_REPORT = 5            # when submitted near the place
POINTS_REPORT_CONFIRMED = 10     # bonus when it becomes confirmed (near reports only)
POINTS_PER_CONFIRMATION = 1      # for vouching for someone else's open report
TRUST_GAIN_CONFIRMED = 2         # author, report confirmed
TRUST_GAIN_CONFIRMED_FAR = 1
TRUST_LOSS_REJECTED = 5
TRUST_MIN, TRUST_MAX = 0, 100

BADGE_REGULAR_POINTS = 20
BADGE_TRUSTED_POINTS, BADGE_TRUSTED_TRUST = 50, 70
BADGE_EXPERT_POINTS, BADGE_EXPERT_TRUST = 200, 90

# Context shown to the reporter right after submitting (rule 6)
CONTEXT_WINDOW_DAYS = 7
