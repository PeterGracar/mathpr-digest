# Configuration for the math.PR weekly digest
# Profile of Peter Gracar (https://gracar.org), used for relevance scoring
# and coauthor highlighting.

OWNER = "Peter Gracar"
PROFILE_URL = "https://gracar.org"

# arXiv category to track
CATEGORY = "math.PR"

# The earliest week (Monday) for which a digest should ever be built.
FIRST_WEEK_MONDAY = "2026-06-01"  # first week of June 2026

# arXiv announces new submissions only on weekdays (Mon–Fri), so a Mon–Sun week
# is treated as COMPLETE once its Friday has passed (e.g. the Saturday run). A
# week is still re-fetched on each run until it is "finalized" — kept open for a
# grace period past its nominal Sunday so any weekend-submitted papers that arXiv
# only announces the following week are captured before the week is frozen. A
# week is finalized once (today - its Sunday) exceeds this many days.
FINALIZE_GRACE_DAYS = 2

# --- Coauthors (from gracar.org publication list) -------------------------
# Names are matched against author lists after unicode-normalisation, so
# accents do not need to match exactly.
COAUTHORS = [
    "Alexander Drewitz",
    "Anh Duc Vu",
    "Arne Grauer",
    "Alexandre Stauffer",
    "Benedikt Jahnel",
    "Christian Monch",      # Mönch
    "Gioele Gallo",
    "Lukas Luchtrath",      # Lüchtrath
    "Markus Heydenreich",
    "Marilyn Korfhage",
    "Peter Morters",        # Mörters
]

# --- Relevance keywords ----------------------------------------------------
# Each tuple is (keyword/phrase, weight). Matching is case-insensitive on the
# concatenated title + abstract. Higher weights => stronger topical match to
# Peter's research (random geometric graphs, percolation, particle systems,
# spread of infection, scale-free / inhomogeneous spatial networks).
HIGH_KEYWORDS = [
    ("random connection model", 6),
    ("random geometric graph", 6),
    ("weight-dependent", 6),
	("random graph", 6),
    ("scale-free", 5),
    ("preferential attachment", 5),
    ("boolean model", 6),
    ("continuum percolation", 5),
    ("long-range percolation", 5),
    ("lipschitz percolation", 6),
    ("lipschitz surface", 6),
    ("chemical distance", 6),
    ("contact process", 5),
    ("spread of infection", 6),
    ("spread of information", 6),
    ("mobile agents", 6),
    ("mobile vertices", 6),
    ("giant component", 5),
    ("inhomogeneous", 4),
    ("spatial network", 5),
    ("age-dependent", 5),
    ("bose-einstein", 5),
    ("gelation", 4),
    ("recurrence and transience", 5),
    ("transience", 4),
    ("graphical construction", 3),
]
MED_KEYWORDS = [
    ("percolation", 4),
    ("random graph", 3),
    ("first passage percolation", 4),
    ("interacting particle system", 4),
    ("particle system", 3),
    ("point process", 3),
    ("poisson process", 3),
    ("epidemic", 3),
    ("sis", 2),
    ("sir", 2),
    ("branching random walk", 3),
    ("random walk", 2),
    ("phase transition", 3),
    ("configuration model", 3),
    ("complex network", 3),
    ("degree distribution", 3),
    ("hyperbolic random graph", 4),
    ("voronoi", 2),
    ("random conductance", 4),
    ("coalescent", 2),
    ("hypergraph", 2),
    ("erdos", 2),
    ("renyi", 2),
    ("stochastic geometry", 4),
    ("connectivity", 2),
    ("survival", 2),
]

# Score thresholds for bucketing
HIGH_THRESHOLD = 6   # >= goes to "Highly relevant"
MED_THRESHOLD = 3    # >= goes to "Possibly relevant"
