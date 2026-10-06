"""
Mock Athlete Profiles and Data Fixtures for Athlethium Test Harness.
"""

from core.models import UserProfile, Goal

CYCLIST_PROFILE = UserProfile(
    uid="cyclist_user_1",
    ctl=55.0,
    atl=35.0,
    weekly_hours=10.0,
    daily_available_hours=1.5,
    sports=["cycling", "strength"],
    focused_sports=["cycling"],
    equipment=["power_meter", "dumbbells", "bench"],
    intensity_weeks=3,
    injury=0,
    illness=0,
    ftp=280.0,
    ftp_cycling=280.0,
    fthr=172.0,
    daily_max_hours={
        "Monday": 1.0,
        "Tuesday": 1.5,
        "Wednesday": 1.5,
        "Thursday": 1.5,
        "Friday": 1.0,
        "Saturday": 3.0,
        "Sunday": 2.5
    },
    goal=Goal(
        name="Gran Fondo 120km",
        date="2026-10-20",  # ~8 weeks out
        type="event",
        sports=["cycling"]
    )
)

MARATHONER_PROFILE = UserProfile(
    uid="runner_user_2",
    ctl=45.0,
    atl=30.0,
    weekly_hours=7.0,
    daily_available_hours=1.0,
    sports=["running", "strength", "stretching"],
    focused_sports=["running"],
    equipment=["bodyweight", "resistance_bands"],
    intensity_weeks=3,
    injury=0,
    illness=0,
    ftp=220.0,
    ftp_running=260.0,
    ftp_pace_running=280.0,  # 4:40 min/km
    fthr=175.0,
    daily_max_hours={
        "Monday": 0.75,
        "Tuesday": 1.25,
        "Wednesday": 1.0,
        "Thursday": 1.25,
        "Friday": 0.75,
        "Saturday": 2.0,
        "Sunday": 1.5
    },
    goal=Goal(
        name="Autumn Marathon",
        date="2026-11-15",  # ~12 weeks out
        type="marathon",
        sports=["running"]
    )
)

TRIATHLETE_PROFILE = UserProfile(
    uid="triathlete_user_3",
    ctl=65.0,
    atl=45.0,
    weekly_hours=12.0,
    daily_available_hours=2.0,
    sports=["cycling", "running", "swimming", "strength"],
    focused_sports=["cycling", "running"],
    equipment=["power_meter", "swim_watch", "dumbbells"],
    intensity_weeks=3,
    injury=0,
    illness=0,
    ftp=260.0,
    fthr=170.0,
    daily_max_hours={
        "Monday": 1.0,
        "Tuesday": 2.0,
        "Wednesday": 2.0,
        "Thursday": 2.0,
        "Friday": 1.5,
        "Saturday": 3.5,
        "Sunday": 2.5
    },
    goal=Goal(
        name="70.3 Half Ironman",
        date="2026-09-30",  # ~5 weeks out
        type="triathlon",
        sports=["cycling", "running", "swimming"]
    )
)

FATIGUED_PROFILE = UserProfile(
    uid="fatigued_user_4",
    ctl=40.0,
    atl=75.0,  # TSB = -35 (Overreached / Deep Fatigue)
    weekly_hours=8.0,
    daily_available_hours=1.5,
    sports=["cycling"],
    focused_sports=["cycling"],
    equipment=["power_meter"],
    injury=0,
    illness=0
)

INJURED_PROFILE = UserProfile(
    uid="injured_user_5",
    ctl=50.0,
    atl=30.0,
    weekly_hours=8.0,
    daily_available_hours=1.5,
    sports=["running"],
    focused_sports=["running"],
    equipment=["bodyweight"],
    injury=2,  # Severe injury
    illness=0
)
