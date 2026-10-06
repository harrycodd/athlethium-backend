"""
Core Configuration and Constants for Athlethium Training Engine.
"""

# Coggan Power & Pace Intensity Zones (1 to 7)
INTENSITY_ZONES = {
    -1: {
        "name": "Rest Day",
        "zone": "Z0",
        "description": "Complete rest and active physiological recovery.",
        "tss_per_hour": 0
    },
    1: {
        "name": "Active Recovery",
        "zone": "Z1",
        "target_pct_ftp": (40, 55),
        "target_pct_hr": (50, 68),
        "description": "Very easy conversational pace. Promotes blood flow and lactate clearance.",
        "tss_per_hour": 35
    },
    2: {
        "name": "Endurance Base",
        "zone": "Z2",
        "target_pct_ftp": (56, 75),
        "target_pct_hr": (69, 83),
        "description": "All-day aerobic pace. Builds mitochondrial density, capillary beds, and fat oxidation.",
        "tss_per_hour": 50
    },
    3: {
        "name": "Tempo / Sweet Spot",
        "zone": "Z3",
        "target_pct_ftp": (76, 90),
        "target_pct_hr": (84, 94),
        "description": "Brisk sustained effort. High aerobic stimulus with manageable fatigue accumulation.",
        "tss_per_hour": 65
    },
    4: {
        "name": "Threshold",
        "zone": "Z4",
        "target_pct_ftp": (91, 105),
        "target_pct_hr": (95, 105),
        "description": "Lactate threshold sustained power. Increases time to exhaustion at race pace.",
        "tss_per_hour": 80
    },
    5: {
        "name": "VO2 Max",
        "zone": "Z5",
        "target_pct_ftp": (106, 120),
        "target_pct_hr": (106, 115),
        "description": "High-intensity aerobic capacity intervals. Expands maximal oxygen uptake ceiling.",
        "tss_per_hour": 95
    },
    6: {
        "name": "Anaerobic Capacity",
        "zone": "Z6",
        "target_pct_ftp": (121, 150),
        "target_pct_hr": (115, 125),
        "description": "Short all-out surges and attacks. Develops glycolytic power and punchiness.",
        "tss_per_hour": 110
    },
    7: {
        "name": "Neuromuscular Sprint",
        "zone": "Z7",
        "target_pct_ftp": (150, 250),
        "target_pct_hr": (100, 120),
        "description": "Maximal sprint power efforts. Recruits fast-twitch motor units.",
        "tss_per_hour": 120
    }
}

# TSS multipliers for quick estimation
TSS_MULTIPLIER_MAP = {
    -1: 0,
    0: 20,
    1: 35,
    2: 50,
    3: 65,
    4: 80,
    5: 95,
    6: 110,
    7: 120
}

# Standard Sport Weight Multipliers for hours allocation in multi-sport
SPORT_HOURS_WEIGHT = {
    "cycling": 4.0,
    "running": 2.0,
    "swimming": 1.5,
    "strength": 1.0,
    "stretching": 0.5,
    "yoga": 0.5
}

SUPPORTED_SPORTS = ["running", "cycling", "swimming", "strength", "stretching"]
SUPPORTED_UNITS = ["Metric", "Imperial"]
DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TARGET_CATEGORIES = ["all", "legs", "core", "upper", "other"]
BODY_AREAS = ["all", "core", "upper", "lower"]

# Equipment normalization mapping from frontend keys
EQUIPMENT_MAPPING = {
    "dumbbells": ["dumbbells", "kettlebells", "weights"],
    "kettlebell": ["kettlebells", "weights"],
    "pullUpBar": ["pullup_bar", "bodyweight"],
    "squatRack": ["barbell", "weights", "squat_rack", "bench"],
    "bench": ["bench"],
    "dipBar": ["dip_station", "bodyweight"],
    "cable": ["cables", "machine"],
    "latPulldown": ["lat_pulldown", "cables", "machine"],
    "flyMachine": ["machine"],
    "resistanceBands": ["bands"],
    "medicineBall": ["medicine_ball"]
}

